"""Entorno de Alembic — plantilla ASINCRÓNICA (async_engine_from_config + run_sync).

La URL sale de `Settings` (.env / entorno): `alembic.ini` no guarda credenciales.
`target_metadata` es `SQLModel.metadata` y los modelos de cada módulo se importan
explícitamente acá (D6): este es el punto único que alimenta el autogenerate y la
consolidación final de C-11.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from alembic import context

from app.core.config import cargar_settings

# Importar el módulo registra sus tablas en `SQLModel.metadata` (D6). Cada change
# que agregue modelos suma su import acá.
from app.modules.usuarios import models as _modelos_usuarios  # noqa: F401
from app.modules.clientes import models as _modelos_clientes  # noqa: F401
from app.modules.repuestos import models as _modelos_repuestos  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL desde Settings (fallo temprano si faltan secretos, igual que la app).
# `%%` porque ConfigParser interpreta `%` (ver Config.set_main_option).
settings = cargar_settings()
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

# Metadata para autogenerate: todas las tablas registradas por los modelos (D6).
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Corre migraciones en modo offline: emite SQL sin conexión a la base."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Conecta con el motor asincrónico y corre las migraciones vía run_sync."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Corre migraciones en modo online contra la base (template async)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
