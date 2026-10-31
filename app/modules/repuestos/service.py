"""Lógica de negocio del módulo repuestos (capa Service).

Implementa las operaciones sobre el catálogo y auditoría de inventario:
- Unicidad de código activo (RN-01, 409).
- Modificaciones de stock exclusivamente vía movimientos (RN-14).
- Registro transaccional en historial al modificar precio (RN-20).
- Baja lógica con preservación de datos (RN-16).
- Búsqueda segura con parámetros ligados y paginación (US-017, RN-18).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.paginacion import PaginaDe, ParametrosPagina, construir_pagina
from app.modules.repuestos.models import (
    HistorialPrecioRepuesto,
    MovimientoStock,
    Repuesto,
)
from app.modules.repuestos.schemas import (
    EntradaActualizarRepuesto,
    EntradaCrearRepuesto,
    EntradaReponerStock,
)
from app.modules.repuestos.unit_of_work import UoWRepuestos

MENSAJE_CODIGO_DUPLICADO = "Ya existe un repuesto activo registrado con ese código."
MENSAJE_REPUESTO_NO_ENCONTRADO = "El repuesto solicitado no existe o fue dado de baja."
MENSAJE_PRECIO_INVALIDO = "El precio nuevo debe ser mayor al precio anterior."


class CodigoRepuestoDuplicado(Exception):
    """El código ya pertenece a un repuesto activo (RN-01, US-018)."""


class RepuestoNoEncontrado(Exception):
    """El repuesto no existe o ya fue dado de baja lógica."""


class PrecioInvalido(Exception):
    """El nuevo precio no supera al precio anterior (RN-20, US-019)."""


async def crear_repuesto(
    uow: UoWRepuestos,
    datos: EntradaCrearRepuesto,
    usuario_id: int | None = None,
) -> Repuesto:
    """Registra una nueva pieza en el catálogo y genera el movimiento de stock inicial (RN-14)."""
    codigo_norm = datos.codigo.strip().upper()
    async with uow:
        existente = await uow.repuestos.get_por_codigo_activo(codigo_norm)
        if existente is not None:
            raise CodigoRepuestoDuplicado(MENSAJE_CODIGO_DUPLICADO)

        repuesto = Repuesto(
            codigo=codigo_norm,
            descripcion=datos.descripcion.strip(),
            precio=datos.precio,
            stock=datos.stock_inicial,
        )
        await uow.repuestos.add(repuesto)

        # Si hay stock inicial > 0, se anota el movimiento de apertura en el mismo UoW
        if datos.stock_inicial > 0:
            movimiento = MovimientoStock(
                repuesto_id=repuesto.id,  # type: ignore[arg-type]
                cantidad=datos.stock_inicial,
                motivo="Stock inicial",
                usuario_id=usuario_id,
            )
            await uow.movimientos.add(movimiento)

        return repuesto


async def actualizar_repuesto(
    uow: UoWRepuestos,
    repuesto_id: int,
    datos: EntradaActualizarRepuesto,
    usuario_id: int | None = None,
) -> Repuesto:
    """Actualiza descripción o precio. Si el precio cambia, registra historial (RN-20)."""
    async with uow:
        repuesto = await uow.repuestos.get_by_id(repuesto_id)
        if repuesto is None:
            raise RepuestoNoEncontrado(MENSAJE_REPUESTO_NO_ENCONTRADO)

        campos = datos.model_dump(exclude_unset=True)

        # Manejo de cambio de precio
        if "precio" in campos and campos["precio"] is not None:
            nuevo_precio = campos["precio"]
            if nuevo_precio <= repuesto.precio:
                raise PrecioInvalido(MENSAJE_PRECIO_INVALIDO)

            historial = HistorialPrecioRepuesto(
                repuesto_id=repuesto.id,  # type: ignore[arg-type]
                usuario_id=usuario_id,
                precio_anterior=repuesto.precio,
                precio_nuevo=nuevo_precio,
            )
            await uow.historial_precios.add(historial)
            repuesto.precio = nuevo_precio

        if "descripcion" in campos and campos["descripcion"] is not None:
            repuesto.descripcion = campos["descripcion"].strip()

        await uow.repuestos.update(repuesto, {})
        return repuesto


async def reponer_stock(
    uow: UoWRepuestos,
    repuesto_id: int,
    datos: EntradaReponerStock,
    usuario_id: int | None = None,
) -> Repuesto:
    """Suma unidades al stock e inserta el movimiento correspondiente en un solo UoW (RN-14)."""
    async with uow:
        repuesto = await uow.repuestos.get_by_id(repuesto_id)
        if repuesto is None:
            raise RepuestoNoEncontrado(MENSAJE_REPUESTO_NO_ENCONTRADO)

        repuesto.stock += datos.cantidad

        movimiento = MovimientoStock(
            repuesto_id=repuesto.id,  # type: ignore[arg-type]
            cantidad=datos.cantidad,
            motivo=datos.motivo.strip(),
            usuario_id=usuario_id,
        )
        await uow.movimientos.add(movimiento)
        await uow.repuestos.update(repuesto, {})
        return repuesto


async def dar_de_baja_repuesto(uow: UoWRepuestos, repuesto_id: int) -> None:
    """Ejecuta la baja lógica de un repuesto activo (RN-16)."""
    async with uow:
        repuesto = await uow.repuestos.get_by_id(repuesto_id)
        if repuesto is None:
            raise RepuestoNoEncontrado(MENSAJE_REPUESTO_NO_ENCONTRADO)

        await uow.repuestos.soft_delete(repuesto)


async def obtener_repuesto(uow: UoWRepuestos, repuesto_id: int) -> Repuesto:
    """Recupera un repuesto activo por su identificador primario."""
    async with uow:
        repuesto = await uow.repuestos.get_by_id(repuesto_id)
        if repuesto is None:
            raise RepuestoNoEncontrado(MENSAJE_REPUESTO_NO_ENCONTRADO)
        return repuesto


async def listar_movimientos(
    uow: UoWRepuestos,
    repuesto_id: int,
) -> Sequence[MovimientoStock]:
    """Lista todos los movimientos de stock del repuesto indicado."""
    async with uow:
        repuesto = await uow.repuestos.get_by_id(repuesto_id)
        if repuesto is None:
            raise RepuestoNoEncontrado(MENSAJE_REPUESTO_NO_ENCONTRADO)
        return await uow.movimientos.get_por_repuesto(repuesto_id)


async def listar_historial_precios(
    uow: UoWRepuestos,
    repuesto_id: int,
) -> Sequence[HistorialPrecioRepuesto]:
    """Lista el historial de variaciones de precio del repuesto indicado."""
    async with uow:
        repuesto = await uow.repuestos.get_by_id(repuesto_id)
        if repuesto is None:
            raise RepuestoNoEncontrado(MENSAJE_REPUESTO_NO_ENCONTRADO)
        return await uow.historial_precios.get_por_repuesto(repuesto_id)


async def buscar_repuestos_paginado(
    uow: UoWRepuestos,
    q: str | None = None,
    parametros: ParametrosPagina | None = None,
) -> PaginaDe[Repuesto]:
    """Consulta paginada del catálogo de repuestos con filtro de texto seguro (RN-18)."""
    if parametros is None:
        parametros = ParametrosPagina()
    async with uow:
        items, total = await uow.repuestos.buscar_catalogo(
            q=q,
            offset=parametros.desplazamiento,
            limit=parametros.size,
        )
        return construir_pagina(
            list(items),
            total=total,
            parametros=parametros,
        )
