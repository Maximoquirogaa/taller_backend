"""Router del módulo clientes (capa Router).

Endpoints:
- `POST /clientes`: alta sin usuario (RECEPCION, ADMIN)
- `GET /clientes/{id}`: detalle de cliente con vehículos precargados (RECEPCION, ADMIN)
- `POST /clientes/{id}/vehiculos`: alta de vehículo (RECEPCION, ADMIN)
- `DELETE /vehiculos/{id}`: baja lógica (RECEPCION, ADMIN)
- `GET /mis-vehiculos`: vehículos propios del cliente autenticado (cualquier usuario con ficha)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import UsuarioAutenticado, requiere_rol, usuario_actual
from app.modules.clientes import service as servicio_clientes
from app.modules.clientes.schemas import (
    EntradaCrearCliente,
    EntradaCrearVehiculo,
    SalidaCliente,
    SalidaClienteDetalle,
    SalidaVehiculo,
)
from app.modules.clientes.unit_of_work import UoWClientes

router = APIRouter(tags=["clientes"])

ROLES_GESTION = ("RECEPCION", "ADMIN")


@router.post(
    "/clientes",
    response_model=SalidaCliente,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_rol(ROLES_GESTION))],
)
async def crear_cliente(
    datos: EntradaCrearCliente,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SalidaCliente:
    """Registra un cliente de mostrador (sin usuario web) — solo RECEPCION o ADMIN."""
    try:
        cliente = await servicio_clientes.crear_cliente(UoWClientes(session), datos)
        return SalidaCliente.model_validate(cliente)
    except servicio_clientes.DocumentoDuplicado as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/clientes/{id}",
    response_model=SalidaClienteDetalle,
    dependencies=[Depends(requiere_rol(ROLES_GESTION))],
)
async def obtener_cliente(
    id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SalidaClienteDetalle:
    """Obtiene la ficha de un cliente con sus vehículos precargados — solo RECEPCION o ADMIN."""
    try:
        cliente = await servicio_clientes.obtener_cliente_detalle(
            UoWClientes(session), id
        )
        return SalidaClienteDetalle.model_validate(cliente)
    except servicio_clientes.ClienteNoEncontrado as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/clientes/{id}/vehiculos",
    response_model=SalidaVehiculo,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_rol(ROLES_GESTION))],
)
async def crear_vehiculo(
    id: int,
    datos: EntradaCrearVehiculo,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SalidaVehiculo:
    """Registra un vehículo asociado a un cliente — solo RECEPCION o ADMIN."""
    try:
        vehiculo = await servicio_clientes.crear_vehiculo(
            UoWClientes(session), id, datos
        )
        return SalidaVehiculo.model_validate(vehiculo)
    except servicio_clientes.ClienteNoEncontrado as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except servicio_clientes.PatenteDuplicada as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.delete(
    "/vehiculos/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(requiere_rol(ROLES_GESTION))],
)
async def dar_baja_vehiculo(
    id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Baja lógica de un vehículo si no tiene órdenes abiertas — solo RECEPCION o ADMIN."""
    try:
        await servicio_clientes.dar_baja_vehiculo(UoWClientes(session), id)
    except servicio_clientes.VehiculoNoEncontrado as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except servicio_clientes.VehiculoConOrdenesAbiertas as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/mis-vehiculos",
    response_model=list[SalidaVehiculo],
)
async def mis_vehiculos(
    usuario_aut: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SalidaVehiculo]:
    """Lista exclusivamente los vehículos propios del usuario autenticado (RN-17)."""
    vehiculos = await servicio_clientes.listar_mis_vehiculos(
        UoWClientes(session), usuario_aut.usuario.id
    )
    return [SalidaVehiculo.model_validate(v) for v in vehiculos]
