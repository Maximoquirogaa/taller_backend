"""Tests de servicio del módulo órdenes (Tasks 3.3, 3.4, 3.6).

Cubre las excepciones de dominio de `crear_orden` y el cálculo de precios y
total por el servidor (RN-10), en el orden de D4: catálogo, vehículo,
repuestos activos, repetidos. Cada comportamiento se triangula con al menos
dos casos.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ordenes.repository import RepositorioOrdenes
from app.modules.ordenes.schemas import EntradaCrearOrden, ItemEntrada
from app.modules.ordenes.models import OrdenTrabajo
from app.modules.ordenes.service import (
    CatalogoEstadosVacio,
    ConflictoComposicion,
    OrdenNoEncontrada,
    RepuestoNoDisponible,
    TransicionInvalida,
    VehiculoNoEncontrado,
    crear_orden,
    iniciar_orden,
)
from app.modules.ordenes.unit_of_work import UoWOrdenes
from app.modules.usuarios.models import Usuario
from test.ordenes.conftest import (
    crear_cliente,
    crear_repuesto,
    crear_vehiculo,
    insertar_catalogo,
)


async def _operador(sesion_db: AsyncSession) -> Usuario:
    """Crea un usuario operador (actor del historial) y confirma."""
    usuario = Usuario(
        email="operador@test",
        nombre="Operador",
        password_hash="x",
        activo=True,
        debe_cambiar_password=False,
    )
    sesion_db.add(usuario)
    await sesion_db.flush()
    await sesion_db.commit()
    await sesion_db.refresh(usuario)
    return usuario


async def _datos_orden(vehiculo_id: int, items: list[tuple[int, int]]) -> EntradaCrearOrden:
    """Construye el contrato de entrada con `(repuesto_id, cantidad)`."""
    return EntradaCrearOrden(
        vehiculo_id=vehiculo_id,
        falla="Ruido en el motor",
        items=[ItemEntrada(repuesto_id=r, cantidad=c) for r, c in items],
    )


async def test_crear_orden_catalogo_vacio_rechaza(sesion_db: AsyncSession) -> None:
    """Sin catálogo de estados, `crear_orden` lanza `CatalogoEstadosVacio` (RN-19).

    La validación del catálogo es la primera, así que ni siquiera hace falta
    que exista el vehículo.
    """
    datos = await _datos_orden(1, [(1, 1)])
    operador = await _operador(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        with pytest.raises(CatalogoEstadosVacio):
            await crear_orden(uow, datos, usuario_id=operador.id)


async def test_crear_orden_repuesto_inexistente_rechaza(sesion_db: AsyncSession) -> None:
    """Repuesto que no existe → `RepuestoNoDisponible` (D4, paso 3)."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    datos = await _datos_orden(vehiculo.id, [(999, 1)])
    operador = await _operador(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        with pytest.raises(RepuestoNoDisponible):
            await crear_orden(uow, datos, usuario_id=operador.id)


async def test_crear_orden_repuesto_dado_de_baja_rechaza(sesion_db: AsyncSession) -> None:
    """Repuesto dado de baja lógica → `RepuestoNoDisponible` (sólo activos, D4)."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuesto = await crear_repuesto(
        sesion_db, codigo="RBAJA", precio="100.00", borrado_en=datetime.now(UTC)
    )
    datos = await _datos_orden(vehiculo.id, [(repuesto.id, 1)])
    operador = await _operador(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        with pytest.raises(RepuestoNoDisponible):
            await crear_orden(uow, datos, usuario_id=operador.id)


async def test_crear_orden_repuesto_repetido_rechaza(sesion_db: AsyncSession) -> None:
    """El mismo `repuesto_id` dos veces → `ConflictoComposicion` (D4, paso 4)."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuesto = await crear_repuesto(sesion_db, codigo="R1", precio="100.00")
    datos = await _datos_orden(vehiculo.id, [(repuesto.id, 1), (repuesto.id, 2)])
    operador = await _operador(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        with pytest.raises(ConflictoComposicion):
            await crear_orden(uow, datos, usuario_id=operador.id)


async def test_crear_orden_vehiculo_inexistente_rechaza(sesion_db: AsyncSession) -> None:
    """Vehículo que no existe → `VehiculoNoEncontrado` (D4, paso 2)."""
    await insertar_catalogo(sesion_db)
    repuesto = await crear_repuesto(sesion_db, codigo="R1", precio="100.00")
    datos = await _datos_orden(999, [(repuesto.id, 1)])
    operador = await _operador(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        with pytest.raises(VehiculoNoEncontrado):
            await crear_orden(uow, datos, usuario_id=operador.id)


async def test_crear_orden_vehiculo_dado_de_baja_rechaza(sesion_db: AsyncSession) -> None:
    """Vehículo dado de baja lógica → `VehiculoNoEncontrado` (soft-delete, D4)."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(
        sesion_db, cliente_id=cliente.id, patente="AAA111", borrado_en=datetime.now(UTC)
    )
    repuesto = await crear_repuesto(sesion_db, codigo="R1", precio="100.00")
    datos = await _datos_orden(vehiculo.id, [(repuesto.id, 1)])
    operador = await _operador(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        with pytest.raises(VehiculoNoEncontrado):
            await crear_orden(uow, datos, usuario_id=operador.id)


async def test_crear_orden_exitoso_precios_copiados_y_total(sesion_db: AsyncSession) -> None:
    """Camino feliz: estado PENDIENTE, precios copiados, total del servidor,
    historial nulo → PENDIENTE del operador (US-023, RN-10)."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuesto_a = await crear_repuesto(sesion_db, codigo="RA", precio="100.00")
    repuesto_b = await crear_repuesto(sesion_db, codigo="RB", precio="200.00")
    datos = await _datos_orden(vehiculo.id, [(repuesto_a.id, 2), (repuesto_b.id, 1)])
    operador = await _operador(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        orden = await crear_orden(uow, datos, usuario_id=operador.id)

    assert orden.estado == "PENDIENTE"
    # total = 100*2 + 200*1 = 400, cuantizado a 2 decimales por el servidor
    assert orden.total == Decimal("400.00")

    items = {item.repuesto_id: item for item in orden.items}
    assert items[repuesto_a.id].precio_unitario == Decimal("100.00")
    assert items[repuesto_a.id].cantidad == 2
    assert items[repuesto_b.id].precio_unitario == Decimal("200.00")
    assert items[repuesto_b.id].cantidad == 1

    assert len(orden.historial) == 1
    entrada = orden.historial[0]
    assert entrada.desde_estado is None
    assert entrada.hasta_estado == "PENDIENTE"
    assert entrada.usuario_id == operador.id


async def test_crear_orden_un_item(sesion_db: AsyncSession) -> None:
    """Un solo ítem: total = precio × cantidad, estado PENDIENTE."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuesto = await crear_repuesto(sesion_db, codigo="R1", precio="250.50")
    datos = await _datos_orden(vehiculo.id, [(repuesto.id, 3)])
    operador = await _operador(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        orden = await crear_orden(uow, datos, usuario_id=operador.id)

    assert orden.estado == "PENDIENTE"
    assert orden.total == Decimal("751.50")
    assert len(orden.items) == 1
    assert orden.items[0].precio_unitario == Decimal("250.50")


async def test_crear_orden_cuatro_items(sesion_db: AsyncSession) -> None:
    """Cuatro ítems: total distinto pero mismo comportamiento (suma del servidor)."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuestos = [
        await crear_repuesto(sesion_db, codigo=f"R{i}", precio=f"{100 * (i + 1)}.00")
        for i in range(4)
    ]
    datos = await _datos_orden(vehiculo.id, [(r.id, i + 1) for i, r in enumerate(repuestos)])
    operador = await _operador(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        orden = await crear_orden(uow, datos, usuario_id=operador.id)

    assert orden.estado == "PENDIENTE"
    esperado = sum(Decimal(str(100 * (i + 1))) * (i + 1) for i in range(4))
    assert orden.total == esperado
    assert len(orden.items) == 4
    assert len(orden.historial) == 1
    assert orden.historial[0].desde_estado is None
    assert orden.historial[0].hasta_estado == "PENDIENTE"


async def test_crear_orden_precio_copiado_inmutable_tras_actualizar_repuesto(
    sesion_db: AsyncSession,
) -> None:
    """El precio copiado no cambia aunque el repuesto se actualice después (RN-20)."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuesto = await crear_repuesto(sesion_db, codigo="R1", precio="100.00")
    datos = await _datos_orden(vehiculo.id, [(repuesto.id, 1)])
    operador = await _operador(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        orden = await crear_orden(uow, datos, usuario_id=operador.id)

    precio_copiado = orden.items[0].precio_unitario
    assert precio_copiado == Decimal("100.00")

    # Simula la actualización de precio del repuesto (C-05 PATCH /repuestos/{id})
    repuesto.precio = Decimal("200.00")
    await sesion_db.flush()

    detalle = await RepositorioOrdenes(sesion_db).get_detalle(orden.id)
    assert detalle.items[0].precio_unitario == precio_copiado


async def _orden_pendiente(sesion_db: AsyncSession, estado: str = "PENDIENTE") -> int:
    """Inserta una orden en el estado indicado y devuelve su id."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    orden = OrdenTrabajo(
        vehiculo_id=vehiculo.id, estado=estado, falla="Falla", total=Decimal("0")
    )
    sesion_db.add(orden)
    await sesion_db.flush()
    await sesion_db.commit()
    await sesion_db.refresh(orden)
    return orden.id


async def _operador_iniciar(sesion_db: AsyncSession) -> Usuario:
    usuario = Usuario(
        email="meca@test", nombre="Meca", password_hash="x",
        activo=True, debe_cambiar_password=False,
    )
    sesion_db.add(usuario)
    await sesion_db.flush()
    await sesion_db.commit()
    await sesion_db.refresh(usuario)
    return usuario


async def test_iniciar_orden_pasa_a_en_reparacion_con_mecanico_y_historial(
    sesion_db: AsyncSession,
) -> None:
    """PENDIENTE → EN_REPARACION, mecanico_id = usuario y una línea de historial."""
    orden_id = await _orden_pendiente(sesion_db, "PENDIENTE")
    operador = await _operador_iniciar(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        orden = await iniciar_orden(uow, orden_id=orden_id, usuario_id=operador.id)

    assert orden.estado == "EN_REPARACION"
    assert orden.mecanico_id == operador.id
    assert len(orden.historial) == 2
    ultima = orden.historial[-1]
    assert ultima.desde_estado == "PENDIENTE"
    assert ultima.hasta_estado == "EN_REPARACION"
    assert ultima.usuario_id == operador.id


async def test_iniciar_orden_ya_en_reparacion_rechaza(
    sesion_db: AsyncSession,
) -> None:
    """Orden ya EN_REPARACION → `TransicionInvalida`."""
    orden_id = await _orden_pendiente(sesion_db, "EN_REPARACION")
    operador = await _operador_iniciar(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        with pytest.raises(TransicionInvalida):
            await iniciar_orden(uow, orden_id=orden_id, usuario_id=operador.id)


async def test_iniciar_orden_inexistente_rechaza(sesion_db: AsyncSession) -> None:
    """Orden que no existe → `OrdenNoEncontrada`."""
    operador = await _operador_iniciar(sesion_db)
    async with UoWOrdenes(sesion_db) as uow:
        with pytest.raises(OrdenNoEncontrada):
            await iniciar_orden(uow, orden_id=999999, usuario_id=operador.id)


async def test_iniciar_orden_estado_final_rechaza(sesion_db: AsyncSession) -> None:
    """Orden TERMINADA o CANCELADA → `TransicionInvalida`."""
    operador = await _operador_iniciar(sesion_db)
    for estado in ("TERMINADA", "CANCELADA"):
        orden_id = await _orden_pendiente(sesion_db, estado)
        async with UoWOrdenes(sesion_db) as uow:
            with pytest.raises(TransicionInvalida):
                await iniciar_orden(uow, orden_id=orden_id, usuario_id=operador.id)
