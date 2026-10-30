"""Endpoints de salud (spec `service-health`) — solo `router.py`, sin capas (SU-05, D5).

- `GET /health/live` → 200 sin tocar la base: "proceso vivo".
- `GET /health/ready` → `SELECT 1`: 200 si la base responde, 503 si no contesta:
  "servicio listo" (reiniciar el proceso no arregla una base caída).
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session

router = APIRouter(tags=["salud"])


@router.get("/health/live")
async def live() -> JSONResponse:
    """Liveness: responde 200 sin ejecutar ninguna consulta contra la base."""
    return JSONResponse(status_code=200, content={"estado": "vivo"})


@router.get("/health/ready")
async def ready(session: AsyncSession = Depends(get_session)) -> JSONResponse:
    """Readiness: `SELECT 1` → 200 si responde, 503 si la base no contesta.

    Cualquier fallo de conectividad se traduce en 503 con mensaje propio: no se
    expone texto interno de PostgreSQL (RN-18) y el error no se propaga como 500.
    """
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"estado": "no listo"})
    return JSONResponse(status_code=200, content={"estado": "listo"})
