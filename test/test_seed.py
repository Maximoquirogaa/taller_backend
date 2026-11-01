"""Tests de la carga inicial del taller (C-10, spec `seed-inicial`).

El seed se ejecuta contra `taller_test` con la fábrica de la suite: un único
`TRUNCATE ... RESTART IDENTITY CASCADE` y todos los `INSERT` dentro de una sola
transacción. Los tests verifican el estado que queda en la base y las garantías
del script (idempotencia, credenciales, stock como movimiento e historiales);
la API no se toca acá — eso lo cubre la suite de órdenes.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import SQLModel

from app.core.security import verificar_password
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import (
    EstadoOrden,
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)
from app.modules.repuestos.models import (
    HistorialPrecioRepuesto,
    MovimientoStock,
    Repuesto,
)
from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, Usuario
from seed import (
    CODIGO_BUJIA,
    CODIGO_FILTRO_ACEITE,
    CONTRASENA_FICTICIA,
    EMAIL_ADMIN,
    EMAIL_MECANICO,
    EMAIL_USUARIO_NUEVO,
    PATENTE_ORDEN_EN_REPARACION,
    PATENTE_ORDEN_PENDIENTE,
    TABLAS_INICIALES,
    cargar_datos_iniciales,
)

ModeloDeTabla = type[SQLModel]

RAIZ_DEL_PROYECTO = Path(__file__).resolve().parents[1]


async def _contar(sesion: AsyncSession, modelo: ModeloDeTabla) -> int:
    """Cantidad de filas de una tabla, por su modelo."""
    resultado = await sesion.execute(select(func.count()).select_from(modelo))
    return int(resultado.scalar_one())


async def _conteos(fabrica: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Conteo de las 13 tablas de la carga (mismo orden que el TRUNCATE)."""
    conteos: dict[str, int] = {}
    async with fabrica() as sesion:
        for tabla in TABLAS_INICIALES:
            resultado = await sesion.execute(text(f'SELECT count(*) FROM "{tabla}"'))
            conteos[tabla] = int(resultado.scalar_one())
    return conteos


@pytest.fixture
async def semilla(
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> None:
    """Deja la base de pruebas en el estado inicial antes de cada test."""
    await cargar_datos_iniciales(fabrica_pruebas)


async def test_la_carga_deja_el_estado_inicial_completo(
    semilla: None,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> None:
    """Catálogo, usuarios/roles, clientes, vehículos, repuestos y órdenes esperados."""
    async with fabrica_pruebas() as sesion:
        estados = (
            await sesion.execute(select(EstadoOrden).order_by(EstadoOrden.posicion))
        ).scalars().all()
        assert [estado.codigo for estado in estados] == [
            "PENDIENTE",
            "EN_REPARACION",
            "TERMINADA",
            "CANCELADA",
        ]
        assert [estado.es_final for estado in estados] == [False, False, True, True]

        assert await _contar(sesion, Usuario) == 7
        assert await _contar(sesion, AsignacionRol) == 7
        assert await _contar(sesion, Cliente) == 2
        assert await _contar(sesion, Vehiculo) == 3
        assert await _contar(sesion, Repuesto) == 4
        assert await _contar(sesion, MovimientoStock) == 4
        assert await _contar(sesion, OrdenTrabajo) == 2
        assert await _contar(sesion, ItemOrden) == 2
        assert await _contar(sesion, HistorialEstadoOrden) == 3
        assert await _contar(sesion, HistorialPrecioRepuesto) == 1
        assert await _contar(sesion, EventoSeguridad) == 1

        # Todas las asignaciones de rol quedan vigentes (sin revocar ni vencer).
        vigentes = (
            await sesion.execute(
                select(AsignacionRol).where(AsignacionRol.revocada_en.is_(None))
            )
        ).scalars().all()
        assert len(vigentes) == 7
        assert all(asignacion.vence_en is None for asignacion in vigentes)

        evento = (await sesion.execute(select(EventoSeguridad))).scalars().one()
        assert evento.actor == "SISTEMA"
        assert evento.accion == "Carga de los datos iniciales"


async def test_orden_pendiente_nace_sin_mecanico_y_con_historial_inicial(
    semilla: None,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> None:
    """La orden PENDIENTE es de Laura, no tiene mecánico y su historial es nulo → PENDIENTE."""
    async with fabrica_pruebas() as sesion:
        orden = (
            await sesion.execute(
                select(OrdenTrabajo).where(OrdenTrabajo.estado == "PENDIENTE")
            )
        ).scalars().one()
        vehiculo = await sesion.get(Vehiculo, orden.vehiculo_id)

        assert vehiculo is not None
        assert vehiculo.patente == PATENTE_ORDEN_PENDIENTE
        assert orden.mecanico_id is None
        assert orden.total == Decimal("8500.00")

        items = (
            await sesion.execute(
                select(ItemOrden).where(ItemOrden.orden_id == orden.id)
            )
        ).scalars().all()
        assert len(items) == 1
        assert items[0].cantidad == 1
        assert items[0].precio_unitario == Decimal("8500.00")

        historial = (
            await sesion.execute(
                select(HistorialEstadoOrden)
                .where(HistorialEstadoOrden.orden_id == orden.id)
                .order_by(HistorialEstadoOrden.id)
            )
        ).scalars().all()
        assert len(historial) == 1
        assert historial[0].desde_estado is None
        assert historial[0].hasta_estado == "PENDIENTE"
        assert historial[0].usuario_id is None


async def test_orden_en_reparacion_tiene_mecanico_y_dos_lineas_de_historial(
    semilla: None,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> None:
    """La orden EN_REPARACION es de Jorge, la toma `mecanico@` y deja dos líneas."""
    async with fabrica_pruebas() as sesion:
        orden = (
            await sesion.execute(
                select(OrdenTrabajo).where(OrdenTrabajo.estado == "EN_REPARACION")
            )
        ).scalars().one()
        vehiculo = await sesion.get(Vehiculo, orden.vehiculo_id)
        mecanico = await sesion.get(Usuario, orden.mecanico_id)

        assert vehiculo is not None
        assert vehiculo.patente == PATENTE_ORDEN_EN_REPARACION
        assert mecanico is not None
        assert mecanico.email == EMAIL_MECANICO
        assert orden.total == Decimal("14000.00")

        historial = (
            await sesion.execute(
                select(HistorialEstadoOrden)
                .where(HistorialEstadoOrden.orden_id == orden.id)
                .order_by(HistorialEstadoOrden.id)
            )
        ).scalars().all()
        assert [(linea.desde_estado, linea.hasta_estado) for linea in historial] == [
            (None, "PENDIENTE"),
            ("PENDIENTE", "EN_REPARACION"),
        ]
        assert historial[1].usuario_id == mecanico.id


async def test_la_carga_es_idempotente(
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> None:
    """Dos ejecuciones seguidas dejan los mismos conteos y los mismos ids."""
    await cargar_datos_iniciales(fabrica_pruebas)
    primeros = await _conteos(fabrica_pruebas)

    await cargar_datos_iniciales(fabrica_pruebas)
    segundos = await _conteos(fabrica_pruebas)

    assert segundos == primeros
    async with fabrica_pruebas() as sesion:
        admin = (
            await sesion.execute(select(Usuario).where(Usuario.email == EMAIL_ADMIN))
        ).scalars().one()
        assert admin.id == 1  # RESTART IDENTITY: ids predecibles en cada carga


async def test_credenciales_ficticias_son_utilizables(
    semilla: None,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> None:
    """Cada usuario verifica la contraseña ficticia y `nuevo@` debe cambiarla."""
    async with fabrica_pruebas() as sesion:
        usuarios = (await sesion.execute(select(Usuario))).scalars().all()
        assert len(usuarios) == 7
        for usuario in usuarios:
            assert await verificar_password(CONTRASENA_FICTICIA, usuario.password_hash), (
                f"la contraseña ficticia no verifica para {usuario.email}"
            )

        nuevo = (
            await sesion.execute(
                select(Usuario).where(Usuario.email == EMAIL_USUARIO_NUEVO)
            )
        ).scalars().one()
        assert nuevo.debe_cambiar_password is True

        rol_nuevo = (
            await sesion.execute(
                select(AsignacionRol).where(
                    AsignacionRol.usuario_id == nuevo.id,
                    AsignacionRol.revocada_en.is_(None),
                )
            )
        ).scalars().one()
        assert rol_nuevo.rol == "MECANICO"


def test_la_contrasena_ficticia_no_esta_en_la_configuracion_versionada() -> None:
    """La contraseña del seed vive sólo en `seed.py`, no en `env.example`."""
    ejemplo = (RAIZ_DEL_PROYECTO / "env.example").read_text(encoding="utf-8")
    assert CONTRASENA_FICTICIA not in ejemplo


async def test_el_stock_inicial_esta_respaldado_por_movimientos(
    semilla: None,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> None:
    """Por cada repuesto: `stock` == suma de sus movimientos y hay un alta inicial."""
    async with fabrica_pruebas() as sesion:
        repuestos = (await sesion.execute(select(Repuesto))).scalars().all()
        assert len(repuestos) == 4
        for repuesto in repuestos:
            movimientos = (
                await sesion.execute(
                    select(MovimientoStock).where(
                        MovimientoStock.repuesto_id == repuesto.id
                    )
                )
            ).scalars().all()
            assert sum(movimiento.cantidad for movimiento in movimientos) == repuesto.stock
            assert any(movimiento.motivo == "Stock inicial" for movimiento in movimientos)

        filtro = (
            await sesion.execute(
                select(Repuesto).where(Repuesto.codigo == CODIGO_FILTRO_ACEITE)
            )
        ).scalars().one()
        assert filtro.precio == Decimal("8500.00")
        assert filtro.stock == 10


async def test_la_orden_en_reparacion_prepara_el_caso_de_stock_insuficiente(
    semilla: None,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> None:
    """La orden EN_REPARACION pide 4 bujías y el stock es 2 (caso de la consigna)."""
    async with fabrica_pruebas() as sesion:
        orden = (
            await sesion.execute(
                select(OrdenTrabajo).where(OrdenTrabajo.estado == "EN_REPARACION")
            )
        ).scalars().one()
        item = (
            await sesion.execute(select(ItemOrden).where(ItemOrden.orden_id == orden.id))
        ).scalars().one()
        bujia = (
            await sesion.execute(select(Repuesto).where(Repuesto.codigo == CODIGO_BUJIA))
        ).scalars().one()

        assert item.repuesto_id == bujia.id
        assert item.cantidad == 4
        assert bujia.stock == 2
        assert item.cantidad > bujia.stock


async def test_historial_de_precio_del_filtro(
    semilla: None,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> None:
    """El filtro registra 8000 → 8500 atribuido a un ADMIN y queda en 8500."""
    async with fabrica_pruebas() as sesion:
        filtro = (
            await sesion.execute(
                select(Repuesto).where(Repuesto.codigo == CODIGO_FILTRO_ACEITE)
            )
        ).scalars().one()
        historial = (
            await sesion.execute(
                select(HistorialPrecioRepuesto).where(
                    HistorialPrecioRepuesto.repuesto_id == filtro.id
                )
            )
        ).scalars().one()
        autor = await sesion.get(Usuario, historial.usuario_id)

        assert historial.precio_anterior == Decimal("8000.00")
        assert historial.precio_nuevo == Decimal("8500.00")
        assert filtro.precio == historial.precio_nuevo
        assert autor is not None
        assert autor.email == EMAIL_ADMIN
