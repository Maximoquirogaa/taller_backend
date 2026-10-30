"""Entrada de la API: aplicación, lifespan y los dos grupos de rutas (DD-09, DD-10).

- Sin `SECRET_KEY` / `POSTGRES_PASSWORD` la app **no arranca**:
  `cargar_settings()` falla temprano con un mensaje propio (spec
  `service-configuration`), antes de que el lifespan siquiera se abra.
- El lifespan es el único dueño de los recursos caros: crea motor y fábrica de
  sesiones en `app.state` y dispone el motor al apagar (spec `service-lifespan`).
- Dos grupos de rutas desde el día uno: `router_abierto` (salud y futuro
  `/auth`) y `router_protegido` (vacío hasta C-03 — el control de cambio
  obligatorio se monta una sola vez; FastAPI suma dependencias, no las resta).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import getLogger

import uvicorn
from fastapi import APIRouter, FastAPI

from app.core.config import cargar_settings
from app.core.database import crear_fabrica_sesiones, crear_motor
from app.modules.health.router import router as router_salud

logger = getLogger("uvicorn.error")

# Fallo temprano: si faltan secretos, acá se corta con mensaje propio (no se
# construye nada más — el lifespan ni se abre).
settings = cargar_settings()

router_abierto = APIRouter()
router_protegido = APIRouter()  # vacío en C-01; se llena desde C-03 en adelante

router_abierto.include_router(router_salud)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Crea motor + fábrica en `app.state` al arrancar y dispone el motor al salir."""
    motor = crear_motor(
        settings.database_url,
        echo=settings.sql_echo,
        pool_size=settings.pool_size,
    )
    app.state.settings = settings
    app.state.motor = motor
    app.state.fabrica_sesiones = crear_fabrica_sesiones(motor)
    try:
        yield
    finally:
        await motor.dispose()
        logger.info("Motor asincrónico dispuesto: pool de conexiones liberado.")


app = FastAPI(title="TP Taller Mecánico", lifespan=lifespan)
app.include_router(router_abierto)
app.include_router(router_protegido)


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000)
