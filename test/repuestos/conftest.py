"""Fixtures de integración para las pruebas del módulo repuestos."""

from __future__ import annotations

import os

os.environ["POSTGRES_DB"] = "taller_test"

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as consulta_sql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core import security
from app.core.mensajes_auth import NOMBRE_COOKIE_SESION
from app.modules.usuarios.models import AsignacionRol, Usuario
from main import app as aplicacion, settings

TABLAS = (
    "historial_precio_repuesto",
    "movimiento_stock",
    "repuesto",
    "vehiculo",
    "cliente",
    "asignacion_rol",
    "intento_acceso",
    "evento_seguridad",
    "usuario",
)


async def _truncar_todo(motor: AsyncEngine) -> None:
    """Vacía las tablas y reinicia las secuencias."""
    tablas = ", ".join(TABLAS)
    async with motor.begin() as conexion:
        await conexion.execute(consulta_sql(f"TRUNCATE TABLE {tablas} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def cliente_http(motor_pruebas: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """Cliente HTTP contra la app con lifespan activo."""
    await _truncar_todo(motor_pruebas)
    async with aplicacion.router.lifespan_context(aplicacion):
        transport = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transport, base_url="http://test") as cliente:
            yield cliente
    await _truncar_todo(motor_pruebas)


@pytest.fixture
async def sesion_db(
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Sesión directa a la base de pruebas."""
    async with fabrica_pruebas() as session:
        yield session


async def autenticar_usuario(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
    email: str,
    rol: str,
    nombre: str = "Usuario Test",
) -> Usuario:
    """Crea usuario con rol en la base y setea la cookie de sesión en cliente_http."""
    hash_pass = await security.hash_password("password-test-123")
    usuario = Usuario(
        email=email,
        nombre=nombre,
        password_hash=hash_pass,
        activo=True,
        debe_cambiar_password=False,
    )
    sesion_db.add(usuario)
    await sesion_db.flush()

    asignacion = AsignacionRol(usuario_id=usuario.id, rol=rol)
    sesion_db.add(asignacion)
    await sesion_db.commit()

    token = security.crear_token_acceso(
        id_usuario=usuario.id,
        roles=[rol],
        secreto=settings.secret_key,
        expira_en_segundos=1800,
    )
    cliente_http.cookies.set(NOMBRE_COOKIE_SESION, token)
    return usuario
