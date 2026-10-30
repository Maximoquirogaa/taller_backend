"""Tests unitarios de los modelos del módulo repuestos (Task 1.1, C-05).

Verifica el contrato de los modelos SQLModel:
- `Repuesto`: campos, tipos, CHECK precio > 0, CHECK stock >= 0 e índice único parcial de código activo.
- `MovimientoStock`: campos, CHECK cantidad > 0, claves foráneas.
- `HistorialPrecioRepuesto`: campos, CHECK precio > 0, CHECK precio_nuevo > precio_anterior.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import CheckConstraint, Index
from sqlmodel import SQLModel

from app.modules.repuestos.models import (
    HistorialPrecioRepuesto,
    MovimientoStock,
    Repuesto,
)


def test_repuesto_modelo_definicion_campos() -> None:
    """Verifica que el modelo Repuesto declara los campos y tipos esperados."""
    assert issubclass(Repuesto, SQLModel)
    assert Repuesto.__tablename__ == "repuesto"

    campos = Repuesto.model_fields
    assert "id" in campos
    assert "codigo" in campos
    assert "descripcion" in campos
    assert "precio" in campos
    assert "stock" in campos
    assert "borrado_en" in campos


def test_repuesto_modelo_restricciones_e_indices() -> None:
    """Verifica CHECKs y el índice único parcial en código activo."""
    table_args = getattr(Repuesto, "__table_args__", ())

    checks = [arg for arg in table_args if isinstance(arg, CheckConstraint)]
    assert any("precio > 0" in str(ck.sqltext) for ck in checks)
    assert any("stock >= 0" in str(ck.sqltext) for ck in checks)

    indices = [arg for arg in table_args if isinstance(arg, Index)]
    indice_codigo = next((idx for idx in indices if idx.name == "ix_repuesto_codigo_activo"), None)
    assert indice_codigo is not None
    assert indice_codigo.unique is True
    assert "borrado_en IS NULL" in str(indice_codigo.dialect_options.get("postgresql", {}).get("where", ""))


def test_movimiento_stock_modelo() -> None:
    """Verifica definición y restricciones de MovimientoStock."""
    assert issubclass(MovimientoStock, SQLModel)
    assert MovimientoStock.__tablename__ == "movimiento_stock"

    campos = MovimientoStock.model_fields
    assert "id" in campos
    assert "repuesto_id" in campos
    assert "orden_id" in campos
    assert "usuario_id" in campos
    assert "cantidad" in campos
    assert "motivo" in campos
    assert "cuando" in campos

    table_args = getattr(MovimientoStock, "__table_args__", ())
    checks = [arg for arg in table_args if isinstance(arg, CheckConstraint)]
    assert any("cantidad > 0" in str(ck.sqltext) for ck in checks)


def test_historial_precio_repuesto_modelo() -> None:
    """Verifica definición y restricciones de HistorialPrecioRepuesto."""
    assert issubclass(HistorialPrecioRepuesto, SQLModel)
    assert HistorialPrecioRepuesto.__tablename__ == "historial_precio_repuesto"

    campos = HistorialPrecioRepuesto.model_fields
    assert "id" in campos
    assert "repuesto_id" in campos
    assert "usuario_id" in campos
    assert "precio_anterior" in campos
    assert "precio_nuevo" in campos
    assert "cuando" in campos

    table_args = getattr(HistorialPrecioRepuesto, "__table_args__", ())
    checks = [arg for arg in table_args if isinstance(arg, CheckConstraint)]
    assert any("precio_anterior > 0" in str(ck.sqltext) for ck in checks)
    assert any("precio_nuevo > 0" in str(ck.sqltext) for ck in checks)
    assert any("precio_nuevo > precio_anterior" in str(ck.sqltext) for ck in checks)


def test_instanciacion_modelos_repuestos() -> None:
    """Verifica la creación de instancias con tipos válidos."""
    r = Repuesto(
        codigo="FIL-001",
        descripcion="Filtro de aceite",
        precio=Decimal("8500.00"),
        stock=10,
    )
    assert r.id is None
    assert r.codigo == "FIL-001"
    assert r.descripcion == "Filtro de aceite"
    assert r.precio == Decimal("8500.00")
    assert r.stock == 10
    assert r.borrado_en is None

    m = MovimientoStock(
        repuesto_id=1,
        cantidad=5,
        motivo="Stock inicial",
    )
    assert m.id is None
    assert m.repuesto_id == 1
    assert m.cantidad == 5
    assert m.motivo == "Stock inicial"
    assert m.orden_id is None
    assert m.cuando is not None

    h = HistorialPrecioRepuesto(
        repuesto_id=1,
        usuario_id=2,
        precio_anterior=Decimal("8000.00"),
        precio_nuevo=Decimal("8500.00"),
    )
    assert h.id is None
    assert h.repuesto_id == 1
    assert h.usuario_id == 2
    assert h.precio_anterior == Decimal("8000.00")
    assert h.precio_nuevo == Decimal("8500.00")
    assert h.cuando is not None
