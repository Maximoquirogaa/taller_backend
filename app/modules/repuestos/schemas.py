"""Esquemas Pydantic del módulo repuestos (capa Schema).

Contratos estrictos (`extra="forbid"`):
- `EntradaCrearRepuesto`: alta con código, descripción, precio y stock_inicial.
- `EntradaActualizarRepuesto`: modificación parcial de descripción y/o precio (stock no admitido).
- `EntradaReponerStock`: reposición con cantidad positiva.
- `SalidaRepuesto`: lectura de repuesto con precio decimal y stock.
- `SalidaMovimientoStock`: registro de auditoría de movimientos.
- `SalidaHistorialPrecio`: registro de variaciones de precio.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EntradaCrearRepuesto(BaseModel):
    """Contrato de entrada para dar de alta una nueva pieza en el catálogo."""

    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=50)
    descripcion: str = Field(min_length=1, max_length=200)
    precio: Decimal = Field(gt=0, description="Precio unitario (debe ser mayor a 0).")
    stock_inicial: int = Field(default=0, ge=0, description="Stock inicial del repuesto (>= 0).")


class EntradaActualizarRepuesto(BaseModel):
    """Contrato de entrada para actualizar descripción o precio (PATCH exclude_unset).

    No incluye campo stock: el stock solo se modifica mediante movimientos (RN-14).
    """

    model_config = ConfigDict(extra="forbid")

    descripcion: str | None = Field(default=None, min_length=1, max_length=200)
    precio: Decimal | None = Field(default=None, gt=0, description="Nuevo precio unitario (> 0).")


class EntradaReponerStock(BaseModel):
    """Contrato de entrada para sumar unidades al stock disponible."""

    model_config = ConfigDict(extra="forbid")

    cantidad: int = Field(gt=0, description="Cantidad a reponer (debe ser mayor a 0).")
    motivo: str = Field(default="Reposición", min_length=1, max_length=120)


class SalidaRepuesto(BaseModel):
    """Contrato de salida para datos de un repuesto."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    descripcion: str
    precio: Decimal
    stock: int


class SalidaMovimientoStock(BaseModel):
    """Contrato de salida para un movimiento de inventario."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    repuesto_id: int
    orden_id: int | None = None
    usuario_id: int | None = None
    cantidad: int
    motivo: str
    cuando: datetime


class SalidaHistorialPrecio(BaseModel):
    """Contrato de salida para una variación histórica de precio."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    repuesto_id: int
    usuario_id: int | None = None
    precio_anterior: Decimal
    precio_nuevo: Decimal
    cuando: datetime
