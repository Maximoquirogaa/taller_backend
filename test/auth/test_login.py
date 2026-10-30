"""Tests de integración de `POST /auth/login` (US-004, RN-08, RN-09, DD-04).

Comprueba el spec `user-auth`: 200 con cookie HttpOnly/SameSite=Lax y cuerpo
sin token; 401 idéntico exista o no el email (hash ficticio, DD-06); usuario
inactivo → 401 genérico; y el límite de intentos fallidos se cuenta sobre la
tabla `intento_acceso` en su transacción propia (DD-07).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.mensajes_auth import MENSAJE_CREDENCIALES_INVALIDAS, NOMBRE_COOKIE_SESION
from app.modules.usuarios.models import IntentoAcceso, Usuario

CORREO_BASE = "laura@example.com"
CONTRASENA_BASE = "clave-segura-9"


@pytest.fixture
async def sesion_pruebas(
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Sesión directa a `taller_test` para ver lo que la API dejó en la base."""
    async with fabrica_pruebas() as session:
        yield session


async def _registrar(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession, correo: str
) -> None:
    """Registra una cuenta activa por la API (precondición de los tests de login)."""
    respuesta = await cliente_auth.post(
        "/auth/registro",
        json={"email": correo, "nombre": "Laura Gómez", "password": CONTRASENA_BASE},
    )
    assert respuesta.status_code == 201, respuesta.text
    total = (
        await sesion_pruebas.execute(select(func.count()).select_from(Usuario))
    ).scalar_one()
    assert total == 1


async def _registrar_y_desactivar(
    cliente_auth: AsyncClient,
    sesion_pruebas: AsyncSession,
    correo: str = "dormido@example.com",
) -> None:
    """Deja un usuario registrado pero desactivado (activo=False)."""
    await cliente_auth.post(
        "/auth/registro",
        json={"email": correo, "nombre": "Usuario Dormido", "password": CONTRASENA_BASE},
    )
    usuario = (
        await sesion_pruebas.execute(select(Usuario).where(Usuario.email == correo))
    ).scalar_one()
    usuario.activo = False
    await sesion_pruebas.commit()


async def test_login_correcto_manda_cookie_httponly_y_cuerpo_sin_token(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """200 con la cookie HttpOnly/SameSite=Lax y el cuerpo sin token (DD-04)."""
    await _registrar(cliente_auth, sesion_pruebas, CORREO_BASE)
    respuesta = await cliente_auth.post(
        "/auth/login", json={"email": CORREO_BASE, "password": CONTRASENA_BASE}
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"debe_cambiar_password", "expira_en_segundos"}
    assert cuerpo["debe_cambiar_password"] is False
    assert cuerpo["expira_en_segundos"] == 1800  # TOKEN_EXPIRE_SEGUNDOS (SU-01)

    conjunto_cookie = respuesta.headers["set-cookie"]
    assert f"{NOMBRE_COOKIE_SESION}=" in conjunto_cookie
    assert "HttpOnly" in conjunto_cookie
    assert "SameSite=lax" in conjunto_cookie  # DD-04 (no se acepta `Lax` con mayúscula)


async def test_login_fallido_igual_con_email_inexistente_o_contrasena_mala(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """Mismo código y mensaje exista o no la cuenta; ambos intentos quedan (DD-06, RN-09)."""
    await _registrar(cliente_auth, sesion_pruebas, CORREO_BASE)
    sin_cuenta = await cliente_auth.post(
        "/auth/login", json={"email": "fantasma@example.com", "password": CONTRASENA_BASE}
    )
    con_cuenta = await cliente_auth.post(
        "/auth/login", json={"email": CORREO_BASE, "password": "Contraseña-Mala-9"}
    )
    assert sin_cuenta.status_code == con_cuenta.status_code == 401
    assert sin_cuenta.json()["detail"] == con_cuenta.json()["detail"] == MENSAJE_CREDENCIALES_INVALIDAS
    intentos = (await sesion_pruebas.execute(select(IntentoAcceso))).scalars().all()
    # orden por llegada: el registro inicial (exito=True) + los 2 fallos
    assert [intento.exito for intento in intentos] == [True, False, False]
    assert {intento.email for intento in intentos} == {
        "fantasma@example.com",
        CORREO_BASE,
    }  # el intento sin cuenta también queda registrado


async def test_login_usuario_inactivo_responde_el_mismo_401(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """El estado activo se reconsulta en la base; el mensaje no aclara el motivo (RN-09)."""
    await _registrar_y_desactivar(cliente_auth, sesion_pruebas)
    respuesta = await cliente_auth.post(
        "/auth/login", json={"email": "dormido@example.com", "password": CONTRASENA_BASE}
    )
    assert respuesta.status_code == 401
    assert respuesta.json()["detail"] == MENSAJE_CREDENCIALES_INVALIDAS
    intentos = (await sesion_pruebas.execute(select(IntentoAcceso))).scalars().all()
    assert [intento.exito for intento in intentos] == [True, False]  # registro + fallo anotado


async def test_login_contrasena_de_mas_de_72_bytes_rechazada_por_contrato(
    cliente_auth: AsyncClient,
) -> None:
    """El contrato valida la contraseña (≤ 72 bytes) → 422, no error interno (RN-18)."""
    respuesta = await cliente_auth.post(
        "/auth/login", json={"email": CORREO_BASE, "password": "a" * (72 + 1)}
    )
    assert respuesta.status_code == 422, respuesta.text


async def test_login_con_intentos_queda_registrado_respetando_la_tabla(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """Los intentos (éxito y fallos) se registran en `intento_acceso` (DD-07)."""
    await _registrar(cliente_auth, sesion_pruebas, CORREO_BASE)
    fallo = await cliente_auth.post(
        "/auth/login", json={"email": CORREO_BASE, "password": "erronea-Pass-1"}
    )
    assert fallo.status_code == 401
    acierto = await cliente_auth.post(
        "/auth/login", json={"email": CORREO_BASE, "password": CONTRASENA_BASE}
    )
    assert acierto.status_code == 200
    total = (
        await sesion_pruebas.execute(select(func.count()).select_from(IntentoAcceso))
    ).scalar_one()
    assert total == 3  # registro (exito) + fallo + acierto, cada uno en su transacción (DD-07)
