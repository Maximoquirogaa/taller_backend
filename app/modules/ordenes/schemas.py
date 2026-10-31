"""Contratos de entrada/salida del módulo ordenes (Pydantic, extra="forbid").

Define los schemas de entrada para abrir una orden, los de respuesta para el
listado, detalle, catálogo de estados e historial, y el enum de códigos de
estado que valida el contrato de consulta de `GET /ordenes`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.core.paginacion import ParametrosPagina


class EstadoOrdenCodigo(StrEnum):
    """Códigos de estado del catálogo aceptados por contrato (D6).

    Se mantiene en Python para que un valor fuera del catálogo (p. ej.
    `INVENTADO`) se rechace con 422 antes de tocar la base de datos.
    """

    PENDIENTE = "PENDIENTE"
    EN_REPARACION = "EN_REPARACION"
    TERMINADA = "TERMINADA"
    CANCELADA = "CANCELADA"


class ItemEntrada(BaseModel):
    """Ítem que solicita abrir: un repuesto y su cantidad (sin precio).

    El precio nunca lo envía el cliente: el servidor lo copia del repuesto
    vigente (RN-10/RN-20).
    """

    model_config = ConfigDict(extra="forbid")

    repuesto_id: Annotated[int, Field(gt=0)]
    cantidad: Annotated[int, Field(gt=0)]


class EntradaCrearOrden(BaseModel):
    """Contrato de entrada de `POST /ordenes` (US-023).

    Solo recibe `vehiculo_id`, `falla` e `items`. `precio_unitario`,
    `total` y `estado` son calculados por el servidor y están prohibidos en
    el cuerpo (`extra="forbid"`).
    """

    model_config = ConfigDict(extra="forbid")

    vehiculo_id: Annotated[int, Field(gt=0)]
    falla: Annotated[str, Field(min_length=1, max_length=500)]
    items: Annotated[list[ItemEntrada], Field(min_length=1)]


class SalidaRepuestoResumen(BaseModel):
    """Repuesto resumido anidado en un ítem de orden."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str


class SalidaItemOrden(BaseModel):
    """Ítem de la orden con el precio copiado, su subtotal y el repuesto anidado."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    repuesto_id: int
    repuesto: SalidaRepuestoResumen
    cantidad: int
    precio_unitario: Decimal
    subtotal: Decimal


class SalidaEstadoOrden(BaseModel):
    """Estado del catálogo de órdenes."""

    model_config = ConfigDict(from_attributes=True)

    codigo: str
    descripcion: str
    posicion: int
    es_final: bool


class SalidaHistorialEstado(BaseModel):
    """Línea del historial de cambios de estado de una orden."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    desde_estado: str | None
    hasta_estado: str
    usuario_id: int | None
    cuando: datetime


class SalidaVehiculoResumen(BaseModel):
    """Vehículo resumido para el listado de órdenes."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    patente: str


class SalidaOrdenResumen(BaseModel):
    """Orden resumida para el listado paginado (`GET /ordenes`, `GET /mis-ordenes`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    vehiculo_id: int
    patente: str
    falla: str
    estado: str
    creada_en: datetime
    total: Decimal


class SalidaClienteBreve(BaseModel):
    """Cliente breve anidado en el detalle de la orden."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    documento: str
    telefono: str


class SalidaOrdenDetalle(BaseModel):
    """Detalle completo de una orden (`GET /ordenes/{id}` y respuesta de `POST /ordenes`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    estado: str
    falla: str
    creada_en: datetime
    total: Decimal
    vehiculo: SalidaVehiculoResumen
    cliente: SalidaClienteBreve
    items: list[SalidaItemOrden]
    historial: list[SalidaHistorialEstado]


class ConsultaOrdenes(ParametrosPagina):
    """Parámetros de query de `GET /ordenes`: paginación + filtro de estado."""

    estado: EstadoOrdenCodigo | None = Field(
        default=None,
        description="Filtra por código de estado del catálogo.",
    )
