"""Fixtures de la suite del núcleo (D9).

Reglas que respeta este archivo:

- La base de pruebas `taller_test` se crea y se migra **solo** con Alembic
  (`alembic upgrade head`): nunca `create_all` (regla dura, DD-08).
- Si PostgreSQL no responde, la suite se **salta** con un mensaje claro en
  lugar de fallar en rojo (supuesto de D9).
- Entre tests se limpian las tablas de acceso con
  `TRUNCATE ... RESTART IDENTITY`, así cada test arranca de cero.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import crear_fabrica_sesiones, crear_motor

RAIZ_DEL_PROYECTO = Path(__file__).resolve().parents[1]
BASE_DE_PRUEBAS = "taller_test"
TIEMPO_LIMITE_CONEXION = 3.0
TABLAS_DE_ACCESO = (
    "vehiculo",
    "cliente",
    "asignacion_rol",
    "intento_acceso",
    "evento_seguridad",
    "usuario",
)


def _settings_de_pruebas() -> Settings:
    """Settings apuntando a `taller_test` sin tocar el `.env` del proyecto."""
    return Settings(postgres_db=BASE_DE_PRUEBAS)


async def _conectar(settings: Settings, base: str) -> asyncpg.Connection:
    """Conexión corta a `base` con las credenciales de Settings (sin loguearlas)."""
    return await asyncpg.connect(
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=base,
        timeout=TIEMPO_LIMITE_CONEXION,
    )


async def _crear_base_si_falta(settings: Settings) -> None:
    """Crea `taller_test` desde `postgres` si no existe (tolera que ya exista)."""
    conexion = await _conectar(settings, "postgres")
    try:
        existe = await conexion.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", BASE_DE_PRUEBAS
        )
        if existe:
            return
        try:
            await conexion.execute(f'CREATE DATABASE "{BASE_DE_PRUEBAS}"')
        except asyncpg.DuplicateDatabaseError:  # carrera con otra corrida de la suite
            pass
    finally:
        await conexion.close()


@lru_cache(maxsize=1)
def _estado_de_postgres() -> tuple[bool, str]:
    """Detecta PostgreSQL una sola vez: (disponible, motivo del salto)."""
    try:
        settings = _settings_de_pruebas()
    except Exception:  # noqa: BLE001 — falta `.env`: se informa, no se revienta
        return (
            False,
            "Falta configuración en .env: no se puede preparar `taller_test`. "
            "La suite del núcleo se salta (D9).",
        )

    destino = f"{settings.postgres_host}:{settings.postgres_port}"

    async def _ping() -> None:
        conexion = await _conectar(settings, "postgres")
        await conexion.close()

    try:
        asyncio.run(_ping())
    except Exception as exc:  # noqa: BLE001 — cualquier fallo de conexión salta la suite
        return (
            False,
            f"PostgreSQL no responde en {destino} ({type(exc).__name__}): "
            "la suite del núcleo se salta (D9). Levantá la base y volvé a correr `pytest`.",
        )
    return True, ""


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Con PostgreSQL caído, marca todos los tests como saltados (no en rojo)."""
    disponible, motivo = _estado_de_postgres()
    if disponible:
        return
    marca = pytest.mark.skip(reason=motivo)
    for item in items:
        item.add_marker(marca)


def _migrar_base_de_pruebas() -> None:
    """Deja `taller_test` en `head` ejecutando Alembic como subproceso (task 2.1)."""
    entorno = {**os.environ, "POSTGRES_DB": BASE_DE_PRUEBAS}
    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=RAIZ_DEL_PROYECTO,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if resultado.returncode != 0:
        pytest.fail(
            "`alembic upgrade head` falló sobre "
            f"{BASE_DE_PRUEBAS}:\n{resultado.stderr[-2000:]}"
        )


@pytest.fixture(scope="session")
def base_de_pruebas() -> None:
    """Crea `taller_test` si falta y la migra una sola vez por sesión."""
    disponible, motivo = _estado_de_postgres()
    if not disponible:
        pytest.skip(motivo)
    asyncio.run(_crear_base_si_falta(_settings_de_pruebas()))
    _migrar_base_de_pruebas()


@pytest.fixture(scope="session")
async def motor_pruebas(base_de_pruebas: None) -> AsyncIterator[AsyncEngine]:
    """Motor asyncpg apuntando a `taller_test`, dispuesto al terminar la sesión."""
    motor = crear_motor(_settings_de_pruebas().database_url, echo=False, pool_size=5)
    try:
        yield motor
    finally:
        await motor.dispose()


@pytest.fixture(scope="session")
def fabrica_pruebas(motor_pruebas: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones de prueba (`expire_on_commit=False`, igual que la app)."""
    return crear_fabrica_sesiones(motor_pruebas)


async def _truncar(motor: AsyncEngine) -> None:
    """Vacía las tablas de acceso y reinicia las secuencias."""
    tablas = ", ".join(TABLAS_DE_ACCESO)
    async with motor.begin() as conexion:
        await conexion.execute(text(f"TRUNCATE TABLE {tablas} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def sesion(
    motor_pruebas: AsyncEngine,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Sesión limpia por test: trunca antes y después, y siempre la cierra."""
    await _truncar(motor_pruebas)
    async with fabrica_pruebas() as session:
        yield session
    await _truncar(motor_pruebas)
