"""Tests de repositorios y UoW del módulo órdenes (Tasks 2.1/2.3/2.5/2.6).

Cubre el catálogo de sólo lectura, la persistencia con `flush` sin `commit`,
la precarga del detalle (sin lazy loading), el filtrado paginado, las órdenes
propias y la atomicidad de `UoWOrdenes`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import (
    EstadoOrden,
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)
from app.modules.ordenes.repository import (
    RepositorioEstadosOrden,
    RepositorioHistorialOrden,
    RepositorioItemsOrden,
    RepositorioOrdenes,
)
from app.modules.ordenes.unit_of_work import UoWOrdenes
from app.modules.repuestos.models import Repuesto
from test.ordenes.conftest import (
    CATALOGO_ESTADOS,
    crear_cliente,
    crear_repuesto,
    crear_vehiculo,
    insertar_catalogo,
)


async def _preparar_base(sesion: AsyncSession) -> tuple[Cliente, Vehiculo, Repuesto]:
    """Catálogo + cliente/vehículo + repuesto listos para crear órdenes."""
    await insertar_catalogo(sesion)
    cliente = await crear_cliente(sesion, nombre="Ana", documento="100")
    vehiculo = await crear_vehiculo(sesion, cliente_id=cliente.id, patente="AAA111")
    repuesto = await crear_repuesto(sesion, codigo="R1", precio="100.00")
    return cliente, vehiculo, repuesto


def test_repositorio_estados_es_solo_lectura() -> None:
    """El repositorio del catálogo no expone escritura (RN-19)."""
    for metodo in ("add", "update", "delete", "soft_delete"):
        assert not hasattr(RepositorioEstadosOrden, metodo)


async def test_repositorio_estados_listar_y_buscar(sesion: AsyncSession) -> None:
    """`listar()` ordena por posición y `get_por_codigo` devuelve la fila."""
    repo = RepositorioEstadosOrden(sesion)
    assert await repo.existe_catalogo() is False

    await insertar_catalogo(sesion)
    estados = await repo.listar()
    assert [e.codigo for e in estados] == [e[0] for e in CATALOGO_ESTADOS]
    assert [e.posicion for e in estados] == sorted(e.posicion for e in estados)

    pendiente = await repo.get_por_codigo("PENDIENTE")
    assert pendiente is not None and pendiente.es_final is False
    assert await repo.get_por_codigo("INVENTADO") is None
    assert await repo.existe_catalogo() is True


async def test_repositorio_ordenes_add_hace_flush_sin_commit(sesion: AsyncSession) -> None:
    """`add` persiste dentro de la transacción, pero no confirma."""
    _, vehiculo, _ = await _preparar_base(sesion)
    repo = RepositorioOrdenes(sesion)
    orden = await repo.add(
        OrdenTrabajo(
            vehiculo_id=vehiculo.id,
            estado="PENDIENTE",
            falla="Ruido",
            total=Decimal("0.00"),
        )
    )
    assert orden.id is not None

    await sesion.rollback()
    encontrada = (
        await sesion.execute(select(OrdenTrabajo).where(OrdenTrabajo.id == orden.id))
    ).scalars().first()
    assert encontrada is None


async def test_get_detalle_precarga_relaciones(sesion: AsyncSession) -> None:
    """El detalle precarga vehículo, cliente, estado, ítems con repuesto e historial."""
    cliente, vehiculo, repuesto = await _preparar_base(sesion)
    orden = OrdenTrabajo(
        vehiculo_id=vehiculo.id, estado="PENDIENTE", falla="Ruido", total=Decimal("200.00")
    )
    sesion.add(orden)
    await sesion.flush()
    sesion.add(
        ItemOrden(
            orden_id=orden.id,
            repuesto_id=repuesto.id,
            cantidad=2,
            precio_unitario=Decimal("100.00"),
        )
    )
    sesion.add(
        HistorialEstadoOrden(
            orden_id=orden.id,
            desde_estado=None,
            hasta_estado="PENDIENTE",
            cuando=datetime.now(UTC),
        )
    )
    await sesion.commit()

    detalle = await RepositorioOrdenes(sesion).get_detalle(orden.id)
    assert detalle is not None
    assert detalle.vehiculo.patente == "AAA111"
    assert detalle.vehiculo.cliente.nombre == cliente.nombre
    assert detalle.estado_catalogo.codigo == "PENDIENTE"
    assert len(detalle.items) == 1 and detalle.items[0].repuesto.codigo == "R1"
    assert len(detalle.historial) == 1
    assert detalle.historial[0].hasta_estado == "PENDIENTE"


async def test_buscar_paginado_filtra_y_ordena(sesion: AsyncSession) -> None:
    """`buscar_paginado` devuelve `(items, total)` filtrado y en orden descendente."""
    _, vehiculo, _ = await _preparar_base(sesion)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i, estado in enumerate(["PENDIENTE", "TERMINADA", "PENDIENTE"]):
        sesion.add(
            OrdenTrabajo(
                vehiculo_id=vehiculo.id,
                estado=estado,
                falla=f"Falla {i}",
                total=Decimal("0.00"),
                creada_en=base + timedelta(days=i),
            )
        )
    await sesion.commit()

    repo = RepositorioOrdenes(sesion)
    items, total = await repo.buscar_paginado(None, offset=0, limit=10)
    assert total == 3
    assert [o.falla for o in items] == ["Falla 2", "Falla 1", "Falla 0"]

    pendientes, total_p = await repo.buscar_paginado("PENDIENTE", offset=0, limit=10)
    assert total_p == 2
    assert all(o.estado == "PENDIENTE" for o in pendientes)

    _, total_vacio = await repo.buscar_paginado("CANCELADA", offset=0, limit=10)
    assert total_vacio == 0


async def test_buscar_por_usuario_solo_lo_propio(sesion: AsyncSession) -> None:
    """`buscar_por_usuario` sólo devuelve órdenes de vehículos de la ficha del usuario."""
    await insertar_catalogo(sesion)
    from app.modules.usuarios.models import Usuario

    usuario = Usuario(
        email="cliente@test", nombre="Cliente", password_hash="x", activo=True
    )
    sesion.add(usuario)
    await sesion.flush()
    propio = await crear_cliente(sesion, nombre="Propio", documento="1", usuario_id=usuario.id)
    ajeno = await crear_cliente(sesion, nombre="Ajeno", documento="2")
    v_propio = await crear_vehiculo(sesion, cliente_id=propio.id, patente="PPP111")
    v_ajeno = await crear_vehiculo(sesion, cliente_id=ajeno.id, patente="AAA111")
    for v in (v_propio, v_ajeno):
        sesion.add(
            OrdenTrabajo(
                vehiculo_id=v.id, estado="PENDIENTE", falla="F", total=Decimal("0.00")
            )
        )
    await sesion.commit()

    items, total = await RepositorioOrdenes(sesion).buscar_por_usuario(
        usuario.id, offset=0, limit=10
    )
    assert total == 1
    assert items[0].vehiculo_id == v_propio.id


async def test_repositorios_items_e_historial_agregan(sesion: AsyncSession) -> None:
    """Los repositorios de ítems e historial agregan filas con `flush`."""
    _, vehiculo, repuesto = await _preparar_base(sesion)
    orden = OrdenTrabajo(
        vehiculo_id=vehiculo.id, estado="PENDIENTE", falla="F", total=Decimal("100.00")
    )
    sesion.add(orden)
    await sesion.flush()

    item = await RepositorioItemsOrden(sesion).add(
        ItemOrden(
            orden_id=orden.id,
            repuesto_id=repuesto.id,
            cantidad=1,
            precio_unitario=Decimal("100.00"),
        )
    )
    hist = await RepositorioHistorialOrden(sesion).add(
        HistorialEstadoOrden(orden_id=orden.id, hasta_estado="PENDIENTE")
    )
    assert item.id is not None and hist.id is not None
    await sesion.commit()


async def test_uow_confirmacion_atomica(sesion: AsyncSession) -> None:
    """Orden + ítems + historial dentro del UoW se confirman juntos."""
    _, vehiculo, repuesto = await _preparar_base(sesion)
    async with UoWOrdenes(sesion) as uow:
        orden = await uow.ordenes.add(
            OrdenTrabajo(
                vehiculo_id=vehiculo.id,
                estado="PENDIENTE",
                falla="F",
                total=Decimal("100.00"),
            )
        )
        await uow.items.add(
            ItemOrden(
                orden_id=orden.id,
                repuesto_id=repuesto.id,
                cantidad=1,
                precio_unitario=Decimal("100.00"),
            )
        )
        await uow.historial.add(
            HistorialEstadoOrden(orden_id=orden.id, hasta_estado="PENDIENTE")
        )

    assert (await sesion.execute(select(OrdenTrabajo))).scalars().all()
    assert (await sesion.execute(select(ItemOrden))).scalars().all()
    assert (await sesion.execute(select(HistorialEstadoOrden))).scalars().all()


async def test_uow_revierte_si_hay_excepcion(sesion: AsyncSession) -> None:
    """Una excepción dentro del bloque no deja filas (rollback del UoW)."""
    _, vehiculo, _ = await _preparar_base(sesion)
    with pytest.raises(RuntimeError):
        async with UoWOrdenes(sesion) as uow:
            await uow.ordenes.add(
                OrdenTrabajo(
                    vehiculo_id=vehiculo.id,
                    estado="PENDIENTE",
                    falla="F",
                    total=Decimal("0.00"),
                )
            )
            raise RuntimeError("fallo simulado")

    assert (await sesion.execute(select(OrdenTrabajo))).scalars().all() == []
