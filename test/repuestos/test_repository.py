"""Tests de repositorios y UoW del módulo repuestos (Task 2.2, C-05).

Verifica:
- `RepositorioRepuestos`: alta, soft delete, índice único parcial sobre código activo (RN-01),
  búsqueda con parámetros ligados (RN-18).
- `RepositorioMovimientosStock`: inserción y consulta ordenada cronológicamente (RN-14).
- `RepositorioHistorialPrecios`: inserción y consulta ordenada (RN-20).
- `UoWRepuestos`: transacción atómica multi-tabla.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.repuestos.models import (
    HistorialPrecioRepuesto,
    MovimientoStock,
    Repuesto,
)
from app.modules.repuestos.repository import (
    RepositorioHistorialPrecios,
    RepositorioMovimientosStock,
    RepositorioRepuestos,
)
from app.modules.repuestos.unit_of_work import UoWRepuestos


async def test_repositorio_repuestos_alta_y_busqueda(sesion: AsyncSession) -> None:
    """Verifica alta y recuperación por código activo."""
    repo = RepositorioRepuestos(sesion)
    repuesto = Repuesto(
        codigo="ACE-001",
        descripcion="Aceite sintético 5W30",
        precio=Decimal("12000.00"),
        stock=20,
    )
    await repo.add(repuesto)
    await sesion.commit()

    encontrado = await repo.get_por_codigo_activo("ACE-001")
    assert encontrado is not None
    assert encontrado.descripcion == "Aceite sintético 5W30"
    assert encontrado.precio == Decimal("12000.00")

    # Búsqueda insensible a mayúsculas/minúsculas o espacios
    encontrado_lower = await repo.get_por_codigo_activo(" ace-001 ")
    assert encontrado_lower is not None
    assert encontrado_lower.id == encontrado.id


async def test_repositorio_repuestos_rechaza_codigo_duplicado_activo(sesion: AsyncSession) -> None:
    """Verifica restricción del índice único parcial en código activo (RN-01)."""
    repo = RepositorioRepuestos(sesion)
    await repo.add(
        Repuesto(codigo="DUP-001", descripcion="Pieza 1", precio=Decimal("1000.00"), stock=1)
    )
    await sesion.flush()

    with pytest.raises(IntegrityError):
        await repo.add(
            Repuesto(codigo="DUP-001", descripcion="Pieza 2", precio=Decimal("2000.00"), stock=2)
        )
        await sesion.flush()
    await sesion.rollback()


async def test_repositorio_repuestos_soft_delete_y_re_registro(sesion: AsyncSession) -> None:
    """Verifica que una pieza dada de baja libera su código para un nuevo alta (RN-01, RN-16)."""
    repo = RepositorioRepuestos(sesion)
    r1 = await repo.add(
        Repuesto(codigo="REC-001", descripcion="Pieza antigua", precio=Decimal("5000.00"), stock=0)
    )
    await sesion.commit()

    # Baja lógica
    await repo.soft_delete(r1)
    await sesion.commit()

    # Código ya no aparece en activos
    activo = await repo.get_por_codigo_activo("REC-001")
    assert activo is None

    # Re-registro con el mismo código es admitido
    r2 = await repo.add(
        Repuesto(codigo="REC-001", descripcion="Pieza nueva versión", precio=Decimal("7500.00"), stock=5)
    )
    await sesion.commit()
    assert r2.id != r1.id
    assert r2.borrado_en is None


async def test_repositorio_repuestos_buscar_catalogo_y_seguridad_sql(sesion: AsyncSession) -> None:
    """Verifica búsqueda por texto con parámetros ligados e inmunidad a inyecciones SQL (RN-18)."""
    repo = RepositorioRepuestos(sesion)
    await repo.add(Repuesto(codigo="FIL-001", descripcion="Filtro de aire", precio=Decimal("4000.00"), stock=10))
    await repo.add(Repuesto(codigo="FIL-002", descripcion="Filtro de combustible", precio=Decimal("6000.00"), stock=5))
    await repo.add(Repuesto(codigo="BUJ-001", descripcion="Bujía de encendido", precio=Decimal("2500.00"), stock=8))
    await sesion.commit()

    # Búsqueda coincidente
    items, total = await repo.buscar_catalogo(q="filtro")
    assert total == 2
    assert len(items) == 2

    # Búsqueda por código
    items_cod, total_cod = await repo.buscar_catalogo(q="BUJ")
    assert total_cod == 1
    assert items_cod[0].codigo == "BUJ-001"

    # Intento de SQL Injection no rompe la consulta ni devuelve datos extra (RN-18)
    items_inj, total_inj = await repo.buscar_catalogo(q="' OR '1'='1")
    assert total_inj == 0
    assert len(items_inj) == 0


async def test_repositorio_movimientos_y_precios(sesion: AsyncSession) -> None:
    """Verifica registro y consulta de movimientos de stock e historial de precios."""
    repo_r = RepositorioRepuestos(sesion)
    repo_m = RepositorioMovimientosStock(sesion)
    repo_h = RepositorioHistorialPrecios(sesion)

    r = await repo_r.add(
        Repuesto(codigo="PAS-001", descripcion="Pastillas de freno", precio=Decimal("15000.00"), stock=4)
    )
    await sesion.flush()

    m1 = await repo_m.add(MovimientoStock(repuesto_id=r.id, cantidad=4, motivo="Stock inicial"))
    m2 = await repo_m.add(MovimientoStock(repuesto_id=r.id, cantidad=6, motivo="Reposición"))
    await sesion.flush()

    h1 = await repo_h.add(
        HistorialPrecioRepuesto(
            repuesto_id=r.id,
            precio_anterior=Decimal("12000.00"),
            precio_nuevo=Decimal("15000.00"),
        )
    )
    await sesion.commit()

    movs = await repo_m.get_por_repuesto(r.id)
    assert len(movs) == 2
    assert movs[0].motivo == "Stock inicial"
    assert movs[1].motivo == "Reposición"

    precios = await repo_h.get_por_repuesto(r.id)
    assert len(precios) == 1
    assert precios[0].precio_anterior == Decimal("12000.00")
    assert precios[0].precio_nuevo == Decimal("15000.00")


async def test_uow_repuestos_transaccion_atomica(sesion: AsyncSession) -> None:
    """Verifica que el UoW confirma o revierte de manera indivisible."""
    try:
        async with UoWRepuestos(sesion) as uow:
            r = await uow.repuestos.add(
                Repuesto(codigo="FAIL-01", descripcion="Prueba rollback", precio=Decimal("100.00"), stock=1)
            )
            await uow.movimientos.add(MovimientoStock(repuesto_id=r.id, cantidad=1, motivo="Test"))
            raise RuntimeError("Fallo provocado")
    except RuntimeError:
        pass

    repo = RepositorioRepuestos(sesion)
    assert await repo.get_por_codigo_activo("FAIL-01") is None
