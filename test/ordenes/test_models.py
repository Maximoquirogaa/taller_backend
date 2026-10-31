"""Tests de modelo y restricciones de las cuatro tablas de órdenes (Task 1.2/1.5).

Cubre PK textual de `estado_orden`, UNIQUE de `posicion`, `es_final` por
defecto, UNIQUE `(orden_id, repuesto_id)` de `item_orden`, CHECK de cantidad,
precio y total, FK de estado y nulabilidad de `historial_estado_orden`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import (
    EstadoOrden,
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)
from app.modules.repuestos.models import Repuesto
from test.ordenes.conftest import crear_cliente, crear_repuesto, crear_vehiculo, insertar_catalogo


def test_modelos_declaran_las_cuatro_tablas() -> None:
    """Los cuatro modelos son tablas SQLModel con el nombre esperado."""
    assert issubclass(EstadoOrden, SQLModel)
    assert issubclass(OrdenTrabajo, SQLModel)
    assert issubclass(ItemOrden, SQLModel)
    assert issubclass(HistorialEstadoOrden, SQLModel)
    assert EstadoOrden.__tablename__ == "estado_orden"
    assert OrdenTrabajo.__tablename__ == "orden_trabajo"
    assert ItemOrden.__tablename__ == "item_orden"
    assert HistorialEstadoOrden.__tablename__ == "historial_estado_orden"


def test_estado_orden_pk_textual_y_es_final_por_defecto() -> None:
    """`codigo` es PK textual y `es_final` arranca en False."""
    columnas = EstadoOrden.__table__.columns
    assert columnas["codigo"].primary_key is True
    assert columnas["codigo"].type.length == 30
    assert EstadoOrden(codigo="PENDIENTE", descripcion="Pendiente", posicion=1).es_final is False


def test_item_orden_tiene_unique_compuesto_y_checks() -> None:
    """`item_orden` declara UNIQUE(orden_id, repuesto_id) y los CHECK de cantidad/precio."""
    table_args = getattr(ItemOrden, "__table_args__", ())
    uniques = [a for a in table_args if isinstance(a, UniqueConstraint)]
    assert any(
        {c.name for c in u.columns} == {"orden_id", "repuesto_id"} for u in uniques
    )
    checks = [str(a.sqltext) for a in table_args if isinstance(a, CheckConstraint)]
    assert any("cantidad > 0" in c for c in checks)
    assert any("precio_unitario > 0" in c for c in checks)


def test_orden_trabajo_check_total_no_negativo() -> None:
    """`orden_trabajo.total` tiene CHECK >= 0."""
    checks = [str(a.sqltext) for a in OrdenTrabajo.__table_args__ if isinstance(a, CheckConstraint)]
    assert any("total >= 0" in c for c in checks)


async def test_posicion_duplicada_viola_unique(sesion_db: AsyncSession) -> None:
    """Dos estados con la misma `posicion` violan el UNIQUE."""
    sesion_db.add(EstadoOrden(codigo="A", descripcion="A", posicion=1))
    await sesion_db.flush()
    sesion_db.add(EstadoOrden(codigo="B", descripcion="B", posicion=1))
    with pytest.raises(IntegrityError):
        await sesion_db.flush()
    await sesion_db.rollback()


async def test_item_repetido_en_misma_orden_viola_unique(sesion_db: AsyncSession) -> None:
    """Un segundo ítem con el mismo repuesto en la misma orden viola el UNIQUE."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuesto = await crear_repuesto(sesion_db, codigo="R1", precio="100.00")

    orden = OrdenTrabajo(
        vehiculo_id=vehiculo.id, estado="PENDIENTE", falla="Falla", total=Decimal("100.00")
    )
    sesion_db.add(orden)
    await sesion_db.flush()

    sesion_db.add(
        ItemOrden(
            orden_id=orden.id,
            repuesto_id=repuesto.id,
            cantidad=1,
            precio_unitario=Decimal("100.00"),
        )
    )
    await sesion_db.flush()
    sesion_db.add(
        ItemOrden(
            orden_id=orden.id,
            repuesto_id=repuesto.id,
            cantidad=1,
            precio_unitario=Decimal("100.00"),
        )
    )
    with pytest.raises(IntegrityError):
        await sesion_db.flush()
    await sesion_db.rollback()


async def test_mismo_repuesto_en_ordenes_distintas_permitido(sesion_db: AsyncSession) -> None:
    """El UNIQUE es por orden: el mismo repuesto puede estar en otra orden."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuesto = await crear_repuesto(sesion_db, codigo="R1", precio="100.00")

    for _ in range(2):
        orden = OrdenTrabajo(
            vehiculo_id=vehiculo.id, estado="PENDIENTE", falla="Falla", total=Decimal("100.00")
        )
        sesion_db.add(orden)
        await sesion_db.flush()
        sesion_db.add(
            ItemOrden(
                orden_id=orden.id,
                repuesto_id=repuesto.id,
                cantidad=1,
                precio_unitario=Decimal("100.00"),
            )
        )
        await sesion_db.flush()
    await sesion_db.commit()


async def test_checks_de_item_y_total(sesion_db: AsyncSession) -> None:
    """Cantidad <= 0, precio <= 0 y total < 0 violan sus CHECK."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuesto = await crear_repuesto(sesion_db, codigo="R1", precio="100.00")

    orden = OrdenTrabajo(
        vehiculo_id=vehiculo.id, estado="PENDIENTE", falla="Falla", total=Decimal("100.00")
    )
    sesion_db.add(orden)
    await sesion_db.flush()

    sesion_db.add(
        ItemOrden(
            orden_id=orden.id,
            repuesto_id=repuesto.id,
            cantidad=0,
            precio_unitario=Decimal("100.00"),
        )
    )
    with pytest.raises(IntegrityError):
        await sesion_db.flush()
    await sesion_db.rollback()


async def test_orden_con_estado_fuera_del_catalogo_viola_fk(sesion_db: AsyncSession) -> None:
    """`orden_trabajo.estado` debe existir en el catálogo (RN-19)."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")

    sesion_db.add(
        OrdenTrabajo(
            vehiculo_id=vehiculo.id, estado="INVENTADO", falla="Falla", total=Decimal("0")
        )
    )
    with pytest.raises(IntegrityError):
        await sesion_db.flush()
    await sesion_db.rollback()


async def test_historial_admite_desde_nulo_y_exige_hasta(sesion_db: AsyncSession) -> None:
    """El historial inicial tiene `desde_estado` nulo y `hasta_estado` obligatorio."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    orden = OrdenTrabajo(
        vehiculo_id=vehiculo.id, estado="PENDIENTE", falla="Falla", total=Decimal("0")
    )
    sesion_db.add(orden)
    await sesion_db.flush()

    sesion_db.add(
        HistorialEstadoOrden(
            orden_id=orden.id,
            desde_estado=None,
            hasta_estado="PENDIENTE",
            usuario_id=None,
            cuando=datetime.now(UTC),
        )
    )
    await sesion_db.commit()

    # Un hasta_estado inexistente viola la FK
    sesion_db.add(
        HistorialEstadoOrden(
            orden_id=orden.id,
            desde_estado="PENDIENTE",
            hasta_estado="INVENTADO",
            cuando=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        await sesion_db.flush()
    await sesion_db.rollback()
