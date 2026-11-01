"""Tests de la garantía de sólo agregado (C-09, RN-15, US-031).

La garantía vive en PostgreSQL: una función y tres disparadores `BEFORE
UPDATE OR DELETE` sobre `historial_estado_orden`, `movimiento_stock` e
`historial_precio_repuesto`, más la FK que cierra el catálogo de estados.

Los tests usan SQL crudo a propósito: lo observable es el error de la base
(mensaje incluido), no lo que el ORM decida emitir. Después de cada error la
transacción queda abortada, así que cada caso hace `rollback()` antes de
volver a consultar.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import EstadoOrden, HistorialEstadoOrden, OrdenTrabajo
from app.modules.repuestos.models import HistorialPrecioRepuesto, MovimientoStock, Repuesto
from app.modules.usuarios.models import Usuario

TABLAS_PROTEGIDAS = (
    "historial_estado_orden",
    "movimiento_stock",
    "historial_precio_repuesto",
)


@pytest.fixture
async def datos_solo_agregado(sesion: AsyncSession) -> dict[str, int]:
    """Filas mínimas y válidas: catálogo, usuario, cliente/vehículo, repuesto, orden e historial."""
    ahora = datetime.now(timezone.utc)

    sesion.add(EstadoOrden(codigo="PENDIENTE", descripcion="Pendiente", posicion=1, es_final=False))
    await sesion.flush()

    usuario = Usuario(
        email="solo-agregado@example.com",
        nombre="Mecánico de prueba",
        password_hash="hash-ficticio",
    )
    cliente = Cliente(
        usuario_id=None,
        nombre="Cliente de prueba",
        documento="DOC-SA-001",
        telefono="555-0100",
    )
    repuesto = Repuesto(
        codigo="SA-REP-001",
        descripcion="Repuesto de prueba",
        precio=Decimal("10.00"),
        stock=5,
    )
    sesion.add_all([usuario, cliente, repuesto])
    await sesion.flush()

    vehiculo = Vehiculo(
        cliente_id=cliente.id,
        patente="SA001AA",
        marca="Marca",
        modelo="Modelo",
        anio=2020,
    )
    sesion.add(vehiculo)
    await sesion.flush()

    orden = OrdenTrabajo(
        vehiculo_id=vehiculo.id,
        mecanico_id=None,
        estado="PENDIENTE",
        falla="Falla de prueba",
        creada_en=ahora,
        total=Decimal("0.00"),
    )
    sesion.add(orden)
    await sesion.flush()

    historial = HistorialEstadoOrden(
        orden_id=orden.id,
        desde_estado=None,
        hasta_estado="PENDIENTE",
        usuario_id=None,
        cuando=ahora,
    )
    movimiento = MovimientoStock(
        repuesto_id=repuesto.id,
        orden_id=None,
        usuario_id=None,
        cantidad=5,
        motivo="Stock inicial",
        cuando=ahora,
    )
    precio = HistorialPrecioRepuesto(
        repuesto_id=repuesto.id,
        usuario_id=None,
        precio_anterior=Decimal("8.00"),
        precio_nuevo=Decimal("10.00"),
        cuando=ahora,
    )
    sesion.add_all([historial, movimiento, precio])
    await sesion.commit()

    return {
        "usuario_id": usuario.id,
        "cliente_id": cliente.id,
        "vehiculo_id": vehiculo.id,
        "repuesto_id": repuesto.id,
        "orden_id": orden.id,
        "historial_id": historial.id,
        "movimiento_id": movimiento.id,
        "precio_id": precio.id,
    }


async def _contar(sesion: AsyncSession, tabla: str) -> int:
    """Cantidad de filas de una tabla protegida (tras hacer rollback del error)."""
    resultado = await sesion.execute(text(f"SELECT count(*) FROM {tabla}"))
    return int(resultado.scalar_one())


@pytest.mark.parametrize("tabla", TABLAS_PROTEGIDAS)
async def test_update_rechazado_por_el_disparador(
    sesion: AsyncSession,
    datos_solo_agregado: dict[str, int],
    tabla: str,
) -> None:
    """UPDATE sobre cualquiera de las tres tablas falla con el error del disparador."""
    filas_antes = await _contar(sesion, tabla)

    with pytest.raises(DBAPIError) as excinfo:
        await sesion.execute(text(f"UPDATE {tabla} SET cuando = cuando WHERE TRUE"))
        await sesion.flush()

    await sesion.rollback()

    assert tabla in str(excinfo.value), (
        f"el error debería identificar la tabla protegida: {excinfo.value!r}"
    )
    assert "sólo agregado" in str(excinfo.value).lower() or "solo agregado" in str(
        excinfo.value
    ).lower(), f"el error debería explicar la regla: {excinfo.value!r}"
    assert await _contar(sesion, tabla) == filas_antes


@pytest.mark.parametrize("tabla", TABLAS_PROTEGIDAS)
async def test_delete_rechazado_por_el_disparador(
    sesion: AsyncSession,
    datos_solo_agregado: dict[str, int],
    tabla: str,
) -> None:
    """DELETE sobre cualquiera de las tres tablas falla y no borra ninguna fila."""
    filas_antes = await _contar(sesion, tabla)
    assert filas_antes > 0

    with pytest.raises(DBAPIError) as excinfo:
        await sesion.execute(text(f"DELETE FROM {tabla} WHERE TRUE"))
        await sesion.flush()

    await sesion.rollback()

    assert tabla in str(excinfo.value), (
        f"el error debería identificar la tabla protegida: {excinfo.value!r}"
    )
    assert await _contar(sesion, tabla) == filas_antes


async def test_insert_sigue_permitido_en_historial_estado_orden(
    sesion: AsyncSession,
    datos_solo_agregado: dict[str, int],
) -> None:
    """La tabla de historial de estados sigue aceptando filas nuevas (sólo agregado)."""
    sesion.add(
        HistorialEstadoOrden(
            orden_id=datos_solo_agregado["orden_id"],
            desde_estado="PENDIENTE",
            hasta_estado="PENDIENTE",
            usuario_id=datos_solo_agregado["usuario_id"],
            cuando=datetime.now(timezone.utc),
        )
    )
    await sesion.commit()

    assert await _contar(sesion, "historial_estado_orden") == 2


async def test_insert_sigue_permitido_en_movimiento_stock(
    sesion: AsyncSession,
    datos_solo_agregado: dict[str, int],
) -> None:
    """La tabla de movimientos de stock sigue aceptando filas nuevas."""
    sesion.add(
        MovimientoStock(
            repuesto_id=datos_solo_agregado["repuesto_id"],
            orden_id=None,
            usuario_id=datos_solo_agregado["usuario_id"],
            cantidad=1,
            motivo="Reposición",
            cuando=datetime.now(timezone.utc),
        )
    )
    await sesion.commit()

    assert await _contar(sesion, "movimiento_stock") == 2


async def test_insert_sigue_permitido_en_historial_precio_repuesto(
    sesion: AsyncSession,
    datos_solo_agregado: dict[str, int],
) -> None:
    """La tabla de historial de precios sigue aceptando filas nuevas."""
    sesion.add(
        HistorialPrecioRepuesto(
            repuesto_id=datos_solo_agregado["repuesto_id"],
            usuario_id=datos_solo_agregado["usuario_id"],
            precio_anterior=Decimal("10.00"),
            precio_nuevo=Decimal("12.00"),
            cuando=datetime.now(timezone.utc),
        )
    )
    await sesion.commit()

    assert await _contar(sesion, "historial_precio_repuesto") == 2


async def test_estado_fuera_del_catalogo_rechazado_por_la_fk(
    sesion: AsyncSession,
    datos_solo_agregado: dict[str, int],
) -> None:
    """Una orden con un estado inexistente la rechaza la FK hacia estado_orden (RN-19)."""
    sesion.add(
        OrdenTrabajo(
            vehiculo_id=datos_solo_agregado["vehiculo_id"],
            mecanico_id=None,
            estado="INEXISTENTE",
            falla="Estado fuera del catálogo",
            creada_en=datetime.now(timezone.utc),
            total=Decimal("0.00"),
        )
    )

    with pytest.raises(IntegrityError) as excinfo:
        await sesion.commit()

    await sesion.rollback()

    assert "estado_orden" in str(excinfo.value) or "foreign key" in str(excinfo.value).lower()
    assert await _contar(sesion, "orden_trabajo") == 1
