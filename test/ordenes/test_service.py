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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ordenes.repository import RepositorioOrdenes
from app.modules.ordenes.schemas import EntradaCrearOrden, ItemEntrada
from app.modules.ordenes.models import (
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)
from app.modules.ordenes.service import (
    CatalogoEstadosVacio,
    ConflictoComposicion,
    OrdenAjena,
    OrdenNoEncontrada,
    RepuestoNoDisponible,
    StockInsuficiente,
    TransicionInvalida,
    VehiculoNoEncontrado,
    cancelar_orden,
    crear_orden,
    iniciar_orden,
    terminar_orden,
)
from app.modules.ordenes.unit_of_work import UoWOrdenes
from app.modules.repuestos.models import MovimientoStock, Repuesto
from app.modules.usuarios.models import Usuario
from app.core.dependencies import UsuarioAutenticado
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


async def _orden_pendiente(
    sesion_db: AsyncSession, estado: str = "PENDIENTE", *, sufijo: str = "a"
) -> int:
    """Inserta una orden en el estado indicado y devuelve su id.

    El documento de cliente y la patente se derivan de `sufijo` para poder
    crear varias órdenes dentro del mismo test sin chocar con los UNIQUE.
    """
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(
        sesion_db, nombre=f"Ana {sufijo}", documento=f"doc-{sufijo}"
    )
    vehiculo = await crear_vehiculo(
        sesion_db, cliente_id=cliente.id, patente=f"AAA{sufijo}"
    )
    orden = OrdenTrabajo(
        vehiculo_id=vehiculo.id, estado=estado, falla="Falla", total=Decimal("0")
    )
    sesion_db.add(orden)
    await sesion_db.flush()
    sesion_db.add(
        HistorialEstadoOrden(
            orden_id=orden.id,
            desde_estado=None,
            hasta_estado=estado,
            usuario_id=None,
        )
    )
    await sesion_db.commit()
    await sesion_db.refresh(orden)
    return orden.id


async def _operador_iniciar(sesion_db: AsyncSession, email: str = "meca@test") -> Usuario:
    usuario = Usuario(
        email=email, nombre=email.split("@")[0], password_hash="x",
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
    operador_id = operador.id
    for estado in ("TERMINADA", "CANCELADA"):
        orden_id = await _orden_pendiente(sesion_db, estado, sufijo=estado.lower())
        async with UoWOrdenes(sesion_db) as uow:
            with pytest.raises(TransicionInvalida):
                await iniciar_orden(uow, orden_id=orden_id, usuario_id=operador_id)

# -- Terminar / cancelar: helpers y casos (tasks 3.1, 4.1, 4.5) --------------


def _identidad(usuario: Usuario, *roles: str) -> UsuarioAutenticado:
    """Construye la identidad de petici�n que recibe el servicio."""
    return UsuarioAutenticado(
        usuario=usuario, roles_vigentes=list(roles), roles_token=list(roles)
    )


async def _orden_con_items(
    sesion_db: AsyncSession,
    *,
    items: list[tuple[str, int, int]],
    estado: str = "EN_REPARACION",
    mecanico_id: int | None = None,
    sufijo: str = "t",
    duenio_usuario_id: int | None = None,
    vehiculo_baja: bool = False,
) -> dict:
    """Inserta orden + �tems + historial; `items` = (codigo, cantidad, stock)."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(
        sesion_db,
        nombre=f"Cliente {sufijo}",
        documento=f"doc-svc-{sufijo}",
        usuario_id=duenio_usuario_id,
    )
    vehiculo = await crear_vehiculo(
        sesion_db,
        cliente_id=cliente.id,
        patente=f"PAT{sufijo}",
        borrado_en=datetime.now(UTC) if vehiculo_baja else None,
    )
    orden = OrdenTrabajo(
        vehiculo_id=vehiculo.id,
        mecanico_id=mecanico_id,
        estado=estado,
        falla="Falla",
        total=Decimal("0"),
    )
    sesion_db.add(orden)
    await sesion_db.flush()

    repuestos: dict[str, Repuesto] = {}
    for indice, (codigo, cantidad, stock) in enumerate(items):
        repuesto = await crear_repuesto(
            sesion_db,
            codigo=f"{codigo}-{sufijo}",
            precio="100.00",
            stock=stock,
        )
        repuestos[codigo] = repuesto
        sesion_db.add(
            ItemOrden(
                orden_id=orden.id,
                repuesto_id=repuesto.id,
                cantidad=cantidad,
                precio_unitario=repuesto.precio,
            )
        )

    sesion_db.add(
        HistorialEstadoOrden(
            orden_id=orden.id,
            desde_estado=None,
            hasta_estado="PENDIENTE",
            usuario_id=None,
        )
    )
    if estado != "PENDIENTE":
        sesion_db.add(
            HistorialEstadoOrden(
                orden_id=orden.id,
                desde_estado="PENDIENTE",
                hasta_estado=estado,
                usuario_id=mecanico_id,
            )
        )
    await sesion_db.commit()
    await sesion_db.refresh(orden)
    return {
        "orden_id": orden.id,
        "vehiculo_id": vehiculo.id,
        "cliente_id": cliente.id,
        "repuestos": {codigo: repuesto.id for codigo, repuesto in repuestos.items()},
    }


async def _stock(sesion_db: AsyncSession, repuesto_id: int) -> int:
    """Lee el stock persistido por consulta directa (nunca un objeto en memoria)."""
    return int(
        (
            await sesion_db.execute(
                select(Repuesto.stock).where(Repuesto.id == repuesto_id)
            )
        ).scalar_one()
    )


async def _contar_movimientos(sesion_db: AsyncSession, orden_id: int) -> int:
    """Cuenta filas de `movimiento_stock` asociadas a la orden."""
    return int(
        (
            await sesion_db.execute(
                select(func.count())
                .select_from(MovimientoStock)
                .where(MovimientoStock.orden_id == orden_id)
            )
        ).scalar_one()
    )


async def _contar_historial(sesion_db: AsyncSession, orden_id: int) -> int:
    """Cuenta l�neas de historial persistidas de la orden."""
    return int(
        (
            await sesion_db.execute(
                select(func.count())
                .select_from(HistorialEstadoOrden)
                .where(HistorialEstadoOrden.orden_id == orden_id)
            )
        ).scalar_one()
    )


async def _estado_persistido(sesion_db: AsyncSession, orden_id: int) -> str:
    """Lee el estado persistido por consulta directa."""
    return str(
        (
            await sesion_db.execute(
                select(OrdenTrabajo.estado).where(OrdenTrabajo.id == orden_id)
            )
        ).scalar_one()
    )


async def test_iniciar_orden_con_items_no_toca_items_ni_historial_previo(
    sesion_db: AsyncSession,
) -> None:
    """Iniciar con ítems: sólo cambia estado/mecánico y agrega una línea (task 2.5)."""
    mecanico = await _operador_iniciar(sesion_db, email="meca-items@test")
    datos = await _orden_con_items(
        sesion_db,
        items=[("RI", 2, 10)],
        estado="PENDIENTE",
        sufijo="ini",
    )
    async with UoWOrdenes(sesion_db) as uow:
        orden = await iniciar_orden(
            uow, datos["orden_id"], usuario_id=mecanico.id
        )

    assert orden.estado == "EN_REPARACION"
    assert orden.mecanico_id == mecanico.id
    assert len(orden.items) == 1
    assert orden.items[0].cantidad == 2
    assert len(orden.historial) == 2
    assert orden.historial[0].hasta_estado == "PENDIENTE"
    assert orden.historial[-1].hasta_estado == "EN_REPARACION"


async def test_terminar_orden_con_stock_justo_lo_deja_en_cero(
    sesion_db: AsyncSession,
) -> None:
    """cantidad == stock disponible → TERMINADA y stock 0 (triangulación 3.5)."""
    mecanico = await _operador_iniciar(sesion_db, email="meca-justo@test")
    datos = await _orden_con_items(
        sesion_db,
        items=[("RJ", 4, 4)],
        mecanico_id=mecanico.id,
        sufijo="justo",
    )
    async with UoWOrdenes(sesion_db) as uow:
        orden = await terminar_orden(
            uow, datos["orden_id"], _identidad(mecanico, "MECANICO")
        )

    assert orden.estado == "TERMINADA"
    assert await _stock(sesion_db, datos["repuestos"]["RJ"]) == 0
    assert await _contar_movimientos(sesion_db, datos["orden_id"]) == 1


async def test_terminar_orden_con_stock_cero_rechaza(
    sesion_db: AsyncSession,
) -> None:
    """Un ítem con stock 0 → `StockInsuficiente` (triangulación 3.5)."""
    mecanico = await _operador_iniciar(sesion_db, email="meca-cero@test")
    datos = await _orden_con_items(
        sesion_db,
        items=[("RZ", 1, 0)],
        mecanico_id=mecanico.id,
        sufijo="cero",
    )
    with pytest.raises(StockInsuficiente):
        async with UoWOrdenes(sesion_db) as uow:
            await terminar_orden(
                uow, datos["orden_id"], _identidad(mecanico, "MECANICO")
            )
    assert await _contar_movimientos(sesion_db, datos["orden_id"]) == 0
    assert await _estado_persistido(sesion_db, datos["orden_id"]) == "EN_REPARACION"


async def test_terminar_orden_mecanico_asignado_descuenta_stock_y_crea_movimientos(
    sesion_db: AsyncSession,
) -> None:
    """Mec�nico asignado + stock suficiente ? TERMINADA, stock descontado,
    movimientos de salida e historial EN_REPARACION ? TERMINADA (RN-13/RN-14)."""
    mecanico = await _operador_iniciar(sesion_db)
    datos = await _orden_con_items(
        sesion_db,
        items=[("RA", 2, 10), ("RB", 1, 5)],
        mecanico_id=mecanico.id,
        sufijo="mec",
    )
    identidad = _identidad(mecanico, "MECANICO")
    async with UoWOrdenes(sesion_db) as uow:
        orden = await terminar_orden(uow, datos["orden_id"], identidad)

    assert orden.estado == "TERMINADA"
    assert orden.historial[-1].desde_estado == "EN_REPARACION"
    assert orden.historial[-1].hasta_estado == "TERMINADA"
    assert orden.historial[-1].usuario_id == mecanico.id

    assert await _stock(sesion_db, datos["repuestos"]["RA"]) == 8
    assert await _stock(sesion_db, datos["repuestos"]["RB"]) == 4
    assert await _contar_movimientos(sesion_db, datos["orden_id"]) == 2
    assert await _contar_historial(sesion_db, datos["orden_id"]) == 3


async def test_terminar_orden_admin_ajena_exitosa(sesion_db: AsyncSession) -> None:
    """ADMIN no asignado tambi�n puede terminar (D2, triangulaci�n)."""
    mecanico = await _operador_iniciar(sesion_db)
    admin = await _operador_iniciar(sesion_db, email="admin@test")
    datos = await _orden_con_items(
        sesion_db,
        items=[("RA", 1, 3)],
        mecanico_id=mecanico.id,
        sufijo="adm",
    )
    async with UoWOrdenes(sesion_db) as uow:
        orden = await terminar_orden(
            uow, datos["orden_id"], _identidad(admin, "ADMIN")
        )

    assert orden.estado == "TERMINADA"
    assert await _stock(sesion_db, datos["repuestos"]["RA"]) == 2


async def test_terminar_orden_stock_insuficiente_revierte_todo(
    sesion_db: AsyncSession,
) -> None:
    """Un �tem sin stock ? `StockInsuficiente` y ninguna escritura (RN-13)."""
    mecanico = await _operador_iniciar(sesion_db)
    datos = await _orden_con_items(
        sesion_db,
        items=[("RA", 2, 10), ("RB", 5, 1)],
        mecanico_id=mecanico.id,
        sufijo="ins",
    )
    identidad = _identidad(mecanico, "MECANICO")
    with pytest.raises(StockInsuficiente):
        async with UoWOrdenes(sesion_db) as uow:
            await terminar_orden(uow, datos["orden_id"], identidad)

    assert await _stock(sesion_db, datos["repuestos"]["RA"]) == 10
    assert await _stock(sesion_db, datos["repuestos"]["RB"]) == 1
    assert await _contar_movimientos(sesion_db, datos["orden_id"]) == 0
    assert await _contar_historial(sesion_db, datos["orden_id"]) == 2
    assert await _estado_persistido(sesion_db, datos["orden_id"]) == "EN_REPARACION"


async def test_terminar_orden_ajena_rechaza_antes_que_estado(
    sesion_db: AsyncSession,
) -> None:
    """Usuario no asignado ni ADMIN ? `OrdenAjena` aunque el estado no permita (403 antes que 409)."""
    mecanico = await _operador_iniciar(sesion_db)
    otro = await _operador_iniciar(sesion_db, email="otro@test")
    datos = await _orden_con_items(
        sesion_db,
        items=[("RA", 1, 3)],
        estado="PENDIENTE",
        mecanico_id=mecanico.id,
        sufijo="ajena",
    )
    with pytest.raises(OrdenAjena):
        async with UoWOrdenes(sesion_db) as uow:
            await terminar_orden(
                uow, datos["orden_id"], _identidad(otro, "MECANICO")
            )

    assert await _estado_persistido(sesion_db, datos["orden_id"]) == "PENDIENTE"


async def test_terminar_orden_no_en_reparacion_rechaza(
    sesion_db: AsyncSession,
) -> None:
    """Mec�nico asignado sobre orden PENDIENTE ? `TransicionInvalida`."""
    mecanico = await _operador_iniciar(sesion_db)
    datos = await _orden_con_items(
        sesion_db,
        items=[("RA", 1, 3)],
        estado="PENDIENTE",
        mecanico_id=mecanico.id,
        sufijo="pend",
    )
    with pytest.raises(TransicionInvalida):
        async with UoWOrdenes(sesion_db) as uow:
            await terminar_orden(
                uow, datos["orden_id"], _identidad(mecanico, "MECANICO")
            )


async def test_terminar_orden_inexistente_rechaza(sesion_db: AsyncSession) -> None:
    """Orden inexistente ? `OrdenNoEncontrada`."""
    mecanico = await _operador_iniciar(sesion_db)
    with pytest.raises(OrdenNoEncontrada):
        async with UoWOrdenes(sesion_db) as uow:
            await terminar_orden(uow, 999999, _identidad(mecanico, "MECANICO"))


async def test_cancelar_orden_staff_y_duenio(
    sesion_db: AsyncSession,
) -> None:
    """RECEPCION y el due�o del veh�culo cancelan �rdenes PENDIENTES (RN-12)."""
    recepcion = await _operador_iniciar(sesion_db, email="recepcion@test")
    duenio = await _operador_iniciar(sesion_db, email="duenio@test")
    datos_staff = await _orden_con_items(
        sesion_db, items=[("RA", 1, 3)], estado="PENDIENTE", sufijo="rec"
    )
    datos_duenio = await _orden_con_items(
        sesion_db,
        items=[("RB", 1, 3)],
        estado="PENDIENTE",
        sufijo="due",
        duenio_usuario_id=duenio.id,
    )

    async with UoWOrdenes(sesion_db) as uow:
        orden = await cancelar_orden(
            uow, datos_staff["orden_id"], _identidad(recepcion, "RECEPCION")
        )
    assert orden.estado == "CANCELADA"
    assert orden.historial[-1].desde_estado == "PENDIENTE"
    assert orden.historial[-1].hasta_estado == "CANCELADA"

    async with UoWOrdenes(sesion_db) as uow:
        orden = await cancelar_orden(
            uow, datos_duenio["orden_id"], _identidad(duenio, "CLIENTE")
        )
    assert orden.estado == "CANCELADA"
    assert await _estado_persistido(sesion_db, datos_duenio["orden_id"]) == "CANCELADA"


async def test_cancelar_orden_ajena_da_403_antes_del_estado(
    sesion_db: AsyncSession,
) -> None:
    """Usuario ajeno a una orden PENDIENTE ? `OrdenAjena` (403, no 409)."""
    ajeno = await _operador_iniciar(sesion_db, email="ajeno@test")
    datos = await _orden_con_items(
        sesion_db, items=[("RA", 1, 3)], estado="PENDIENTE", sufijo="ajeno"
    )
    with pytest.raises(OrdenAjena):
        async with UoWOrdenes(sesion_db) as uow:
            await cancelar_orden(
                uow, datos["orden_id"], _identidad(ajeno, "CLIENTE")
            )
    assert await _estado_persistido(sesion_db, datos["orden_id"]) == "PENDIENTE"


async def test_cancelar_orden_en_estado_final_rechaza(
    sesion_db: AsyncSession,
) -> None:
    """Con relaci�n v�lida pero estado final ? `TransicionInvalida` (409)."""
    recepcion = await _operador_iniciar(sesion_db, email="recepcion2@test")
    datos = await _orden_con_items(
        sesion_db, items=[("RA", 1, 3)], estado="TERMINADA", sufijo="fin"
    )
    with pytest.raises(TransicionInvalida):
        async with UoWOrdenes(sesion_db) as uow:
            await cancelar_orden(
                uow, datos["orden_id"], _identidad(recepcion, "RECEPCION")
            )
    assert await _estado_persistido(sesion_db, datos["orden_id"]) == "TERMINADA"


async def test_cancelar_orden_inexistente_rechaza(sesion_db: AsyncSession) -> None:
    """Orden inexistente ? `OrdenNoEncontrada`."""
    recepcion = await _operador_iniciar(sesion_db, email="recepcion3@test")
    with pytest.raises(OrdenNoEncontrada):
        async with UoWOrdenes(sesion_db) as uow:
            await cancelar_orden(
                uow, 999999, _identidad(recepcion, "RECEPCION")
            )


async def test_cancelar_orden_de_vehiculo_dado_de_baja_por_su_duenio(
    sesion_db: AsyncSession,
) -> None:
    """La relaci�n con la orden se eval�a por veh�culo aunque est� de baja (task 4.5)."""
    duenio = await _operador_iniciar(sesion_db, email="duenio2@test")
    datos = await _orden_con_items(
        sesion_db,
        items=[("RA", 1, 3)],
        estado="PENDIENTE",
        sufijo="baja",
        duenio_usuario_id=duenio.id,
        vehiculo_baja=True,
    )
    async with UoWOrdenes(sesion_db) as uow:
        orden = await cancelar_orden(
            uow, datos["orden_id"], _identidad(duenio, "CLIENTE")
        )
    assert orden.estado == "CANCELADA"
