"""Tests unitarios de los modelos `Cliente` y `Vehiculo` (Task 1.1, C-04).

Valida el contrato de los modelos SQLModel:
- `Cliente`: id, usuario_id (1:1 opcional), nombre, documento (único), telefono, relaciones.
- `Vehiculo`: id, cliente_id (FK), patente, marca, modelo, anio (CHECK 1950..2100), borrado_en (timestamptz).
- Restricciones e índices: CHECK de anio e índice único parcial en patente activa.
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, Index
from sqlmodel import SQLModel

from app.modules.clientes.models import Cliente, Vehiculo


def test_cliente_modelo_definicion_campos() -> None:
    """Verifica que el modelo Cliente declara los campos y tipos esperados."""
    assert issubclass(Cliente, SQLModel)
    assert Cliente.__tablename__ == "cliente"

    campos = Cliente.model_fields
    assert "id" in campos
    assert "usuario_id" in campos
    assert "nombre" in campos
    assert "documento" in campos
    assert "telefono" in campos


def test_vehiculo_modelo_definicion_campos() -> None:
    """Verifica que el modelo Vehiculo declara los campos y restricciones."""
    assert issubclass(Vehiculo, SQLModel)
    assert Vehiculo.__tablename__ == "vehiculo"

    campos = Vehiculo.model_fields
    assert "id" in campos
    assert "cliente_id" in campos
    assert "patente" in campos
    assert "marca" in campos
    assert "modelo" in campos
    assert "anio" in campos
    assert "borrado_en" in campos


def test_vehiculo_modelo_restricciones_e_indices() -> None:
    """Verifica el CHECK de anio y el índice único parcial de patente activa."""
    table_args = getattr(Vehiculo, "__table_args__", ())

    checks = [arg for arg in table_args if isinstance(arg, CheckConstraint)]
    assert any("anio >= 1950" in str(ck.sqltext) and "anio <= 2100" in str(ck.sqltext) for ck in checks)

    indices = [arg for arg in table_args if isinstance(arg, Index)]
    indice_patente = next((idx for idx in indices if idx.name == "ix_vehiculo_patente_activa"), None)
    assert indice_patente is not None
    assert indice_patente.unique is True
    assert "borrado_en IS NULL" in str(indice_patente.dialect_options.get("postgresql", {}).get("where", ""))


def test_instanciacion_cliente_y_vehiculo() -> None:
    """Verifica instanciación de entidades con valores por defecto."""
    c = Cliente(nombre="Juan Pérez", documento="30111222", telefono="11-2233-4455")
    assert c.id is None
    assert c.usuario_id is None
    assert c.nombre == "Juan Pérez"
    assert c.documento == "30111222"

    v = Vehiculo(cliente_id=1, patente="AA123BB", marca="Toyota", modelo="Corolla", anio=2020)
    assert v.id is None
    assert v.cliente_id == 1
    assert v.patente == "AA123BB"
    assert v.borrado_en is None
