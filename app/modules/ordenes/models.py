"""Modelos de tabla del módulo ordenes (SQLModel) — capa Model.

Cuatro tablas (design.md D2, KB 04):

- `estado_orden`: catálogo de estados con PK textual `codigo`, `posicion`
  UNIQUE y `es_final`. La crea la migración **vacía** (DD-01); C-10 la puebla.
- `orden_trabajo`: orden con vehículo, mecánico opcional, estado (FK al
  catálogo), falla, fecha de creación y total NUMERIC(12,2) CHECK >= 0.
- `item_orden`: composición de la orden con `UNIQUE(orden_id, repuesto_id)`
  (RN-10) y precio unitario copiado del repuesto. CHECK de cantidad y precio.
- `historial_estado_orden`: bitácora de sólo agregado (RN-15, protegida por el
  disparador de C-09). `desde_estado` es nulo en la fila inicial; `usuario_id`
  es nullable para permitir eventos de `SISTEMA` del seed (C-10).
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import CheckConstraint, Column, DateTime, Numeric, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.modules.clientes.models import Cliente, Vehiculo  # noqa: F401
from app.modules.repuestos.models import Repuesto  # noqa: F401
from app.modules.usuarios.models import Usuario  # noqa: F401


class EstadoOrden(SQLModel, table=True):
    """Estado del catálogo: PK textual, posición única y marca de estado final."""

    __tablename__ = "estado_orden"
    __table_args__ = (
        CheckConstraint("posicion > 0", name="ck_estado_orden_posicion_positiva"),
    )

    codigo: str = Field(
        max_length=30,
        primary_key=True,
        description="Código del estado (PK textual, RN-19).",
    )
    descripcion: str = Field(max_length=120)
    posicion: int = Field(
        unique=True,
        description="Orden de presentación en el catálogo (único y > 0).",
    )
    es_final: bool = Field(
        default=False,
        description="True si el estado cierra la orden (RN-16).",
    )


class OrdenTrabajo(SQLModel, table=True):
    """Orden de trabajo: nace PENDIENTE y su total lo calcula el servidor (RN-10)."""

    __tablename__ = "orden_trabajo"
    __table_args__ = (
        CheckConstraint("total >= 0", name="ck_orden_trabajo_total_no_negativo"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    vehiculo_id: int = Field(
        foreign_key="vehiculo.id",
        index=True,
        description="Vehículo que ingresa al taller.",
    )
    mecanico_id: Optional[int] = Field(
        default=None,
        foreign_key="usuario.id",
        index=True,
        description="Mecánico asignado (nulo hasta iniciar la reparación, RN-11).",
    )
    estado: str = Field(
        max_length=30,
        foreign_key="estado_orden.codigo",
        index=True,
        description="Código del estado vigente (FK al catálogo, RN-19).",
    )
    falla: str = Field(
        max_length=500,
        description="Falla reportada por el cliente (máx. 500 caracteres).",
    )
    creada_en: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        description="Instante de apertura de la orden (UTC).",
    )
    total: Decimal = Field(
        sa_column=Column(Numeric(12, 2), nullable=False),
        description="Total calculado por el servidor: suma de precio × cantidad (RN-10).",
    )

    # Relaciones (nombres distintos de las columnas FK para no colisionar)
    vehiculo: Optional[Vehiculo] = Relationship()
    estado_catalogo: Optional[EstadoOrden] = Relationship()
    items: List["ItemOrden"] = Relationship(
        back_populates="orden",
        sa_relationship_kwargs={"order_by": "ItemOrden.id"},
    )
    historial: List["HistorialEstadoOrden"] = Relationship(
        back_populates="orden",
        sa_relationship_kwargs={"order_by": "HistorialEstadoOrden.cuando"},
    )


class ItemOrden(SQLModel, table=True):
    """Ítem de composición: un repuesto por orden, con precio copiado (RN-10)."""

    __tablename__ = "item_orden"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_item_orden_cantidad_positiva"),
        CheckConstraint("precio_unitario > 0", name="ck_item_orden_precio_positivo"),
        UniqueConstraint("orden_id", "repuesto_id", name="uq_item_orden_orden_repuesto"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    orden_id: int = Field(
        foreign_key="orden_trabajo.id",
        index=True,
        description="Orden de trabajo a la que pertenece el ítem.",
    )
    repuesto_id: int = Field(
        foreign_key="repuesto.id",
        index=True,
        description="Repuesto usado en la orden (único por orden, RN-10).",
    )
    cantidad: int = Field(description="Unidades usadas (> 0).")
    precio_unitario: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Precio copiado del repuesto al abrir la orden (RN-10/RN-20).",
    )

    orden: Optional[OrdenTrabajo] = Relationship(back_populates="items")
    repuesto: Optional[Repuesto] = Relationship()


class HistorialEstadoOrden(SQLModel, table=True):
    """Línea de historial de estados: sólo agregado (RN-15)."""

    __tablename__ = "historial_estado_orden"

    id: Optional[int] = Field(default=None, primary_key=True)
    orden_id: int = Field(
        foreign_key="orden_trabajo.id",
        index=True,
        description="Orden cuyo estado cambió.",
    )
    desde_estado: Optional[str] = Field(
        default=None,
        max_length=30,
        foreign_key="estado_orden.codigo",
        description="Estado anterior; nulo en la línea inicial (nulo → PENDIENTE).",
    )
    hasta_estado: str = Field(
        max_length=30,
        foreign_key="estado_orden.codigo",
        description="Estado nuevo (obligatorio).",
    )
    usuario_id: Optional[int] = Field(
        default=None,
        foreign_key="usuario.id",
        index=True,
        description="Actor del cambio; nullable para eventos de SISTEMA (seed C-10).",
    )
    cuando: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        description="Instante del cambio de estado (UTC).",
    )

    orden: Optional[OrdenTrabajo] = Relationship(back_populates="historial")
    desde_estado_catalogo: Optional[EstadoOrden] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[HistorialEstadoOrden.desde_estado]"}
    )
    hasta_estado_catalogo: Optional[EstadoOrden] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[HistorialEstadoOrden.hasta_estado]"}
    )
    usuario: Optional[Usuario] = Relationship()
