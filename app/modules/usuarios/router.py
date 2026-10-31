"""Endpoints del módulo usuarios (capa Router).

Dos routers:

- `router_auth` (`/auth`): grupo **abierto** (DD-10: salud y `/auth`). El token
  NUNCA viaja en el cuerpo (DD-04): la cookie se emite con `Set-Cookie`
  explícito (HttpOnly, SameSite=Lax, Max-Age, Secure configurable).
- `router_usuarios`: administración de personal, roles y auditoría (C-06). Se
  monta en `router_protegido` (`main.py`), así hereda el control del cambio de
  contraseña pendiente (RN-06) y exige `ADMIN` vigente en la base (RN-04).

Errores (RN-18): ninguna entrada inválida termina en 500 y ningún texto
interno de la base llega al cliente; `IntegrityError` → 409 con mensaje propio.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import UsuarioAutenticado, requiere_rol, usuario_actual
from app.core.mensajes_auth import (
    MENSAJE_CREDENCIALES_INVALIDAS,
    MENSAJE_EMAIL_DUPLICADO,
    MENSAJE_LIMITE_INTENTOS,
    MENSAJE_SESION_CERRADA,
    NOMBRE_COOKIE_SESION,
)
from app.core.security import crear_token_acceso
from app.modules.usuarios import service as servicio_usuarios
from app.modules.usuarios.schemas import (
    EntradaAsignarRol,
    EntradaCambioPassword,
    EntradaCrearUsuario,
    EntradaLogin,
    EntradaRegistro,
    SalidaAsignacionRol,
    SalidaLogin,
    SalidaRegistro,
    SalidaLogout,
    SalidaUsuario,
    SalidaYo,
)
from app.modules.usuarios.unit_of_work import UoWUsuarios

router_auth = APIRouter(prefix="/auth", tags=["auth"])
router_usuarios = APIRouter(tags=["usuarios"])

IP_DESCONOCIDA = "127.0.0.1"  # deploy sin `request.client` (p. ej. ASGI interno)
ROL_CLIENTE = "CLIENTE"  # rol único del auto-registro (consigna)
ROLES_ADMIN = ("ADMIN",)  # única autorización de la administración de personal


def _ip_de(request: Request) -> str:
    """IP del cliente o valor de contingencia si el canal ASGI no la entrega.

    Args:
        request: petición en curso.

    Returns:
        La IP textual del cliente (o `IP_DESCONOCIDA`).
    """
    cliente = request.client
    return cliente.host if cliente else IP_DESCONOCIDA


def _emitir_cookie_sesion(
    response: Response, request: Request, id_usuario: int, roles: list[str]
) -> None:
    """Firma el token y lo deja **solo** en la cookie HttpOnly (DD-04).

    Args:
        response: respuesta de la petición de login o de cambio de contraseña.
        request: petición (app.state.settings para secreto y vencimiento).
        id_usuario: id de la fila de usuario (`sub` del token).
        roles: roles vigentes al emitir (informativos, RN-04).
    """
    settings = request.app.state.settings
    token = crear_token_acceso(
        id_usuario, roles, settings.secret_key, settings.token_expire_segundos
    )
    response.set_cookie(
        key=NOMBRE_COOKIE_SESION,
        value=token,
        max_age=settings.token_expire_segundos,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


@router_auth.post("/registro", status_code=status.HTTP_201_CREATED, response_model=SalidaRegistro)
async def registro(
    datos: EntradaRegistro,
    request: Request,
    sesion: Annotated[AsyncSession, Depends(get_session)],
) -> SalidaRegistro:
    """US-003/RN-02: alta propia de cuenta de CLIENTE (usuario + rol + intento, un UoW).

    Args:
        datos: contrato validado (email único, nombre, contraseña con política).
        request: petición (la IP va al intento inicial de auditoría).
        sesion: sesión de la petición (la transacción la administra el servicio).

    Returns:
        Resumen sin hash ni token: email, nombre y rol asignado.

    Raises:
        HTTPException(409): email ya registrado (`IntegrityError` → mensaje propio).
        HTTPException(422): contrato inválido (Pydantic, con mensajes propios).
    """
    try:
        usuario = await servicio_usuarios.registrar_cliente(
            sesion, datos, _ip_de(request), request.app.state.settings.bcrypt_cost
        )
    except IntegrityError:
        # La base garantiza la unicidad (RN-01): se traduce limpio, sin texto de la base.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=MENSAJE_EMAIL_DUPLICADO
        ) from None
    return SalidaRegistro(email=usuario.email, nombre=usuario.nombre, rol=ROL_CLIENTE)


@router_auth.post("/login", response_model=SalidaLogin)
async def login(
    datos: EntradaLogin,
    response: Response,
    request: Request,
    sesion: Annotated[AsyncSession, Depends(get_session)],
) -> SalidaLogin:
    """US-004/RN-08/RN-09: sesión con cookie HttpOnly; 429 al límite; 401 idéntico siempre.

    Args:
        datos: credenciales (email + contraseña ≤ 72 bytes).
        response: respuesta para emitir la cookie (el token NUNCA en el cuerpo).
        request: petición (IP del límite y `app.state` para sesiones propias).
        sesion: sesión de la petición (lecturas del usuario y roles).

    Returns:
        Estado del cambio de contraseña y duración de la sesión, sin token.

    Raises:
        HTTPException(429): límite de intentos con `Retry-After` (sin tocar bcrypt).
        HTTPException(401): credenciales inválidas (un solo mensaje para todo caso).
        HTTPException(422): contraseña fuera de la política del contrato.
    """
    settings = request.app.state.settings
    try:
        usuario, roles = await servicio_usuarios.autentica(
            sesion,
            request.app.state.fabrica_sesiones,
            datos.email,
            datos.password,
            _ip_de(request),
            settings.bcrypt_cost,
        )
    except servicio_usuarios.LimiteIntentosAlcanzado as limite:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=MENSAJE_LIMITE_INTENTOS,
            headers={"Retry-After": str(limite.segundos_espera)},
        ) from None
    except servicio_usuarios.CredencialesInvalidas:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=MENSAJE_CREDENCIALES_INVALIDAS
        ) from None

    _emitir_cookie_sesion(response, request, usuario.id, roles)
    return SalidaLogin(
        debe_cambiar_password=usuario.debe_cambiar_password,
        expira_en_segundos=settings.token_expire_segundos,
    )


@router_auth.post("/logout", response_model=SalidaLogout)
async def logout(response: Response) -> SalidaLogout:
    """US-005: cierra la sesión borrando la cookie (no exige una sesión válida)."""
    response.delete_cookie(key=NOMBRE_COOKIE_SESION, path="/")
    return SalidaLogout(mensaje=MENSAJE_SESION_CERRADA)


@router_auth.get("/yo", response_model=SalidaYo)
async def yo(
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> SalidaYo:
    """US-006/RN-04: identidad propia con roles vigentes (base) y roles del token.

    Args:
        usuario: dependencia `usuario_actual` (401 si la sesión no vale).

    Returns:
        Email, nombre, flag de cambio y los dos conjuntos de roles separados.
    """
    return SalidaYo(
        email=usuario.usuario.email,
        nombre=usuario.usuario.nombre,
        debe_cambiar_password=usuario.debe_cambiar_password,
        roles_vigentes=usuario.roles_vigentes,
        roles_token=usuario.roles_token,
    )


@router_auth.post("/cambiar-password", response_model=SalidaLogin)
async def cambiar_password(
    datos: EntradaCambioPassword,
    response: Response,
    request: Request,
    sesion: Annotated[AsyncSession, Depends(get_session)],
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> SalidaLogin:
    """US-007/RN-07: cambio verificado; cookie nueva **después** de anotar el cambio.

    Args:
        datos: contraseña actual + nueva (mismo contrato de política).
        response: respuesta para emitir la cookie nueva (el token viejo muere).
        request: petición (app.state.settings para el secreto del token nuevo).
        sesion: sesión de la petición (el UoW del servicio la administra).
        usuario: dependencia de sesión (401 sin ella).

    Returns:
        Flag limpio y la duración del token nuevo, sin el token en el cuerpo.

    Raises:
        HTTPException(401): sesión inválida o contraseña actual incorrecta
            (nada se modifica).
        HTTPException(422): nueva contraseña fuera de la política del contrato.
    """
    settings = request.app.state.settings
    try:
        roles_nuevos = await servicio_usuarios.cambiar_password(
            sesion, usuario.usuario, datos, settings.bcrypt_cost
        )
    except servicio_usuarios.ContrasenaActualIncorrecta:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=MENSAJE_CREDENCIALES_INVALIDAS
        ) from None

    _emitir_cookie_sesion(response, request, usuario.id, roles_nuevos)
    return SalidaLogin(
        debe_cambiar_password=False,
        expira_en_segundos=settings.token_expire_segundos,
    )


# ── Administración de personal, roles y auditoría (C-06) ─────────────────────


@router_usuarios.post(
    "/usuarios",
    response_model=SalidaUsuario,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_rol(ROLES_ADMIN))],
)
async def crear_usuario(
    datos: EntradaCrearUsuario,
    sesion: Annotated[AsyncSession, Depends(get_session)],
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> SalidaUsuario:
    """US-008/RN-01/RN-06: alta de personal con contraseña provisoria y evento en el mismo UoW.

    Args:
        datos: contrato validado (email único, nombre y contraseña con política).
        sesion: sesión de la petición (el servicio abre la transacción del UoW).
        usuario: ADMIN autenticado; su email va como `actor` del evento (US-011).

    Returns:
        El usuario creado con `debe_cambiar_password=True`, sin hash ni contraseña.

    Raises:
        HTTPException(409): email ya registrado (excepción de dominio o
            `IntegrityError` de la base, siempre con mensaje propio).
        HTTPException(422): contrato inválido (Pydantic, antes de la transacción).
    """
    try:
        empleado = await servicio_usuarios.crear_empleado(
            UoWUsuarios(sesion), datos, actor_email=usuario.usuario.email
        )
    except servicio_usuarios.EmailUsuarioDuplicado as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except IntegrityError as exc:
        # Carrera de unicidad: la base decide (RN-01); no se filtra su texto.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=servicio_usuarios.MENSAJE_EMAIL_USUARIO_DUPLICADO,
        ) from exc
    return SalidaUsuario.model_validate(empleado)


@router_usuarios.post(
    "/usuarios/{id}/roles",
    response_model=SalidaAsignacionRol,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_rol(ROLES_ADMIN))],
)
async def otorgar_rol(
    id: int,
    datos: EntradaAsignarRol,
    sesion: Annotated[AsyncSession, Depends(get_session)],
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> SalidaAsignacionRol:
    """US-009/RN-03: abre una asignación de rol con vencimiento opcional.

    Args:
        id: usuario destinatario del rol.
        datos: `rol` del catálogo y `vencimiento` (con zona y futuro) opcional.
        sesion: sesión de la petición (el servicio abre la transacción del UoW).
        usuario: ADMIN autenticado; su id va en `otorgada_por` y su email al evento.

    Returns:
        La asignación abierta (o la nueva, tras cerrar una vencida).

    Raises:
        HTTPException(404): usuario inexistente (sin escribir nada).
        HTTPException(409): el rol ya está abierto y vigente (o el índice único
            parcial rechazó la carrera, siempre con mensaje propio).
        HTTPException(422): vencimiento sin zona, pasado o contrato inválido.
    """
    try:
        asignacion = await servicio_usuarios.otorgar_rol(
            UoWUsuarios(sesion),
            id,
            datos,
            actor_id=usuario.id,
            actor_email=usuario.usuario.email,
        )
    except servicio_usuarios.UsuarioNoEncontrado as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except servicio_usuarios.RolYaAsignado as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except servicio_usuarios.VencimientoInvalido as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except IntegrityError as exc:
        # El índice parcial `uq_asignacion_rol_abierta` es la garantía final (RN-03).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=servicio_usuarios.MENSAJE_ROL_YA_ASIGNADO,
        ) from exc
    return SalidaAsignacionRol.model_validate(asignacion)
