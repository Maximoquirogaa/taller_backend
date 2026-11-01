"""Lógica de negocio del módulo clientes (capa Service).

Implementa las operaciones sobre clientes y vehículos garantizando:
- Unicidad de documento (RN-01, 409).
- Unicidad de patente activa (RN-01, 409) con normalización en mayúsculas.
- Punto de extensión para verificación de órdenes abiertas en baja de vehículos (RN-16).
- Aislamiento en `/mis-vehiculos` (RN-17).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.clientes.schemas import EntradaCrearCliente, EntradaCrearVehiculo
from app.modules.clientes.unit_of_work import UoWClientes

MENSAJE_DOCUMENTO_DUPLICADO = "Ya existe un cliente registrado con ese documento."
MENSAJE_PATENTE_DUPLICADA = "Ya existe un vehículo activo registrado con esa patente."
MENSAJE_CLIENTE_NO_ENCONTRADO = "El cliente solicitado no existe."
MENSAJE_VEHICULO_NO_ENCONTRADO = "El vehículo solicitado no existe o fue dado de baja."
MENSAJE_VEHICULO_CON_ORDENES = "No se puede dar de baja un vehículo con órdenes de trabajo abiertas."


class DocumentoDuplicado(Exception):
    """El documento ya pertenece a un cliente del taller (RN-01, US-012)."""


class PatenteDuplicada(Exception):
    """La patente ya pertenece a un vehículo activo (RN-01, US-013)."""


class ClienteNoEncontrado(Exception):
    """El cliente no existe en la base de datos."""


class VehiculoNoEncontrado(Exception):
    """El vehículo no existe o ya fue dado de baja lógica."""


class VehiculoConOrdenesAbiertas(Exception):
    """El vehículo tiene órdenes de trabajo en estado no final (RN-16, US-014)."""


async def verificar_ordenes_abiertas(session: AsyncSession, vehiculo_id: int) -> bool:
    """Indica si el vehículo tiene órdenes en un estado no final (RN-16).

    Consulta las órdenes del vehículo unidas al catálogo `estado_orden` y
    considera "abierta" toda orden cuyo estado tenga `es_final = False`. Se
    apoya en el catálogo y no en una lista de códigos hardcodeada, así agregar
    estados nuevos no exige tocar la baja de vehículos.

    Args:
        session: sesión de la petición (dueña de la transacción del UoW).
        vehiculo_id: identificador del vehículo a dar de baja.

    Returns:
        `True` si existe al menos una orden no final para el vehículo.
    """
    from app.modules.ordenes.models import EstadoOrden, OrdenTrabajo

    consulta = (
        select(OrdenTrabajo.id)
        .join(EstadoOrden, OrdenTrabajo.estado == EstadoOrden.codigo)
        .where(
            OrdenTrabajo.vehiculo_id == vehiculo_id,
            EstadoOrden.es_final.is_(False),
        )
        .limit(1)
    )
    return (await session.execute(consulta)).scalar() is not None


async def crear_cliente(uow: UoWClientes, datos: EntradaCrearCliente) -> Cliente:
    """Crea una ficha de cliente sin usuario asociado (US-012, RN-01)."""
    async with uow:
        existente = await uow.clientes.get_por_documento(datos.documento)
        if existente is not None:
            raise DocumentoDuplicado(MENSAJE_DOCUMENTO_DUPLICADO)

        cliente = Cliente(
            nombre=datos.nombre,
            documento=datos.documento,
            telefono=datos.telefono,
        )
        return await uow.clientes.add(cliente)


async def obtener_cliente_detalle(uow: UoWClientes, cliente_id: int) -> Cliente:
    """Obtiene la ficha de un cliente con sus vehículos precargados (US-016)."""
    async with uow:
        cliente = await uow.clientes.get_con_vehiculos(cliente_id)
        if cliente is None:
            raise ClienteNoEncontrado(MENSAJE_CLIENTE_NO_ENCONTRADO)
        return cliente


async def crear_vehiculo(
    uow: UoWClientes, cliente_id: int, datos: EntradaCrearVehiculo
) -> Vehiculo:
    """Registra un vehículo asociado a un cliente existente (US-013, RN-01)."""
    async with uow:
        cliente = await uow.clientes.get_by_id(cliente_id)
        if cliente is None:
            raise ClienteNoEncontrado(MENSAJE_CLIENTE_NO_ENCONTRADO)

        patente_normalizada = datos.patente.strip().upper()
        existente = await uow.vehiculos.get_por_patente_activa(patente_normalizada)
        if existente is not None:
            raise PatenteDuplicada(MENSAJE_PATENTE_DUPLICADA)

        vehiculo = Vehiculo(
            cliente_id=cliente_id,
            patente=patente_normalizada,
            marca=datos.marca,
            modelo=datos.modelo,
            anio=datos.anio,
        )
        return await uow.vehiculos.add(vehiculo)


async def dar_baja_vehiculo(uow: UoWClientes, vehiculo_id: int) -> None:
    """Realiza la baja lógica de un vehículo si no tiene órdenes abiertas (US-014, RN-16)."""
    async with uow:
        vehiculo = await uow.vehiculos.get_by_id(vehiculo_id)
        if vehiculo is None:
            raise VehiculoNoEncontrado(MENSAJE_VEHICULO_NO_ENCONTRADO)

        if await verificar_ordenes_abiertas(uow.session, vehiculo_id):
            raise VehiculoConOrdenesAbiertas(MENSAJE_VEHICULO_CON_ORDENES)

        await uow.vehiculos.soft_delete(vehiculo)


async def listar_mis_vehiculos(
    uow: UoWClientes, usuario_id: int
) -> Sequence[Vehiculo]:
    """Lista exclusivamente los vehículos del cliente vinculado al usuario actual (US-015, RN-17)."""
    async with uow:
        cliente = await uow.clientes.get_por_usuario_id(usuario_id)
        if cliente is None:
            return []
        return await uow.vehiculos.get_por_cliente(cliente.id)
