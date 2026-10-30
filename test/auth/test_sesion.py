"""Tests de la sesión y la autorización: logout, `/auth/yo`, RBAC y cambios (US-005/006).

Comprueba el spec `user-auth`: logout borra cookie; `Authorization: Bearer`
nunca se lee (DD-04); token vencido/mal firmado → 401; usuario desactivado
→ 401; los roles **vigentes** salen de la base (RN-04) y los del token son
informativos; el control de cambio obligatorio bloquea el grupo protegido
(RN-06, DD-10).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import jwt
from fastapi import HTTPException

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import security
from app.core.dependencies import (
    UsuarioAutenticado,
    exige_sin_cambio_pendiente,
    requiere_rol,
)
from app.core.mensajes_auth import (
    MENSAJE_CAMBIO_PENDIENTE,
    MENSAJE_SESION_INVALIDA,
    MENSAJE_SIN_PERMISO,
    NOMBRE_COOKIE_SESION,
)
from app.modules.usuarios.models import AsignacionRol, Usuario
from main import settings

ALGORITMO = security.ALGORITMO_JWT
CORREO_BASE = "laura@example.com"
CONTRASENA_BASE = "clave-segura-9"


async def _registrar(
    cliente_auth: AsyncClient,
    sesion_pruebas: AsyncSession,
    correo: str,
    nombre: str,
) -> Usuario:
    """Registra un usuario por la API y devuelve su fila cargada de la base."""
    registrado = await cliente_auth.post(
        "/auth/registro",
        json={"email": correo, "nombre": nombre, "password": CONTRASENA_BASE},
    )
    assert registrado.status_code == 201, registrado.text
    usuario = (
        await sesion_pruebas.execute(select(Usuario).where(Usuario.email == correo))
    ).scalar_one()
    assert usuario is not None
    return usuario


def _token_manual(id_usuario: int, roles: list[str]) -> str:
    """Token válido emitido por `security` (para poner en la cookie a mano)."""
    return security.crear_token_acceso(
        id_usuario, roles, settings.secret_key, settings.token_expire_segundos
    )


def _usuario_falso(
    id_usuario: int, roles: tuple[str, ...], cambio_pendiente: bool = False
) -> UsuarioAutenticado:
    """Usuario autenticado de prueba para los tests unitarios de dependencias."""
    cuenta = Usuario(
        id=id_usuario,
        email=f"u{id_usuario}@example.com",
        nombre="Nadie",
        password_hash="$2b$12$hash-ficticio-de-prueba-para-los-tests",
        debe_cambiar_password=cambio_pendiente,
    )
    return UsuarioAutenticado(cuenta, roles, list(roles))


@pytest.fixture
async def sesion_pruebas(
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Sesión directa a `taller_test` para manipular asignaciones de rol."""
    async with fabrica_pruebas() as session:
        yield session


# ── logout (US-005) ──────────────────────────────────────────────────────────


async def test_logout_borra_la_cookie_y_responde_200(base_autenticada: AsyncClient) -> None:
    """Logout con sesión: 200 y orden de borrado de la cookie en la respuesta."""
    respuesta = await base_autenticada.post("/auth/logout")
    assert respuesta.status_code == 200, respuesta.text
    conjunto = respuesta.headers["set-cookie"]
    assert f'{NOMBRE_COOKIE_SESION}=""' in conjunto or "Max-Age=0" in conjunto

    # La orden de borrado deja al cliente fuera: la sesión ya no viaja.
    subsiguiente = await base_autenticada.get("/auth/yo")
    assert subsiguiente.status_code == 401


async def test_logout_sin_sesion_igual_responde_200(cliente_auth: AsyncClient) -> None:
    """Logout sin cookie: 200 igual (salir nunca exige una sesión válida)."""
    respuesta = await cliente_auth.post("/auth/logout")
    assert respuesta.status_code == 200


# ── /auth/yo con y sin sesión (US-006) ───────────────────────────────────────


async def test_yo_sin_cookie_o_con_token_malo_responde_401(cliente_auth: AsyncClient) -> None:
    """Sin cookie → 401; cookie con firma ajustada distinta → mismo 401 (sin detalle)."""
    sin = await cliente_auth.get("/auth/yo")
    assert sin.status_code == 401
    assert sin.json()["detail"] == MENSAJE_SESION_INVALIDA

    token_falso = jwt.encode(
        {"sub": "1", "iat": 1_000.0, "exp": 100_000_000_000.0, "roles": ["CLIENTE"]},
        "clave-distinta-a-la-real-muy-larga-!!",
        algorithm=ALGORITMO,
    )
    firmada_bien = await cliente_auth.get("/auth/yo", cookies={NOMBRE_COOKIE_SESION: token_falso})
    assert firmada_bien.status_code == 401
    assert firmada_bien.json()["detail"] == MENSAJE_SESION_INVALIDA


async def test_yo_con_bearer_header_y_cookie_corrupta(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """Bearer header no se acepta (DD-04): sin cookie → 401 aunque la cabecera traiga token."""
    usuario = await _registrar(cliente_auth, sesion_pruebas, CORREO_BASE, "Laura")
    token = _token_manual(usuario.id, ["CLIENTE"])

    bearer_sin_cookie = await cliente_auth.get(
        "/auth/yo", headers={"Authorization": f"Bearer {token}"}, cookies={}
    )
    assert bearer_sin_cookie.status_code == 401  # Bearer sin cookie → 401 (regla dura)


async def test_yo_con_token_de_usuario_inactivo_responde_401(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """El usuario se reconsulta en la base: desactivado con token vigente → 401."""
    usuario = await _registrar(cliente_auth, sesion_pruebas, "dormido@example.com", "Dormido")
    usuario.activo = False
    await sesion_pruebas.commit()

    token = _token_manual(usuario.id, ["CLIENTE"])
    respuesta = await cliente_auth.get("/auth/yo", cookies={NOMBRE_COOKIE_SESION: token})
    assert respuesta.status_code == 401


async def test_yo_con_token_de_valor_previo_no_lee_otra_cuenta(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """El `sub` del token se resuelve contra la base: id inexistente → 401 (sin fantasmas)."""
    token_huerfano = _token_manual(999_999, ["CLIENTE"])
    respuesta = await cliente_auth.get("/auth/yo", cookies={NOMBRE_COOKIE_SESION: token_huerfano})
    assert respuesta.status_code == 401


async def test_yo_con_token_vencido_responde_401(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """Token con vencimiento ya corrido → 401 (inválido o vencido: el mismo código)."""
    usuario = await _registrar(cliente_auth, sesion_pruebas, CORREO_BASE, "Laura")
    tiempo_vencido = 1_000.0
    token_vencido = jwt.encode(
        {"sub": str(usuario.id), "iat": tiempo_vencido, "exp": tiempo_vencido + 1.0, "roles": ["CLIENTE"]},
        settings.secret_key,
        algorithm=ALGORITMO,
    )
    respuesta = await cliente_auth.get("/auth/yo", cookies={NOMBRE_COOKIE_SESION: token_vencido})
    assert respuesta.status_code == 401


async def test_yo_a_la_vuelta_de_la_revocacion_rol_vigente(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """RN-04: la revocación vale en la PRÓXIMA petición, el token dijo lo que quiera."""
    usuario = await _registrar(cliente_auth, sesion_pruebas, "mixta@example.com", "Roles Mixtos")

    asignacion_revocada = AsignacionRol(
        usuario_id=usuario.id, rol="MECANICO", revocada_en=datetime.now(UTC)
    )
    sesion_pruebas.add(asignacion_revocada)
    await sesion_pruebas.commit()

    token = _token_manual(usuario.id, ["CLIENTE", "MECANICO"])  # informativo: dice MECANICO
    respuesta = await cliente_auth.get("/auth/yo", cookies={NOMBRE_COOKIE_SESION: token})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["roles_token"] == ["CLIENTE", "MECANICO"]  # informativos (del token)
    assert cuerpo["roles_vigentes"] == ["CLIENTE"]  # de la BASE: la revocada no vale
    assert cantidad_yo_vigente_solo_clientes(cuerpo) is True  # un solo rol vigente


def cantidad_yo_vigente_solo_clientes(cuerpo: dict[str, object]) -> bool:
    """Comprueba que la vigencia sea exactamente una por el rol del registro."""
    roles_vigentes = cuerpo.get("roles_vigentes")
    return isinstance(roles_vigentes, list) and roles_vigentes == ["CLIENTE"]


async def test_yo_antes_de_la_revocacion_consulta_asignacion_vigente(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """CAMBIO DE BANDERA (control): /auth/yo no ANULA vigencia pero CONSULTA la fila real."""
    usuario = await _registrar(cliente_auth, sesion_pruebas, "viva@example.com", "Asignada")
    sesion_pruebas.add(AsignacionRol(usuario_id=usuario.id, rol="MECANICO"))  # abierta (sin revoca)
    await sesion_pruebas.commit()

    token = _token_manual(usuario.id, ["CLIENTE"])  # el token ni siquiera dice MECANICO
    respuesta = await cliente_auth.get("/auth/yo", cookies={NOMBRE_COOKIE_SESION: token})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    # ROL VIGENTE en la base aunque el token no lo *"supiera"* → la base manda (RN-04):
    assert sorted(cuerpo["roles_vigentes"]) == ["CLIENTE", "MECANICO"]
    assert cuerpo["roles_token"] == ["CLIENTE"]


async def test_yo_devuelve_el_hash_en_ninguna_forma(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """La identidad y roles consultados no revelan el hash (RN-18)."""
    token = _token_manual(
        (await _registrar(cliente_auth, sesion_pruebas, CORREO_BASE, "Laura")).id, ["CLIENTE"]
    )
    respuesta = await cliente_auth.get("/auth/yo", cookies={NOMBRE_COOKIE_SESION: token})
    assert respuesta.status_code == 200
    assert "password_hash" not in respuesta.text
    assert CONTRASENA_BASE not in respuesta.text  # ni un rastro del texto plano


# ── dependencias unitarias: RBAC y cambio obligatorio (RN-04, RN-06, DD-10) ──


async def test_requiere_rol_permite_con_rol_vigente_y_deniega_sin_rol() -> None:
    """`requiere_rol(rol)` devuelve el usuario si el rol está vigente; 403 si no."""
    dependencia_admin = requiere_rol("ADMIN")
    con_rol = await dependencia_admin(_usuario_falso(1, ("ADMIN", "CLIENTE")))
    assert con_rol.roles_vigentes[0] == "ADMIN"

    sin_rol = requiere_rol("ADMIN")
    with pytest.raises(HTTPException) as excepcion:
        await sin_rol(_usuario_falso(2, ("CLIENTE",)))
    assert excepcion.value.status_code == 403
    assert excepcion.value.detail == MENSAJE_SIN_PERMISO


async def test_cambio_obligatorio_bloquea_con_flag_y_pasa_sin_flag() -> None:
    """El guard del grupo protegido: 403 con la bandera, usuario sin flag pasa (DD-10)."""
    with pytest.raises(HTTPException) as excepcion:
        await exige_sin_cambio_pendiente(_usuario_falso(3, ("CLIENTE",), cambio_pendiente=True))
    assert excepcion.value.status_code == 403
    assert excepcion.value.detail == MENSAJE_CAMBIO_PENDIENTE

    usuario = await exige_sin_cambio_pendiente(
        _usuario_falso(4, ("CLIENTE",), cambio_pendiente=False)
    )
    assert usuario.roles_token == ["CLIENTE"]  # lo devuelve a la lógica de la ruta
