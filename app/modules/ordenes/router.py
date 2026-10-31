"""Endpoints del módulo ordenes (capa Router, grupo de rutas protegido).

Rutas:
- `POST /ordenes` — apertura (RECEPCION, ADMIN).
- `GET /ordenes` — listado paginado con filtro de estado (ADMIN, RECEPCION, MECANICO).
- `GET /ordenes/{id}` — detalle (staff ve cualquiera; CLIENTE solo la suya).
- `GET /estados-orden` — catálogo de estados (cualquier autenticado).
- `GET /mis-ordenes` — órdenes propias paginadas (cualquier autenticado).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import UsuarioAutenticado, requiere_rol, usuario_actual
from app.core.paginacion import PaginaDe, calcular_paginas, validar_pagina
from app.modules.ordenes import service as servicio_ordenes
from app.modules.ordenes.schemas import (
    ConsultaOrdenes,
    EntradaCrearOrden,
    SalidaClienteBreve,
    SalidaEstadoOrden,
    SalidaHistorialEstado,
    SalidaItemOrden,
    SalidaOrdenDetalle,
    SalidaOrdenResumen,
    SalidaRepuestoResumen,
    SalidaVehiculoResumen,
)
from app.modules.ordenes.unit_of_work import UoWOrdenes

router_ordenes = APIRouter(tags=["ordenes"])

ROLES_APERTURA = ("RECEPCION", "ADMIN")
ROLES_LISTA = ("ADMIN", "RECEPCION", "MECANICO")


def _detalle_a_salida(orden) -> SalidaOrdenDetalle:
    """Convierte una `OrdenTrabajo` ya cargada en `SalidaOrdenDetalle`.

    El `subtotal` se deriva de columnas persistidas (precio × cantidad) y no
    se guarda en la tabla (D7). Se accede a `vehiculo`, `cliente` y `repuesto`
    porque `get_detalle` los precarga (sin carga perezosa).
    """
    return SalidaOrdenDetalle(
        id=orden.id,
        estado=orden.estado,
        falla=orden.falla,
        creada_en=orden.creada_en,
        total=orden.total,
        vehiculo=SalidaVehiculoResumen(
            id=orden.vehiculo.id, patente=orden.vehiculo.patente
        ),
        cliente=SalidaClienteBreve(
            id=orden.vehiculo.cliente.id,
            nombre=orden.vehiculo.cliente.nombre,
            documento=orden.vehiculo.cliente.documento,
            telefono=orden.vehiculo.cliente.telefono,
        ),
        items=[
            SalidaItemOrden(
                id=item.id,
                repuesto_id=item.repuesto_id,
                repuesto=SalidaRepuestoResumen(
                    id=item.repuesto.id, codigo=item.repuesto.codigo
                ),
                cantidad=item.cantidad,
                precio_unitario=item.precio_unitario,
                subtotal=item.precio_unitario * item.cantidad,
            )
            for item in orden.items
        ],
        historial=[SalidaHistorialEstado.model_validate(h) for h in orden.historial],
    )


def _resumen_a_salida(orden) -> SalidaOrdenResumen:
    """Convierte una `OrdenTrabajo` cargada en `SalidaOrdenResumen`.

    `patente` se lee del vehículo precargado; no es columna de la orden.
    """
    return SalidaOrdenResumen(
        id=orden.id,
        vehiculo_id=orden.vehiculo_id,
        patente=orden.vehiculo.patente,
        falla=orden.falla,
        estado=orden.estado,
        creada_en=orden.creada_en,
        total=orden.total,
    )


@router_ordenes.post(
    "/ordenes",
    response_model=SalidaOrdenDetalle,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_rol(ROLES_APERTURA))],
)
async def crear_orden_endpoint(
    datos: EntradaCrearOrden,
    session: Annotated[AsyncSession, Depends(get_session)],
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> SalidaOrdenDetalle:
    """Abre una orden de trabajo de forma atómica (US-023, RN-10, RN-19).

    El servidor calcula el total y copia los precios; el cliente nunca los
    envía. Traduce las excepciones de dominio a 409/404 con `from exc`.
    """
    try:
        orden = await servicio_ordenes.crear_orden(
            UoWOrdenes(session), datos, usuario_id=usuario.usuario.id
        )
    except servicio_ordenes.CatalogoEstadosVacio as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except servicio_ordenes.RepuestoNoDisponible as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except servicio_ordenes.ConflictoComposicion as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except servicio_ordenes.VehiculoNoEncontrado as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except IntegrityError as exc:
        # Violación de integridad de la base (p. ej. carrera por el UNIQUE de
        # ítems): responde 409 con mensaje propio, sin texto de PostgreSQL (D5).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflicto de integridad al registrar la orden: verifique los datos.",
        ) from exc
    return _detalle_a_salida(orden)


@router_ordenes.get(
    "/ordenes",
    response_model=PaginaDe[SalidaOrdenResumen],
    dependencies=[Depends(requiere_rol(ROLES_LISTA))],
)
async def listar_ordenes(
    session: Annotated[AsyncSession, Depends(get_session)],
    consulta: Annotated[ConsultaOrdenes, Query()],
) -> PaginaDe[SalidaOrdenResumen]:
    """Listado paginado de órdenes con filtro opcional de estado (US-024).

    Un estado fuera del contrato es rechazado por FastAPI con 422 antes de
    consultar la base (D6).
    """
    async with UoWOrdenes(session) as uow:
        items, total = await uow.ordenes.buscar_paginado(
            consulta.estado, consulta.desplazamiento, consulta.size
        )
    pages = calcular_paginas(total, consulta.size)
    validar_pagina(consulta.page, pages)
    return PaginaDe[SalidaOrdenResumen](
        items=[_resumen_a_salida(o) for o in items],
        total=total,
        page=consulta.page,
        size=consulta.size,
        pages=pages,
    )


@router_ordenes.get("/ordenes/{orden_id}", response_model=SalidaOrdenDetalle)
async def obtener_orden(
    orden_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> SalidaOrdenDetalle:
    """Detalle de una orden (US-025, RN-17).

    Staff (ADMIN/RECEPCION/MECANICO) ve cualquiera; un CLIENTE solo ve la
    suya. Inexistente → 404; ajena → 403 (el 404 se evalúa primero para no
    filtrar existencia).
    """
    try:
        orden = await servicio_ordenes.obtener_detalle(
            UoWOrdenes(session), orden_id, usuario
        )
    except servicio_ordenes.OrdenNoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except servicio_ordenes.OrdenAjena as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return _detalle_a_salida(orden)


@router_ordenes.get("/estados-orden", response_model=list[SalidaEstadoOrden])
async def listar_estados_orden(
    session: Annotated[AsyncSession, Depends(get_session)],
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> list[SalidaEstadoOrden]:
    """Catálogo de estados de orden, ordenado por posición (US-029, RN-19).

    Cualquier usuario autenticado puede consultarlo.
    """
    estados = await servicio_ordenes.listar_estados(UoWOrdenes(session))
    return [SalidaEstadoOrden.model_validate(e) for e in estados]


@router_ordenes.get("/mis-ordenes", response_model=PaginaDe[SalidaOrdenResumen])
async def mis_ordenes(
    session: Annotated[AsyncSession, Depends(get_session)],
    consulta: Annotated[ConsultaOrdenes, Query()],
    usuario: Annotated[UsuarioAutenticado, Depends(usuario_actual)],
) -> PaginaDe[SalidaOrdenResumen]:
    """Órdenes propias del cliente autenticado, paginadas (US-030, RN-17).

    Un usuario sin ficha de cliente recibe una página vacía con 200 (D9).
    """
    pagina = await servicio_ordenes.listar_mis_ordenes(
        UoWOrdenes(session), usuario.usuario.id, consulta
    )
    return PaginaDe[SalidaOrdenResumen](
        items=[_resumen_a_salida(o) for o in pagina.items],
        total=pagina.total,
        page=pagina.page,
        size=pagina.size,
        pages=pagina.pages,
    )
