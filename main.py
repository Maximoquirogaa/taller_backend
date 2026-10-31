"""Entrada de la API: aplicación, lifespan y los dos grupos de rutas (DD-09, DD-10).

- Sin `SECRET_KEY` / `POSTGRES_PASSWORD` la app **no arranca**: `cargar_settings()`
  falla temprano con un mensaje propio (spec `service-configuration`), antes de
  que el lifespan siquiera se abra.
- El lifespan es el único dueño de los recursos caros: crea motor y fábrica de
  sesiones en `app.state` y dispone el motor al apagar (spec `service-lifespan`).
- Dos grupos de rutas desde C-03: `router_abierto` (salud + `/auth`) y
  `router_protegido` (vacío hasta C-04). El control de cambio de contraseña
  queda montado **una sola vez** como dependencia del grupo protegido (DD-10,
  RN-06): las rutas de C-04…C-11 lo heredan gratis — FastAPI suma dependencias
  y no las resta, por eso el control vive en el grupo y no ruta por ruta.
- El documento OpenAPI declara la seguridad real del proyecto: cookie
  `access_token` HttpOnly (DD-04). `Authorization: Bearer` jamás se acepta.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import getLogger
from typing import Any

import uvicorn
from fastapi import APIRouter, Depends, FastAPI
from fastapi.openapi.utils import get_openapi

from app.core.config import cargar_settings
from app.core.database import crear_fabrica_sesiones, crear_motor
from app.core.dependencies import exige_sin_cambio_pendiente
from app.modules.health.router import router as router_salud
from app.modules.usuarios.router import router_auth, router_usuarios
from app.modules.clientes.router import router as router_clientes
from app.modules.repuestos.router import router as router_repuestos

logger = getLogger("uvicorn.error")

# Fallo temprano: si faltan secretos, acá se corta con mensaje propio (no se
# construye nada más — el lifespan ni se abre).
settings = cargar_settings()

router_abierto = APIRouter()
router_protegido = APIRouter(dependencies=[Depends(exige_sin_cambio_pendiente)])

router_abierto.include_router(router_salud)
router_abierto.include_router(router_auth)
router_protegido.include_router(router_clientes)
router_protegido.include_router(router_repuestos)
router_protegido.include_router(router_usuarios)


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


def construir_openapi() -> dict[str, Any]:
    """Construye el esquema OpenAPI con la seguridad del proyecto (DD-04).

    La sesión vive en la cookie HttpOnly `access_token`: se declara en
    `components.securitySchemes` para que el documento refleje el mecanismo
    real (no existe un esquema Bearer en las rutas del proyecto).

    Returns:
        El esquema OpenAPI completo con `components.securitySchemes`.
    """
    esquema = get_openapi(
        title=app.title,
        version=app.version or "0.0.0",
        description="API del TP Taller Mecánico (sesión en cookie HttpOnly).",
        routes=app.routes,
    )
    esquema.setdefault("components", {})["securitySchemes"] = {
        "cookieAuth": {"type": "apiKey", "in": "cookie", "name": "access_token"}
    }
    return esquema


app.openapi = construir_openapi


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000)
