"""Modelos de tabla del módulo clientes (SQLModel) — capa Model.

Define las tablas `cliente` y `vehiculo`:
- `cliente`: fichas de clientes con o sin usuario web asociado (`usuario_id UNIQUE` nulo, 1:1 opcional). Documento único.
- `vehiculo`: vehículos asociados al cliente con borrado lógico (`borrado_en` timestamptz).
  Restricción CHECK de año (1950..2100) e índice único parcial `(patente) WHERE borrado_en IS NULL` (RN-01).
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import CheckConstraint, DateTime, Index, text
from sqlmodel import Field, Relationship, SQLModel

from app.modules.usuarios.models import Usuario  # noqa: F401


class Cliente(SQLModel, table=True):
    """Ficha de cliente: puede estar vinculada o no a un usuario web."""

    __tablename__ = "cliente"

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: Optional[int] = Field(
        default=None,
        foreign_key="usuario.id",
        unique=True,
        index=True,
        description="Usuario web asociado (1:1 opcional, nulo para clientes de mostrador).",
    )
    nombre: str = Field(max_length=120)
    documento: str = Field(
        max_length=30,
        unique=True,
        index=True,
        description="Documento del cliente (DNI, CUIT, etc.), único en el sistema.",
    )
    telefono: str = Field(max_length=40)

    # Relación con vehículos
    vehiculos: List["Vehiculo"] = Relationship(back_populates="cliente")


class Vehiculo(SQLModel, table=True):
    """Vehículo del cliente con borrado lógico e índice único parcial de patente activa."""

    __tablename__ = "vehiculo"
    __table_args__ = (
        CheckConstraint("anio >= 1950 AND anio <= 2100", name="ck_vehiculo_anio_valido"),
        Index(
            "ix_vehiculo_patente_activa",
            "patente",
            unique=True,
            postgresql_where=text("borrado_en IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    cliente_id: int = Field(
        foreign_key="cliente.id",
        index=True,
        description="Cliente dueño del vehículo.",
    )
    patente: str = Field(
        max_length=20,
        index=True,
        description="Dominio/patente del vehículo.",
    )
    marca: str = Field(max_length=60)
    modelo: str = Field(max_length=60)
    anio: int = Field(description="Año de fabricación (1950..2100).")
    borrado_en: Optional[datetime] = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        description="Fecha y hora de baja lógica; NULL = vehículo activo.",
    )

    # Relación con cliente
    cliente: Optional[Cliente] = Relationship(back_populates="vehiculos")
