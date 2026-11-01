"""Lógica de negocio del módulo ordenes (capa Service).

Implementa la apertura atómica de una orden de trabajo (RN-10, Flujo 4) y la
máquina de estados de C-08 (Flujos 5–7):

- `iniciar_orden`: PENDIENTE → EN_REPARACION asignando el mecánico (RN-11).
- `terminar_orden`: EN_REPARACION → TERMINADA descontando stock por
  `movimiento_stock` en la misma transacción (RN-13/RN-14).
- `cancelar_orden`: PENDIENTE → CANCELADA con relación antes que estado (RN-12).

El catálogo de estados debe estar cargado (RN-19); el vehículo y los repuestos
deben existir y estar vigentes; los precios y el total los calcula exclusivamente
el servidor. Cada operación confirma o revierte en un único bloque del UoW.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.ordenes.models import (
    EstadoOrden,
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)
from app.modules.ordenes.schemas import EntradaCrearOrden
from app.modules.ordenes.unit_of_work import UoWOrdenes
from app.modules.repuestos.models import MovimientoStock
from app.core.paginacion import PaginaDe, ParametrosPagina, construir_pagina
from app.core.dependencies import UsuarioAutenticado

MENSAJE_CATALOGO_VACIO = (
    "El catálogo de estados de orden está vacío: cargá los estados antes de abrir órdenes."
)
MENSAJE_REPUESTO_NO_DISPONIBLE = "El repuesto no existe o fue dado de baja."
MENSAJE_CONFLICTO_COMPOSICION = "No se puede repetir un mismo repuesto en una orden."
MENSAJE_VEHICULO_NO_ENCONTRADO = "El vehículo no existe o fue dado de baja."

CANTIDAD_DECIMALES_TOTAL = 2


class CatalogoEstadosVacio(Exception):
    """No hay estados cargados: no se puede abrir una orden (RN-19 → 409)."""


class RepuestoNoDisponible(Exception):
    """Un repuesto pedido no existe o está dado de baja (D4 → 409)."""


class ConflictoComposicion(Exception):
    """Un `repuesto_id` se repite en los ítems de la orden (D4 → 409)."""


class VehiculoNoEncontrado(Exception):
    """El vehículo no existe o está dado de baja (D4 → 404)."""


def _cuantizar_total(valor: Decimal) -> Decimal:
    """Cuantiza un importe a dos decimales (moneda, sin pérdidas de precisión)."""
    return valor.quantize(Decimal(10) ** -CANTIDAD_DECIMALES_TOTAL)


async def crear_orden(
    uow: UoWOrdenes,
    datos: EntradaCrearOrden,
    usuario_id: int,
) -> OrdenTrabajo:
    """Abre una orden de trabajo de forma atómica (US-023, RN-10, D4).

    Todo ocurre dentro de un único `async with uow`, que confirma al salir o
    revierte ante cualquier excepción:

    1. Verifica que el catálogo de estados no esté vacío.
    2. Carga el vehículo vigente (bajas lógicas ocultas).
    3. Carga los repuestos activos pedidos en una sola consulta.
    4. Rechaza repuestos repetidos en el payload.
    5. Crea la orden con `estado="PENDIENTE"` y el total calculado por el
       servidor (`sum(precio × cantidad)`, cuantizado a 2 decimales).
    6. Crea un ítem por repuesto copiando `precio_unitario` del repuesto.
    7. Crea la línea de historial inicial: `nulo → PENDIENTE`.

    Args:
        uow: unit of work de la orden (dueño de la transacción).
        datos: contrato de entrada ya validado (`vehiculo_id`, `falla`, `items`).
        usuario_id: identificador del operador que abre la orden.

    Returns:
        La `OrdenTrabajo` creada, con ítems (con repuesto) e historial
        precargados, lista para serializar en la respuesta.

    Raises:
        CatalogoEstadosVacio: si el catálogo de estados está vacío.
        RepuestoNoDisponible: si algún repuesto pedido no existe o está dado de baja.
        ConflictoComposicion: si un `repuesto_id` se repite en `items`.
        VehiculoNoEncontrado: si el vehículo no existe o está dado de baja.
    """
    async with uow:
        # 1. Catálogo no vacío (primera validación, RN-19).
        if not await uow.estados.existe_catalogo():
            raise CatalogoEstadosVacio(MENSAJE_CATALOGO_VACIO)

        # 2. Vehículo vigente.
        vehiculo = await uow.vehiculos.get_by_id(datos.vehiculo_id)
        if vehiculo is None:
            raise VehiculoNoEncontrado(MENSAJE_VEHICULO_NO_ENCONTRADO)

        # 3. Repuestos activos en una sola consulta (D4).
        ids_solicitados = [item.repuesto_id for item in datos.items]
        repuestos_activos = await uow.repuestos.get_activos_por_ids(ids_solicitados)
        repuestos_por_id = {repuesto.id: repuesto for repuesto in repuestos_activos}

        for item in datos.items:
            if item.repuesto_id not in repuestos_por_id:
                raise RepuestoNoDisponible(MENSAJE_REPUESTO_NO_DISPONIBLE)

        # 4. Sin repuestos repetidos en el payload (D4).
        if len(ids_solicitados) != len(set(ids_solicitados)):
            raise ConflictoComposicion(MENSAJE_CONFLICTO_COMPOSICION)

        # 5. Orden con total calculado por el servidor (RN-10).
        total = _cuantizar_total(
            sum(
                repuestos_por_id[item.repuesto_id].precio * item.cantidad
                for item in datos.items
            )
        )
        orden = OrdenTrabajo(
            vehiculo_id=datos.vehiculo_id,
            estado="PENDIENTE",
            falla=datos.falla,
            total=total,
        )
        await uow.ordenes.add(orden)

        # 6. Ítems con el precio copiado del repuesto (nunca el del cliente).
        for item in datos.items:
            repuesto = repuestos_por_id[item.repuesto_id]
            await uow.items.add(
                ItemOrden(
                    orden_id=orden.id,
                    repuesto_id=item.repuesto_id,
                    cantidad=item.cantidad,
                    precio_unitario=repuesto.precio,
                )
            )

        # 7. Historial inicial: nulo → PENDIENTE (RN-10, historial null→PENDIENTE).
        await uow.historial.add(
            HistorialEstadoOrden(
                orden_id=orden.id,
                desde_estado=None,
                hasta_estado="PENDIENTE",
                usuario_id=usuario_id,
            )
        )

        # Devolver la orden ya cargada con sus relaciones (detalle completo).
        return await uow.ordenes.get_detalle(orden.id)


MENSAJE_ORDEN_NO_ENCONTRADA = "La orden de trabajo no existe."
MENSAJE_ORDEN_AJENA = "No tenés permiso para ver esta orden."
MENSAJE_ORDEN_AJENA_ACCION = "No tenés permiso para operar sobre esta orden."
MENSAJE_TRANSICION_INVALIDA = (
    "La orden no está en un estado que permita esa transición."
)
MENSAJE_STOCK_INSUFICIENTE = (
    "No hay stock suficiente de uno o más repuestos para terminar la reparación."
)
MOTIVO_MOVIMIENTO_SALIDA = "Consumo orden"

ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_EN_REPARACION = "EN_REPARACION"
ESTADO_TERMINADA = "TERMINADA"
ESTADO_CANCELADA = "CANCELADA"


class OrdenNoEncontrada(Exception):
    """La orden solicitada no existe (→ 404)."""


class OrdenAjena(Exception):
    """La orden existe pero no pertenece al usuario que la consulta (→ 403)."""


class TransicionInvalida(Exception):
    """La orden no está en el estado que exige la transición pedida (→ 409)."""


class StockInsuficiente(Exception):
    """Algún ítem pide más unidades de las disponibles en stock (→ 409)."""


ROLES_STAFF = ("ADMIN", "RECEPCION", "MECANICO")


async def obtener_detalle(
    uow: UoWOrdenes,
    orden_id: int,
    usuario: UsuarioAutenticado,
) -> OrdenTrabajo:
    """Devuelve el detalle de una orden aplicando la regla 404 → 403 de D8.

    Primero se busca la orden: si no existe se lanza `OrdenNoEncontrada` (404).
    Si existe, un staff (ADMIN/RECEPCION/MECANICO) la ve cualquiera; un CLIENTE
    solo la ve si es dueño del vehículo, caso contrario `OrdenAjena` (403).
    El orden 404 → 403 evita filtrar la existencia de una orden a un usuario
    que no es su dueño (RN-17).

    Args:
        uow: unit of work de la orden.
        orden_id: identificador de la orden.
        usuario: usuario autenticado de la petición.

    Returns:
        La `OrdenTrabajo` con relaciones precargadas.

    Raises:
        OrdenNoEncontrada: si no existe la orden.
        OrdenAjena: si el usuario no es staff ni dueño del vehículo.
    """
    orden = await uow.ordenes.get_detalle(orden_id)
    if orden is None:
        raise OrdenNoEncontrada(MENSAJE_ORDEN_NO_ENCONTRADA)

    es_staff = any(rol in usuario.roles_vigentes for rol in ROLES_STAFF)
    if es_staff:
        return orden

    # CLIENTE: solo ve órdenes de sus propios vehículos.
    vehiculo = orden.vehiculo
    if (
        vehiculo is None
        or vehiculo.cliente is None
        or vehiculo.cliente.usuario_id != usuario.id
    ):
        raise OrdenAjena(MENSAJE_ORDEN_AJENA)
    return orden


async def listar_estados(uow: UoWOrdenes) -> list[EstadoOrden]:
    """Devuelve el catálogo de estados ordenado por posición (US-029, RN-19).

    Cualquier usuario autenticado puede consultarlo.
    """
    async with uow:
        return await uow.estados.listar()


async def listar_mis_ordenes(
    uow: UoWOrdenes,
    usuario_id: int,
    parametros: ParametrosPagina,
) -> PaginaDe[OrdenTrabajo]:
    """Devuelve las órdenes de los vehículos propios del usuario (US-030, RN-17, D9).

    Resuelve la ficha de cliente del usuario; si no existe, devuelve una página
    vacía sin consultar órdenes. Filtra solo vehículos vigentes.

    Args:
        uow: unit of work de la orden.
        usuario_id: identificador del usuario.
        parametros: parámetros de paginación ya validados.

    Returns:
        `PaginaDe[OrdenTrabajo]` con las órdenes propias de la página.
    """
    async with uow:
        cliente = await uow.clientes.get_por_usuario_id(usuario_id)
        if cliente is None:
            return PaginaDe[OrdenTrabajo](
                items=[],
                total=0,
                page=parametros.page,
                size=parametros.size,
                pages=1,
            )
        items, total = await uow.ordenes.buscar_por_usuario(
            usuario_id, parametros.desplazamiento, parametros.size
        )
        return construir_pagina(items, total=total, parametros=parametros)


def _es_staff(usuario: UsuarioAutenticado) -> bool:
    """Indica si el usuario tiene alguno de los roles de personal del taller."""
    return any(rol in usuario.roles_vigentes for rol in ROLES_STAFF)


def _es_duenio_del_vehiculo(orden: OrdenTrabajo, usuario: UsuarioAutenticado) -> bool:
    """Indica si el usuario es el dueño del vehículo de la orden (RN-17)."""
    vehiculo = orden.vehiculo
    return (
        vehiculo is not None
        and vehiculo.cliente is not None
        and vehiculo.cliente.usuario_id == usuario.id
    )


async def iniciar_orden(
    uow: UoWOrdenes,
    orden_id: int,
    usuario_id: int,
) -> OrdenTrabajo:
    """Inicia la reparación de una orden PENDIENTE (US-026, RN-11).

    Dentro de un único `async with uow`:

    1. Carga la orden; si no existe → `OrdenNoEncontrada` (404).
    2. Exige estado PENDIENTE; cualquier otro → `TransicionInvalida` (409).
    3. Asigna `mecanico_id = usuario_id` y pasa a EN_REPARACION.
    4. Agrega la línea de historial PENDIENTE → EN_REPARACION.

    Args:
        uow: unit of work de la orden (dueño de la transacción).
        orden_id: identificador de la orden a iniciar.
        usuario_id: mecánico autenticado que toma la orden.

    Returns:
        La orden recargada con relaciones e historial actualizado.

    Raises:
        OrdenNoEncontrada: si la orden no existe.
        TransicionInvalida: si la orden no está PENDIENTE.
    """
    async with uow:
        orden = await uow.ordenes.get_detalle(orden_id)
        if orden is None:
            raise OrdenNoEncontrada(MENSAJE_ORDEN_NO_ENCONTRADA)
        if orden.estado != ESTADO_PENDIENTE:
            raise TransicionInvalida(MENSAJE_TRANSICION_INVALIDA)

        await uow.ordenes.update(
            orden,
            {"estado": ESTADO_EN_REPARACION, "mecanico_id": usuario_id},
        )
        await uow.historial.add(
            HistorialEstadoOrden(
                orden_id=orden.id,
                desde_estado=ESTADO_PENDIENTE,
                hasta_estado=ESTADO_EN_REPARACION,
                usuario_id=usuario_id,
            )
        )
        return await uow.ordenes.get_detalle(orden.id)


async def terminar_orden(
    uow: UoWOrdenes,
    orden_id: int,
    usuario: UsuarioAutenticado,
) -> OrdenTrabajo:
    """Termina la reparación y descuenta el stock en una sola transacción (RN-13/RN-14).

    Permiso: el mecánico asignado o un ADMIN; cualquier otro → `OrdenAjena`
    (403) **antes** de mirar el estado. Luego exige EN_REPARACION (409).
    El chequeo de stock de **todos** los ítems ocurre antes de cualquier
    escritura: si alguno no alcanza, `StockInsuficiente` revierte todo el UoW
    y no queda ningún cambio parcial (stock, movimientos ni historial).

    Args:
        uow: unit of work de la orden (dueño de la transacción).
        orden_id: identificador de la orden a terminar.
        usuario: usuario autenticado que ejecuta la transición.

    Returns:
        La orden recargada en estado TERMINADA.

    Raises:
        OrdenNoEncontrada: si la orden no existe.
        OrdenAjena: si no es ADMIN ni el mecánico asignado.
        TransicionInvalida: si la orden no está EN_REPARACION.
        StockInsuficiente: si algún repuesto no alcanza (rollback total).
    """
    async with uow:
        orden = await uow.ordenes.get_detalle(orden_id)
        if orden is None:
            raise OrdenNoEncontrada(MENSAJE_ORDEN_NO_ENCONTRADA)

        es_admin = "ADMIN" in usuario.roles_vigentes
        if not es_admin and orden.mecanico_id != usuario.id:
            raise OrdenAjena(MENSAJE_ORDEN_AJENA_ACCION)

        if orden.estado != ESTADO_EN_REPARACION:
            raise TransicionInvalida(MENSAJE_TRANSICION_INVALIDA)

        # 1. Chequeo de stock de TODOS los ítems antes de escribir (D5, RN-13).
        for item in orden.items:
            if item.repuesto is None or item.repuesto.stock < item.cantidad:
                raise StockInsuficiente(MENSAJE_STOCK_INSUFICIENTE)

        # 2. Descuento por ítem + movimiento de salida (único punto de stock, RN-14).
        for item in orden.items:
            repuesto = item.repuesto
            await uow.repuestos.update(
                repuesto, {"stock": repuesto.stock - item.cantidad}
            )
            await uow.movimientos.add(
                MovimientoStock(
                    repuesto_id=repuesto.id,
                    orden_id=orden.id,
                    usuario_id=usuario.id,
                    cantidad=item.cantidad,
                    motivo=MOTIVO_MOVIMIENTO_SALIDA,
                )
            )

        # 3. Estado TERMINADA + historial dentro del mismo UoW.
        await uow.ordenes.update(orden, {"estado": ESTADO_TERMINADA})
        await uow.historial.add(
            HistorialEstadoOrden(
                orden_id=orden.id,
                desde_estado=ESTADO_EN_REPARACION,
                hasta_estado=ESTADO_TERMINADA,
                usuario_id=usuario.id,
            )
        )
        return await uow.ordenes.get_detalle(orden.id)


async def cancelar_orden(
    uow: UoWOrdenes,
    orden_id: int,
    usuario: UsuarioAutenticado,
) -> OrdenTrabajo:
    """Cancela una orden PENDIENTE evaluando primero la relación (RN-12).

    Orden de las validaciones (D3): primero la relación del usuario con la
    orden (personal del taller o dueño del vehículo) → `OrdenAjena` (403);
    recién después el estado PENDIENTE → `TransicionInvalida` (409). Así un
    usuario ajeno recibe 403 y nunca 409.

    Args:
        uow: unit of work de la orden (dueño de la transacción).
        orden_id: identificador de la orden a cancelar.
        usuario: usuario autenticado que ejecuta la transición.

    Returns:
        La orden recargada en estado CANCELADA.

    Raises:
        OrdenNoEncontrada: si la orden no existe.
        OrdenAjena: si no es personal ni dueño del vehículo.
        TransicionInvalida: si la orden no está PENDIENTE.
    """
    async with uow:
        orden = await uow.ordenes.get_detalle(orden_id)
        if orden is None:
            raise OrdenNoEncontrada(MENSAJE_ORDEN_NO_ENCONTRADA)

        if not (_es_staff(usuario) or _es_duenio_del_vehiculo(orden, usuario)):
            raise OrdenAjena(MENSAJE_ORDEN_AJENA_ACCION)

        if orden.estado != ESTADO_PENDIENTE:
            raise TransicionInvalida(MENSAJE_TRANSICION_INVALIDA)

        await uow.ordenes.update(orden, {"estado": ESTADO_CANCELADA})
        await uow.historial.add(
            HistorialEstadoOrden(
                orden_id=orden.id,
                desde_estado=ESTADO_PENDIENTE,
                hasta_estado=ESTADO_CANCELADA,
                usuario_id=usuario.id,
            )
        )
        return await uow.ordenes.get_detalle(orden.id)
