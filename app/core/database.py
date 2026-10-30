"""Motor asincrónico, fábrica de sesiones y sesión por petición (spec `service-lifespan`).

Nada se construye al importar este módulo (DD-09): el motor y la fábrica los crea
el lifespan de `main.py` y quedan en `app.state`; `get_session` entrega una
sesión por petición con `expire_on_commit=False` y la cierra al final.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def crear_motor(url: str, echo: bool = False, pool_size: int = 5) -> AsyncEngine:
    """Crea el motor asincrónico — sólo se llama desde el lifespan (nunca al importar)."""
    return create_async_engine(url, echo=echo, pool_size=pool_size)


def crear_fabrica_sesiones(motor: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones con `expire_on_commit=False` (atributos legibles tras commit)."""
    return async_sessionmaker(bind=motor, class_=AsyncSession, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Sesión por petición: la toma de `app.state.fabrica_sesiones` y la cierra siempre."""
    fabrica: async_sessionmaker[AsyncSession] = request.app.state.fabrica_sesiones
    session = fabrica()
    try:
        yield session
    finally:
        await session.close()
