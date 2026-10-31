"""Fixtures de integración para las pruebas del módulo usuarios (C-06, task 1.1).

- La API de pruebas corre **sobre `taller_test`**: antes de importar `main` se fija
  `POSTGRES_DB` en el entorno (misma mecánica que `test/auth` y `test/repuestos`).
- No hay migración nueva (design.md, decisión 3): el esquema sale del head actual
  `004_repuestos_stock` y solo se truncan las tablas de acceso ya existentes.
- El lifespan de `main.py` se abre y cierra a mano (DD-09), porque
  `ASGITransport` de httpx no lo ejecuta.
- `autenticar_usuario` crea el usuario con su rol en la base y deja la cookie de
  sesión puesta en el cliente: la autorización siempre se lee de la base (RN-04).
"""

from __future__ import annotations

import os

# Debe ocurrir ANTES de importar `main` (que instancia sus Settings al importarse).
os.environ["POSTGRES_DB"] = "taller_test"  # noqa: E402 — la app de pruebas usa la base de pruebas

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text as consulta_sql  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker  # noqa: E402

from app.core import security  # noqa: E402
from app.core.mensajes_auth import NOMBRE_COOKIE_SESION  # noqa: E402
from app.modules.usuarios.models import AsignacionRol, Usuario  # noqa: E402
from main import app as aplicacion, settings  # noqa: E402

# Tablas de acceso del módulo (existen desde `001_esquema_inicial`): ninguna nueva.
TABLAS_DE_ACCESO = (
    "evento_seguridad",
    "asignacion_rol",
    "intento_acceso",
    "usuario",
)

CONTRASENA_DE_PRUEBA = "password-test-123"


async def _truncar_acceso(motor: AsyncEngine) -> None:
    """Vacía las tablas de acceso y reinicia las secuencias (entre tests)."""
    tablas = ", ".join(TABLAS_DE_ACCESO)
    async with motor.begin() as conexion:
        await conexion.execute(consulta_sql(f"TRUNCATE TABLE {tablas} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def cliente_http(motor_pruebas: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """Cliente HTTP contra la app completa, con lifespan abierto y base limpia."""
    await _truncar_acceso(motor_pruebas)
    async with aplicacion.router.lifespan_context(aplicacion):
        transport = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transport, base_url="http://taller.test") as cliente:
            yield cliente
    await _truncar_acceso(motor_pruebas)


@pytest.fixture
async def sesion_db(
    motor_pruebas: AsyncEngine,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Sesión directa a `taller_test`, con las tablas de acceso vacías al arrancar."""
    await _truncar_acceso(motor_pruebas)
    async with fabrica_pruebas() as session:
        yield session


async def autenticar_usuario(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
    email: str,
    rol: str,
    nombre: str = "Usuario Test",
    debe_cambiar_password: bool = False,
) -> Usuario:
    """Crea el usuario con su rol en la base y setea la cookie de sesión en el cliente.

    Args:
        cliente_http: cliente HTTP de la prueba (recibe la cookie `access_token`).
        sesion_db: sesión directa para sembrar usuario y asignación de rol.
        email: email único del usuario.
        rol: rol del catálogo que se abre para el usuario (RN-03).
        nombre: nombre visible del usuario.
        debe_cambiar_password: bandera de contraseña provisoria (RN-06).

    Returns:
        El `Usuario` persistido (con `id`).
    """
    hash_pass = await security.hash_password(CONTRASENA_DE_PRUEBA)
    usuario = Usuario(
        email=email,
        nombre=nombre,
        password_hash=hash_pass,
        activo=True,
        debe_cambiar_password=debe_cambiar_password,
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
