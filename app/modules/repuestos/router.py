"""Router del módulo repuestos (capa Router).

Endpoints:
- `GET /repuestos`: catálogo con búsqueda por texto y paginación (ADMIN, RECEPCION, MECANICO)
- `POST /repuestos`: alta de repuesto con stock inicial (ADMIN)
- `PATCH /repuestos/{id}`: modificación de precio o descripción (ADMIN)
- `DELETE /repuestos/{id}`: baja lógica (ADMIN)
- `POST /repuestos/{id}/reponer`: reposición de stock (ADMIN)
- `GET /repuestos/{id}/movimientos`: auditoría de movimientos (ADMIN, RECEPCION, MECANICO)
- `GET /repuestos/{id}/precios`: auditoría de precios (ADMIN, RECEPCION, MECANICO)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import UsuarioAutenticado, requiere_rol, usuario_actual
from app.core.paginacion import PaginaDe, ParametrosPagina
from app.modules.repuestos import service as servicio_repuestos
from app.modules.repuestos.schemas import (
    EntradaActualizarRepuesto,
    EntradaCrearRepuesto,
    EntradaReponerStock,
    SalidaHistorialPrecio,
    SalidaMovimientoStock,
    SalidaRepuesto,
)
from app.modules.repuestos.unit_of_work import UoWRepuestos

router = APIRouter(tags=["repuestos"])

ROLES_ADMIN = ("ADMIN",)
ROLES_CONSULTA = ("ADMIN", "RECEPCION", "MECANICO")


@router.get(
    "/repuestos",
    response_model=PaginaDe[SalidaRepuesto],
    dependencies=[Depends(requiere_rol(ROLES_CONSULTA))],
)
async def listar_repuestos(
    session: Annotated[AsyncSession, Depends(get_session)],
    parametros: Annotated[ParametrosPagina, Query()],
    q: str | None = Query(default=None, description="Búsqueda por código o descripción."),
) -> PaginaDe[SalidaRepuesto]:
    """Consulta el catálogo de repuestos activos con búsqueda y paginación (US-017)."""
    async with UoWRepuestos(session) as uow:
        pagina = await servicio_repuestos.buscar_repuestos_paginado(
            uow, q=q, parametros=parametros
        )
        return PaginaDe[SalidaRepuesto](
            items=[SalidaRepuesto.model_validate(r) for r in pagina.items],
            total=pagina.total,
            page=pagina.page,
            size=pagina.size,
            pages=pagina.pages,
        )


@router.post(
    "/repuestos",
    response_model=SalidaRepuesto,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_rol(ROLES_ADMIN))],
)
async def crear_repuesto(
    datos: EntradaCrearRepuesto,
    session: Annotated[AsyncSession, Depends(get_session)],
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> SalidaRepuesto:
    """Registra una nueva pieza con stock inicial opcional (US-018, RN-14)."""
    try:
        async with UoWRepuestos(session) as uow:
            repuesto = await servicio_repuestos.crear_repuesto(
                uow, datos, usuario_id=usuario.usuario.id
            )
            return SalidaRepuesto.model_validate(repuesto)
    except servicio_repuestos.CodigoRepuestoDuplicado as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.patch(
    "/repuestos/{id}",
    response_model=SalidaRepuesto,
    dependencies=[Depends(requiere_rol(ROLES_ADMIN))],
)
async def actualizar_repuesto(
    id: int,
    datos: EntradaActualizarRepuesto,
    session: Annotated[AsyncSession, Depends(get_session)],
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> SalidaRepuesto:
    """Modifica precio y/o descripción. Si cambia el precio, guarda historial (US-019, RN-20)."""
    try:
        async with UoWRepuestos(session) as uow:
            repuesto = await servicio_repuestos.actualizar_repuesto(
                uow, id, datos, usuario_id=usuario.usuario.id
            )
            return SalidaRepuesto.model_validate(repuesto)
    except servicio_repuestos.RepuestoNoEncontrado as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except servicio_repuestos.PrecioInvalido as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.delete(
    "/repuestos/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(requiere_rol(ROLES_ADMIN))],
)
async def dar_de_baja_repuesto(
    id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Baja lógica de un repuesto activo liberando su código (US-020, RN-16)."""
    try:
        async with UoWRepuestos(session) as uow:
            await servicio_repuestos.dar_de_baja_repuesto(uow, id)
    except servicio_repuestos.RepuestoNoEncontrado as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/repuestos/{id}/reponer",
    response_model=SalidaRepuesto,
    dependencies=[Depends(requiere_rol(ROLES_ADMIN))],
)
async def reponer_stock(
    id: int,
    datos: EntradaReponerStock,
    session: Annotated[AsyncSession, Depends(get_session)],
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> SalidaRepuesto:
    """Suma unidades de stock y asienta el movimiento en una transacción (US-021, RN-14)."""
    try:
        async with UoWRepuestos(session) as uow:
            repuesto = await servicio_repuestos.reponer_stock(
                uow, id, datos, usuario_id=usuario.usuario.id
            )
            return SalidaRepuesto.model_validate(repuesto)
    except servicio_repuestos.RepuestoNoEncontrado as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/repuestos/{id}/movimientos",
    response_model=list[SalidaMovimientoStock],
    dependencies=[Depends(requiere_rol(ROLES_CONSULTA))],
)
async def consultar_movimientos(
    id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SalidaMovimientoStock]:
    """Lista todos los movimientos históricos del repuesto especificado (US-022)."""
    try:
        async with UoWRepuestos(session) as uow:
            movimientos = await servicio_repuestos.listar_movimientos(uow, id)
            return [SalidaMovimientoStock.model_validate(m) for m in movimientos]
    except servicio_repuestos.RepuestoNoEncontrado as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/repuestos/{id}/precios",
    response_model=list[SalidaHistorialPrecio],
    dependencies=[Depends(requiere_rol(ROLES_CONSULTA))],
)
async def consultar_historial_precios(
    id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SalidaHistorialPrecio]:
    """Lista el historial de cambios de precio del repuesto especificado (US-022)."""
    try:
        async with UoWRepuestos(session) as uow:
            precios = await servicio_repuestos.listar_historial_precios(uow, id)
            return [SalidaHistorialPrecio.model_validate(p) for p in precios]
    except servicio_repuestos.RepuestoNoEncontrado as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
