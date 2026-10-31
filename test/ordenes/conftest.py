"""Fixtures de integración para las pruebas del módulo órdenes (C-07).

Replica el patrón de `test/repuestos/conftest.py`:

- La app de pruebas corre sobre `taller_test` (se fija `POSTGRES_DB` antes de
  importar `main`).
- El `TRUNCATE` incluye las cuatro tablas nuevas de órdenes; `estado_orden` va
  incluida porque la migración 005 la deja vacía (DD-01).
- `catalogo` siembra PENDIENTE(1), EN_REPARACION(2), TERMINADA(3, final) y
  CANCELADA(4, final): es la fixture que reemplaza al seed de C-10.
"""

from __future__ import annotations

import os

os.environ["POSTGRES_DB"] = "taller_test"  # noqa: E402 — la app de pruebas usa la base de pruebas

from collections.abc import AsyncIterator  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text as consulta_sql  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker  # noqa: E402

from app.core import security  # noqa: E402
from app.core.mensajes_auth import NOMBRE_COOKIE_SESION  # noqa: E402
from app.modules.clientes.models import Cliente, Vehiculo  # noqa: E402
from app.modules.repuestos.models import Repuesto  # noqa: E402
from app.modules.usuarios.models import AsignacionRol, Usuario  # noqa: E402
from main import app as aplicacion, settings  # noqa: E402

TABLAS = (
    "historial_estado_orden",
    "item_orden",
    "orden_trabajo",
    "estado_orden",
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

# Catálogo canónico (KB 04 §estado_orden): la migración no lo carga (DD-01).
CATALOGO_ESTADOS = (
    ("PENDIENTE", "Pendiente de reparación", 1, False),
    ("EN_REPARACION", "En reparación", 2, False),
    ("TERMINADA", "Terminada", 3, True),
    ("CANCELADA", "Cancelada", 4, True),
)


async def _truncar_todo(motor: AsyncEngine) -> None:
    """Vacía las tablas y reinicia las secuencias."""
    tablas = ", ".join(TABLAS)
    async with motor.begin() as conexion:
        await conexion.execute(consulta_sql(f"TRUNCATE TABLE {tablas} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def cliente_http(motor_pruebas: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """Cliente HTTP contra la app con lifespan activo y base limpia."""
    await _truncar_todo(motor_pruebas)
    async with aplicacion.router.lifespan_context(aplicacion):
        transport = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transport, base_url="http://test") as cliente:
            yield cliente
    await _truncar_todo(motor_pruebas)


@pytest.fixture
async def sesion_db(
    motor_pruebas: AsyncEngine,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Sesión directa a la base de pruebas, con las tablas limpias."""
    await _truncar_todo(motor_pruebas)
    async with fabrica_pruebas() as session:
        yield session
    await _truncar_todo(motor_pruebas)


async def insertar_catalogo(sesion_db: AsyncSession) -> None:
    """Inserta el catálogo canónico de estados y confirma."""
    from app.modules.ordenes.models import EstadoOrden  # import local: existe tras la migración

    for codigo, descripcion, posicion, es_final in CATALOGO_ESTADOS:
        sesion_db.add(
            EstadoOrden(
                codigo=codigo,
                descripcion=descripcion,
                posicion=posicion,
                es_final=es_final,
            )
        )
    await sesion_db.commit()


@pytest.fixture
async def catalogo(sesion_db: AsyncSession) -> None:
    """Deja cargado el catálogo de estados (PENDIENTE…CANCELADA)."""
    await insertar_catalogo(sesion_db)


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


async def crear_cliente(
    sesion_db: AsyncSession,
    *,
    nombre: str,
    documento: str,
    telefono: str = "555-0000",
    usuario_id: int | None = None,
) -> Cliente:
    """Crea y confirma una ficha de cliente (opcionalmente ligada a un usuario)."""
    cliente = Cliente(
        nombre=nombre,
        documento=documento,
        telefono=telefono,
        usuario_id=usuario_id,
    )
    sesion_db.add(cliente)
    await sesion_db.commit()
    await sesion_db.refresh(cliente)
    return cliente


async def crear_vehiculo(
    sesion_db: AsyncSession,
    *,
    cliente_id: int,
    patente: str,
    borrado_en: datetime | None = None,
) -> Vehiculo:
    """Crea y confirma un vehículo del cliente."""
    vehiculo = Vehiculo(
        cliente_id=cliente_id,
        patente=patente,
        marca="Marca Test",
        modelo="Modelo Test",
        anio=2020,
        borrado_en=borrado_en,
    )
    sesion_db.add(vehiculo)
    await sesion_db.commit()
    await sesion_db.refresh(vehiculo)
    return vehiculo


async def crear_repuesto(
    sesion_db: AsyncSession,
    *,
    codigo: str,
    precio: str,
    stock: int = 10,
    borrado_en: datetime | None = None,
) -> Repuesto:
    """Crea y confirma un repuesto con precio Decimal."""
    repuesto = Repuesto(
        codigo=codigo,
        descripcion=f"Repuesto {codigo}",
        precio=Decimal(precio),
        stock=stock,
        borrado_en=borrado_en,
    )
    sesion_db.add(repuesto)
    await sesion_db.commit()
    await sesion_db.refresh(repuesto)
    return repuesto


def ahora_utc() -> datetime:
    """Instante UTC para fixtures que necesitan fechas explícitas."""
    return datetime.now(UTC)
