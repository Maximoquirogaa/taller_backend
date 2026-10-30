"""Dependencias de FastAPI: usuario actual, RBAC y cambio obligatorio (C-03).

- `usuario_actual` (specs `user-auth`): lee la cookie de sesión (DD-04: NUNCA
  `Authorization: Bearer`), valida el token, carga al usuario y sus roles
  vigentes de la base **en cada petición** (RN-04) y falla con 401 en todo
  caso de sesión inválida (sin cookie, firma mala, vencido, usuario inactivo o
  token anterior al cambio de contraseña — RN-07 con `iat` completo, DD-05).
- `requiere_rol(rol)`: dependencia que compone RBAC: 403 si el rol no está
  vigente en la base.
- `exige_sin_cambio_pendiente`: el control del cambio obligatorio de
  contraseña (RN-06), montado **una sola vez** sobre el grupo protegido
  (DD-10): 403 si el usuario tiene la bandera, y las rutas `/auth` y salud
  quedan fuera por diseño (están en el grupo abierto).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, NoReturn, Sequence

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.mensajes_auth import (
    MENSAJE_CAMBIO_PENDIENTE,
    MENSAJE_SESION_INVALIDA,
    MENSAJE_SIN_PERMISO,
    NOMBRE_COOKIE_SESION,
)
from app.core.security import decode_token, instantes_token_contra_cambio, TokenInvalido
from app.modules.usuarios.models import Usuario
from app.modules.usuarios.repository import RepositorioUsuarios, roles_vigentes_de


@dataclass(frozen=True)
class UsuarioAutenticado:
    """Todo lo que la petición conoce del usuario tras validar su sesión.

    Atributos:
        usuario: fila de `usuario` cargada de la base en esta petición.
        roles_vigentes: roles de `asignacion_rol` vigentes (la base manda, RN-04).
        roles_token: roles informativos del momento de emisión del token.
    """

    usuario: Usuario
    roles_vigentes: list[str]
    roles_token: list[str]

    @property
    def id(self) -> int:
        """Identificador del usuario, garantizado (fallo rápido si viniera None)."""
        if self.usuario.id is None:
            raise ValueError("El usuario autenticado debería tener id de la base")
        return self.usuario.id

    @property
    def debe_cambiar_password(self) -> bool:
        """Bandera de cambio obligatorio leída de la base en esta petición (RN-06)."""
        return self.usuario.debe_cambiar_password


def _falla_sesion() -> NoReturn:
    """Lanza el `HTTPException(401)` con el mensaje propio de sesión (sin detalle interno)."""
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=MENSAJE_SESION_INVALIDA,
    )


async def usuario_actual(
    request: Request,
    sesion: Annotated[AsyncSession, Depends(get_session)],
) -> UsuarioAutenticado:
    """Traduce la cookie de sesión al usuario vigente de la base (espeso: 401 si nada vale).

    Args:
        request: petición en curso; la cookie es la única fuente (DD-04) y la
            cabecera `Authorization` nunca se lee.
        sesion: sesión de la petición para consultar usuario y roles.

    Returns:
        El `UsuarioAutenticado` de esta petición (también queda en
        `request.state.usuario` para el resto de la pila).

    Raises:
        HTTPException(401): sin cookie, con token inválido/vencido/mal firmado,
            si el usuario no existe más, está desactivo o el token es anterior
            al último cambio de contraseña (RN-07, DD-05).
        ValueError: (defecto interno) si un usuario cargado no tuviera id.
    """
    settings = request.app.state.settings
    token = request.cookies.get(NOMBRE_COOKIE_SESION)
    if not token:
        _falla_sesion()

    try:
        payload = decode_token(token, settings.secret_key)
    except TokenInvalido:
        _falla_sesion()

    id_token = int(payload["sub"])
    usuario = await RepositorioUsuarios(sesion).get_by_id(id_token)
    if usuario is None or not usuario.activo:
        print(f"[DEBUG-401] usuario ausente/inactivo: id={id_token} usuario={usuario!r}")
        _falla_sesion()

    if instantes_token_contra_cambio(payload, usuario):
        _falla_sesion()  # token anterior a `password_cambiada_en` (RN-07, sin truncar)

    roles_vigentes = await roles_vigentes_de(sesion, usuario.id)
    identidad = UsuarioAutenticado(
        usuario=usuario,
        roles_vigentes=roles_vigentes,
        roles_token=list(payload["roles"]),
    )
    request.state.usuario = identidad
    return identidad


def requiere_rol(*roles: str | Sequence[str]):
    """Dependencia de RBAC: exige el rol (o al menos uno de ellos) **vigente en la base** en cada petición (RN-04).

    Args:
        roles: rol o roles del catálogo (`ADMIN`, `RECEPCION`, `MECANICO`, `CLIENTE`).

    Returns:
        La dependencia a montar (como `Depends(requiere_rol("ADMIN"))` o `Depends(requiere_rol("RECEPCION", "ADMIN"))`).

    Raises:
        TypeError: si ningún rol es válido o si un elemento no es `str` (fail-fast de la fábrica).
        HTTPException(401): si la sesión no es válida (por `usuario_actual`).
        HTTPException(403): si ninguno de los roles está vigente para el usuario: la
            revocación de roles alcanza a la sesión abierta sin esperar al
            vencimiento del token.
    """
    roles_efectivos: list[str] = []
    for r in roles:
        if isinstance(r, (list, tuple, set)):
            roles_efectivos.extend(r)
        elif isinstance(r, str):
            roles_efectivos.append(r)
        else:
            raise TypeError("El rol requerido debe ser una cadena de texto no vacía")

    if not roles_efectivos or any(not isinstance(r, str) or r == "" for r in roles_efectivos):
        raise TypeError("El rol requerido debe ser una cadena de texto no vacía")

    async def _comprobar(
        usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
    ) -> UsuarioAutenticado:
        """Dependencia real: valida rol vigente o dispara 403 con mensaje propio."""
        if not any(r in usuario.roles_vigentes for r in roles_efectivos):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=MENSAJE_SIN_PERMISO,
            )
        return usuario

    return _comprobar


async def exige_sin_cambio_pendiente(
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> UsuarioAutenticado:
    """Control del cambio obligatorio de contraseña, montado UNA vez (DD-10, RN-06).

    Args:
        usuario: la dependencia de sesión ya resolvió al usuario de la base.

    Returns:
        El mismo `UsuarioAutenticado` si no hay cambio pendiente (la ruta sigue).

    Raises:
        HTTPException(401): sin sesión válida (de `usuario_actual`).
        HTTPException(403): si el usuario tiene `debe_cambiar_password=True`:
            solo puede usar rutas de `/auth` y salud (que viven en el grupo
            abierto, por eso este control nunca las ve).
    """
    if usuario.debe_cambiar_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=MENSAJE_CAMBIO_PENDIENTE,
        )
    return usuario
