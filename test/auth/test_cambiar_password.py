"""Tests de integración de `POST /auth/cambiar-password` (RN-06, RN-07, US-007).

Comprueba el spec `user-auth`: hash nuevo fuera de la transacción, flag limpio,
`password_cambiada_en` anotado, cookie **nueva válida** y tokens anteriores
(emitidos medio segundo antes del cambio) → 401 por comparación sin truncar.
"""

from __future__ import annotations

import asyncio
import time

import jwt

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import security
from app.core.mensajes_auth import NOMBRE_COOKIE_SESION
from app.modules.usuarios.models import Usuario
from main import settings

ALGORITMO = security.ALGORITMO_JWT
CORREO_BASE = "laura@example.com"
CONTRASENA_BASE = "clave-segura-9"
CONTRASENA_NUEVA = "otra-clave-mas-2026"


@pytest.fixture
async def sesion_pruebas(
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Sesión directa a `taller_test` para asertar filas de `usuario`."""
    async with fabrica_pruebas() as session:
        yield session


async def _leer_usuario(sesion_pruebas: AsyncSession) -> Usuario:
    """El usuario registrado por el fixture `base_autenticada` (fuera de caché local)."""
    # La sesión del test puede tener la fila en su mapa de identidad con datos
    # anteriores al POST: se invalida para releer lo que la API dejó en la base.
    sesion_pruebas.expire_all()
    usuario = (
        await sesion_pruebas.execute(select(Usuario).where(Usuario.email == CORREO_BASE))
    ).scalar_one()
    assert usuario is not None
    return usuario


def _token_con_iat(id_usuario: int | None, marca: float, roles: list[str]) -> str:
    """Token manual con `iat` fijado al instante indicado (con fracciones, DD-05)."""
    return jwt.encode(
        {"sub": str(id_usuario), "iat": marca, "exp": marca + settings.token_expire_segundos, "roles": roles},
        settings.secret_key,
        algorithm=ALGORITMO,
    )


async def test_cambio_actualiza_hash_limpia_flag_y_valida_solo_cookie_nueva(
    base_autenticada: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """Cambiar con la contraseña actual correcta: 200, flag limpio y solo el token nuevo vale."""
    usuario_antes = await _leer_usuario(sesion_pruebas)
    hash_anterior = usuario_antes.password_hash
    token_viejo = base_autenticada.cookies.get(NOMBRE_COOKIE_SESION)
    assert token_viejo is not None

    respuesta = await base_autenticada.post(
        "/auth/cambiar-password",
        json={"password_actual": CONTRASENA_BASE, "password_nueva": CONTRASENA_NUEVA},
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["debe_cambiar_password"] is False
    assert cuerpo["expira_en_segundos"] == settings.token_expire_segundos
    assert CONTRASENA_NUEVA not in respuesta.text  # nunca viaja en el cuerpo
    token_nuevo = respuesta.cookies.get(NOMBRE_COOKIE_SESION)
    assert token_nuevo is not None  # la respuesta del cambio devuelve SU cookie válida
    conjunto = respuesta.headers["set-cookie"]
    assert "HttpOnly" in conjunto and "SameSite=lax" in conjunto  # misma mecánica del login

    # La jarra quedó con cookies duplicadas (login + cambio): se limpia; cada
    # verificación siguiente envía EXACTAMENTE una cookie por petición.

    usuario_despues = await _leer_usuario(sesion_pruebas)
    assert usuario_despues.password_hash.startswith("$2b$")
    assert usuario_despues.password_hash != hash_anterior  # hash nuevo distinto
    assert usuario_despues.debe_cambiar_password is False
    assert usuario_despues.password_cambiada_en is not None

    # Verificación unívoca (sin ambigüedades de la jarra): una sola cookie por petición.
    base_autenticada.cookies.clear()
    con_viejo = await base_autenticada.get("/auth/yo", cookies={NOMBRE_COOKIE_SESION: token_viejo})
    assert con_viejo.status_code == 401  # el token ANTERIOR murió (iat < cambio, RN-07)
    con_nuevo = await base_autenticada.get("/auth/yo", cookies={NOMBRE_COOKIE_SESION: token_nuevo})
    assert con_nuevo.status_code == 200, con_nuevo.text


async def test_cambio_con_contraseña_actual_incorrecta_no_cambia_nada(
    base_autenticada: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """401 y nada modificado: ni hash ni instante ni bandera."""
    usuario_antes = await _leer_usuario(sesion_pruebas)
    hash_anterior = usuario_antes.password_hash

    respuesta = await base_autenticada.post(
        "/auth/cambiar-password",
        json={"password_actual": "Contraseña-Equivocada-9", "password_nueva": CONTRASENA_NUEVA},
    )
    assert respuesta.status_code == 401

    usuario_despues = await _leer_usuario(sesion_pruebas)
    assert usuario_despues.password_hash == hash_anterior  # nada cambió
    assert usuario_despues.password_cambiada_en is None
    assert usuario_despues.debe_cambiar_password is False  # flag sin cambios

    # La sesión anterior no se rompió: la cookie (token viejo) sigue sirviendo.
    propio = await base_autenticada.get("/auth/yo")
    assert propio.status_code == 200


async def test_token_de_medio_segundo_antes_del_cambio_se_rechaza(
    base_autenticada: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """RN-07 sin truncar (DD-05): token con iat = cambio - 0.5 s → 401; iat posterior → 200."""
    respuesta = await base_autenticada.post(
        "/auth/cambiar-password",
        json={"password_actual": CONTRASENA_BASE, "password_nueva": CONTRASENA_NUEVA},
    )
    assert respuesta.status_code == 200
    usuario = await _leer_usuario(sesion_pruebas)
    assert usuario.password_cambiada_en is not None
    instante_cambio = usuario.password_cambiada_en.timestamp()
    # La jarra quedó con cookies duplicadas (login + respuesta del cambio): la
    # limpieza deja las verificaciones unívocas (una sola cookie por petición).
    base_autenticada.cookies.clear()

    # Las dos verificaciones van unívocas: una sola cookie por petición (sin jarra).
    token_anterior = _token_con_iat(usuario.id, instante_cambio - 0.5, roles=["CLIENTE"])
    rechazado = await base_autenticada.get("/auth/yo", cookies={NOMBRE_COOKIE_SESION: token_anterior})
    assert rechazado.status_code == 401  # murió aunque no esté vencido: iat < cambio (RN-07)

    # Token emitido DESPUÉS del cambio (medio segundo después): sí vale. PyJWT
    # rechaza tokens con `iat` a futuro (inmaduros), y el cambio ocurrió hace
    # apenas fracciones de segundo: se espera a que el reloj real pase su `iat`
    # antes de verificarlo (equivale a "el token ya se emitió y ya maduró").
    espera = (instante_cambio + 0.5) - time.time()
    await asyncio.sleep(espera + 0.05 if espera > 0 else 0.0)
    token_posterior = _token_con_iat(usuario.id, instante_cambio + 0.5, roles=["CLIENTE"])
    aceptado = await base_autenticada.get("/auth/yo", cookies={NOMBRE_COOKIE_SESION: token_posterior})
    assert aceptado.status_code == 200, aceptado.text


async def test_nueva_contrasena_invalida_responde_422(
    base_autenticada: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """La nueva contraseña pasa por el mismo contrato (422): sin espacios y ≤72 bytes."""
    usuario_antes = await _leer_usuario(sesion_pruebas)
    hash_anterior = usuario_antes.password_hash

    respuesta = await base_autenticada.post(
        "/auth/cambiar-password",
        json={"password_actual": CONTRASENA_BASE, "password_nueva": "sin numeros"},
    )
    assert respuesta.status_code == 422

    usuario_despues = await _leer_usuario(sesion_pruebas)
    assert usuario_despues.password_hash == hash_anterior  # nada cambió
