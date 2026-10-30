"""Esquemas Pydantic del módulo clientes (capa Schema).

Contratos estrictos (`extra="forbid"`):
- `EntradaCrearCliente`
- `SalidaCliente`
- `EntradaCrearVehiculo`
- `SalidaVehiculo`
- `SalidaClienteDetalle`
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EntradaCrearCliente(BaseModel):
    """Contrato de entrada para crear un cliente de mostrador (sin usuario)."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=120)
    documento: str = Field(min_length=1, max_length=30)
    telefono: str = Field(min_length=1, max_length=40)


class SalidaCliente(BaseModel):
    """Contrato de salida para datos de cliente."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int | None = None
    nombre: str
    documento: str
    telefono: str


class EntradaCrearVehiculo(BaseModel):
    """Contrato de entrada para registrar un vehículo asociado a un cliente."""

    model_config = ConfigDict(extra="forbid")

    patente: str = Field(min_length=1, max_length=20)
    marca: str = Field(min_length=1, max_length=60)
    modelo: str = Field(min_length=1, max_length=60)
    anio: int = Field(ge=1950, le=2100)


class SalidaVehiculo(BaseModel):
    """Contrato de salida para datos de vehículo."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    cliente_id: int
    patente: str
    marca: str
    modelo: str
    anio: int


class SalidaClienteDetalle(BaseModel):
    """Contrato de salida para la ficha de cliente con sus vehículos precargados."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int | None = None
    nombre: str
    documento: str
    telefono: str
    vehiculos: list[SalidaVehiculo] = []
