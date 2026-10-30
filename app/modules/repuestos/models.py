"""Modelos de tabla del módulo repuestos (SQLModel) — capa Model.

Define las tablas del dominio de repuestos y stock:
- `repuesto`: catálogo de piezas con precio NUMERIC(10,2) CHECK > 0, stock CHECK >= 0,
  borrado lógico y un índice único parcial `(codigo) WHERE borrado_en IS NULL` (RN-01).
- `movimiento_stock`: registro de auditoría de cada cambio de stock (alta inicial, reposición,
  salida por orden de trabajo) con cantidad CHECK > 0 (RN-14, RN-15).
- `historial_precio_repuesto`: registro inmutable de variaciones de precio en transacciones
  atómicas con CHECK `precio_nuevo > precio_anterior` (RN-20, RN-15).
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import CheckConstraint, Column, DateTime, Index, Numeric, text
from sqlmodel import Field, Relationship, SQLModel

from app.modules.usuarios.models import Usuario  # noqa: F401


class Repuesto(SQLModel, table=True):
    """Catálogo de repuestos con precio decimal, stock y borrado lógico."""

    __tablename__ = "repuesto"
    __table_args__ = (
        CheckConstraint("precio > 0", name="ck_repuesto_precio_positivo"),
        CheckConstraint("stock >= 0", name="ck_repuesto_stock_no_negativo"),
        Index(
            "ix_repuesto_codigo_activo",
            "codigo",
            unique=True,
            postgresql_where=text("borrado_en IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    codigo: str = Field(
        max_length=50,
        index=True,
        description="Código identificador de la pieza (único entre vigentes, RN-01).",
    )
    descripcion: str = Field(
        max_length=200,
        description="Descripción detallada de la pieza o repuesto.",
    )
    precio: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Precio unitario vigente (Decimal NUMERIC(10,2) > 0).",
    )
    stock: int = Field(
        default=0,
        description="Cantidad actual en depósito. Solo editable vía movimientos (RN-14).",
    )
    borrado_en: Optional[datetime] = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        description="Fecha y hora de baja lógica; NULL = repuesto activo.",
    )

    # Relaciones
    movimientos: List["MovimientoStock"] = Relationship(back_populates="repuesto")
    historial_precios: List["HistorialPrecioRepuesto"] = Relationship(back_populates="repuesto")


class MovimientoStock(SQLModel, table=True):
    """Movimiento de auditoría de inventario: entrada o salida de piezas."""

    __tablename__ = "movimiento_stock"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_movimiento_stock_cantidad_positiva"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    repuesto_id: int = Field(
        foreign_key="repuesto.id",
        index=True,
        description="Repuesto cuyo stock se altera.",
    )
    orden_id: Optional[int] = Field(
        default=None,
        index=True,
        description="Orden de trabajo vinculada si es salida (nulo en compras).",
    )
    usuario_id: Optional[int] = Field(
        default=None,
        foreign_key="usuario.id",
        index=True,
        description="Usuario que realizó la operación.",
    )
    cantidad: int = Field(
        description="Cantidad de unidades afectadas (siempre > 0).",
    )
    motivo: str = Field(
        max_length=120,
        description="Razón del movimiento (Stock inicial, Reposición, Consumo orden, etc.).",
    )
    cuando: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        description="Fecha y hora de registro del movimiento.",
    )

    # Relación
    repuesto: Optional[Repuesto] = Relationship(back_populates="movimientos")


class HistorialPrecioRepuesto(SQLModel, table=True):
    """Registro inmutable de cambio de precio de un repuesto (RN-20)."""

    __tablename__ = "historial_precio_repuesto"
    __table_args__ = (
        CheckConstraint("precio_anterior > 0", name="ck_historial_precio_anterior_positivo"),
        CheckConstraint("precio_nuevo > 0", name="ck_historial_precio_nuevo_positivo"),
        CheckConstraint("precio_nuevo > precio_anterior", name="ck_historial_precio_aumento"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    repuesto_id: int = Field(
        foreign_key="repuesto.id",
        index=True,
        description="Repuesto cuyo precio varió.",
    )
    usuario_id: Optional[int] = Field(
        default=None,
        foreign_key="usuario.id",
        index=True,
        description="Usuario administrador que efectuó el ajuste.",
    )
    precio_anterior: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Precio previo a la modificación.",
    )
    precio_nuevo: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Nuevo precio establecido.",
    )
    cuando: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        description="Momento exacto en que impactó la actualización.",
    )

    # Relación
    repuesto: Optional[Repuesto] = Relationship(back_populates="historial_precios")
