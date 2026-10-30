"""Tests de integración del límite de intentos de login (RN-08, tareas 6 y 8).

- 5 intentos fallidos del mismo email+IP en 60 s → el login siguiente responde
  `429` con `Retry-After` **sin verificar la contraseña**: a diferencia del
  diseño tentativo en memoria, el conteo se hace **sobre la tabla
  `intento_acceso`** (regla RN-08 de la KB: "Conteo sobre intento_acceso"),
  que es lo que garantiza el índice (email, ip, cuando) creado en C-02.
- Un login correcto reinicia la cuenta: los fallos previos siguen en la tabla
  pero dejan de contar.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.usuarios.models import IntentoAcceso, Usuario

CORREO_BASE = "laura@example.com"
CONTRASENA_BASE = "clave-segura-9"
CORREO_INCORRECTO = "otro@example.com"
CONTRASENA_INCORRECTA = "Contraseña-Erronea-1"


@pytest.fixture
async def sesion_pruebas(
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Sesión directa a `taller_test` para inspección de intentos."""
    async with fabrica_pruebas() as session:
        yield session


async def _fallos(cliente_auth: AsyncClient, correo: str, cantidad: int) -> list[int]:
    """Envía `cantidad` logins fallidos y devuelve los códigos obtenidos."""
    codigos = []
    for _ in range(cantidad):
        respuesta = await cliente_auth.post(
            "/auth/login", json={"email": correo, "password": CONTRASENA_INCORRECTA}
        )
        codigos.append(respuesta.status_code)
    return codigos


async def _registrar(cliente_auth: AsyncClient, correo: str) -> None:
    """Registra una cuenta activa por la API (precondición de los tests de límite)."""
    respuesta = await cliente_auth.post(
        "/auth/registro",
        json={"email": correo, "nombre": "Laura Gómez", "password": CONTRASENA_BASE},
    )
    assert respuesta.status_code == 201, respuesta.text


async def test_quinto_intento_alcanza_el_limite_y_el_siguiente_responde_429(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """Los 5 fallos responden 401; el 6.º intento (con o sin cuenta) → 429 + Retry-After."""
    await _registrar(cliente_auth, CORREO_BASE)
    codigos = await _fallos(cliente_auth, CORREO_BASE, 5)
    assert codigos == [401] * 5

    bloqueado_mala = await cliente_auth.post(
        "/auth/login", json={"email": CORREO_BASE, "password": CONTRASENA_INCORRECTA}
    )
    assert bloqueado_mala.status_code == 429
    cabeceras = {clave.lower() for clave in bloqueado_mala.headers}
    assert "retry-after" in cabeceras
    assert int(bloqueado_mala.headers["retry-after"]) > 0

    # Y también con la contraseña CORRECTA: no se verifica nada (RN-08).
    bloqueado_correcta = await cliente_auth.post(
        "/auth/login", json={"email": CORREO_BASE, "password": CONTRASENA_BASE}
    )
    assert bloqueado_correcta.status_code == 429
    assert "retry-after" in {clave.lower() for clave in bloqueado_correcta.headers}

    # Quedaron 5 filas de fallo (el 6.º intento no se registra) + la del registro.
    intentos = (await sesion_pruebas.execute(select(IntentoAcceso))).scalars().all()
    fallos = [intento for intento in intentos if not intento.exito]
    assert len(fallos) == 5 and len(intentos) == 6  # registro añadó 1 exito inicial


async def test_login_correcto_reinicia_la_cuenta_de_fallos(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """Tras un éxito, los fallos previos no cuentan (RN-08) aunque sigan en la tabla."""
    await _registrar(cliente_auth, CORREO_BASE)
    assert set(await _fallos(cliente_auth, CORREO_BASE, 3)) == {401}
    acierto = await cliente_auth.post(
        "/auth/login", json={"email": CORREO_BASE, "password": CONTRASENA_BASE}
    )
    assert acierto.status_code == 200

    # Otros 3 fallos después del éxito: suma 4 en la ventana nueva; sin límite.
    assert set(await _fallos(cliente_auth, CORREO_BASE, 3)) == {401}
    segundo_acierto = await cliente_auth.post(
        "/auth/login", json={"email": CORREO_BASE, "password": CONTRASENA_BASE}
    )
    assert segundo_acierto.status_code == 200, "los fallos previos al último éxito no cuentan"

    # Los registros NO se borran (auditoría): quedan todos = 1 (registro) + 3 + 1 + 3 + 1.
    total = (
        await sesion_pruebas.execute(select(func.count()).select_from(IntentoAcceso))
    ).scalar_one()
    assert total == 9


async def test_otro_email_no_inicia_la_ventana_bloqueada(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """El límite es por combinación email+IP: otro email arranca con su cuenta propia."""
    assert set(await _fallos(cliente_auth, CORREO_BASE, 5)) == {401}

    contrasena_otro = "otro-pass-2026"
    registro = await cliente_auth.post(
        "/auth/registro",
        json={"email": CORREO_INCORRECTO, "nombre": "Otra Cuenta", "password": contrasena_otro},
    )
    assert registro.status_code == 201, registro.text
    respuesta_otro = await cliente_auth.post(
        "/auth/login", json={"email": CORREO_INCORRECTO, "password": contrasena_otro}
    )
    assert respuesta_otro.status_code == 200, respuesta_otro.text


async def test_usuario_anotado_reconoce_los_intentos_del_punto_de_vista_de_la_tabla(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """El intento (fallido) que bloquea se cuenta desde la tabla, no de un contador local."""
    await _registrar(cliente_auth, CORREO_BASE)
    await _fallos(cliente_auth, CORREO_BASE, 5)
    usuario = (
        await sesion_pruebas.execute(select(Usuario).where(Usuario.email == CORREO_BASE))
    ).scalar_one()
    assert usuario is not None  # precondition: la cuenta existe y no fue borrada
    filas = (await sesion_pruebas.execute(select(IntentoAcceso))).scalars().all()
    fallos = [fila for fila in filas if not fila.exito]
    assert len(fallos) == 5 and len(filas) == 6  # 5 fallos + la fila del registro
    assert {fila.ip for fila in filas} != {""}  # la IP quedó registrada en cada intento
