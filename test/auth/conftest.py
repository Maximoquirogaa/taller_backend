"""Fixtures de integración para el grupo de rutas `/auth` (tarea 8).

- La API de pruebas corre **sobre `taller_test`**: antes de importar `main`, se
  fija `POSTGRES_DB` en el entorno (prioridad sobre `.env`), como ya hace el
  conftest del núcleo (nunca `create_all`; Alembic migró la base, DD-08).
- El lifespan de `main.py` se abre y cierra a mano (DD-09): `ASGITransport` de
  httpx no ejecuta el lifespan, así que los recursos (`motor`, fábrica,
  `settings`) se crean igual que en producción.
- Entre tests se truncan las tablas de acceso (mismo criterio que el conftest
  del núcleo): cada test arranca limpio.
"""

from __future__ import annotations

import os

# Debe ocurrir ANTES de importar `main` (que instancia sus Settings al importarse).
os.environ["POSTGRES_DB"] = "taller_test"  # noqa: E402 — la app de pruebas usa la base de pruebas

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text as consulta_sql  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine  # noqa: E402

# `python -m pytest` inserta la raíz del proyecto en `sys.path` (así lo importa el proyecto).
from main import app as aplicacion  # noqa: E402

TABLAS_DE_ACCESO = (
    "vehiculo",
    "cliente",
    "asignacion_rol",
    "intento_acceso",
    "evento_seguridad",
    "usuario",
)


async def _truncar_acceso(motor: AsyncEngine) -> None:
    """Vacía las tablas de acceso y reinicia las secuencias (entre tests)."""
    tablas = ", ".join(TABLAS_DE_ACCESO)
    async with motor.begin() as conexion:
        await conexion.execute(consulta_sql(f"TRUNCATE TABLE {tablas} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def cliente_auth(motor_pruebas: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """Cliente HTTP contra la app completa, con su lifespan abierto y base limpia."""
    await _truncar_acceso(motor_pruebas)
    async with aplicacion.router.lifespan_context(aplicacion):
        transport = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transport, base_url="http://taller.test") as cliente:
            yield cliente
    await _truncar_acceso(motor_pruebas)


@pytest.fixture
async def base_autenticada(cliente_auth: AsyncClient) -> AsyncIterator[AsyncClient]:
    """Cliente con la cookie de sesión ya puesta: registro + login exitosos."""
    registrando = await cliente_auth.post(
        "/auth/registro",
        json={
            "email": "laura@example.com",
            "nombre": "Laura Gómez",
            "password": "clave-segura-9",
        },
    )
    assert registrando.status_code == 201, registrando.text
    ingresando = await cliente_auth.post(
        "/auth/login",
        json={"email": "laura@example.com", "password": "clave-segura-9"},
    )
    assert ingresando.status_code == 200, ingresando.text
    yield cliente_auth
