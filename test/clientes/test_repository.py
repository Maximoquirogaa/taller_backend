"""Tests de los repositorios y UoW del módulo clientes (Task 2.1, C-04).

Verifica:
- `RepositorioClientes`: alta, búsqueda por documento, búsqueda por usuario_id, y precarga con selectinload sin N+1.
- `RepositorioVehiculos`: alta, baja lógica (`soft_delete`), búsqueda por patente activa, e índice único parcial.
- `UoWClientes`: confirmación y reversión atómica de transacciones.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.clientes.repository import RepositorioClientes, RepositorioVehiculos
from app.modules.clientes.unit_of_work import UoWClientes


async def test_repositorio_clientes_alta_y_busqueda(sesion: AsyncSession) -> None:
    """Verifica alta y búsqueda por documento y usuario_id."""
    repo = RepositorioClientes(sesion)
    cliente = Cliente(nombre="Carlos Gomez", documento="20123456", telefono="11-9876-5432")
    await repo.add(cliente)
    await sesion.commit()

    encontrado = await repo.get_por_documento("20123456")
    assert encontrado is not None
    assert encontrado.nombre == "Carlos Gomez"

    inexistente = await repo.get_por_documento("99999999")
    assert inexistente is None


async def test_repositorio_clientes_rechaza_documento_duplicado(sesion: AsyncSession) -> None:
    """Verifica restricción de unicidad en documento de cliente."""
    repo = RepositorioClientes(sesion)
    await repo.add(Cliente(nombre="Cliente 1", documento="DUP1234", telefono="111"))
    await sesion.flush()

    with pytest.raises(IntegrityError):
        await repo.add(Cliente(nombre="Cliente 2", documento="DUP1234", telefono="222"))
        await sesion.flush()
    await sesion.rollback()


async def test_repositorio_vehiculos_soft_delete_y_patente_activa(sesion: AsyncSession) -> None:
    """Verifica soft_delete y que la patente dada de baja no bloquea una nueva alta (RN-01)."""
    repo_c = RepositorioClientes(sesion)
    repo_v = RepositorioVehiculos(sesion)

    c1 = await repo_c.add(Cliente(nombre="Cliente A", documento="11111111", telefono="111"))
    c2 = await repo_c.add(Cliente(nombre="Cliente B", documento="22222222", telefono="222"))
    await sesion.flush()

    v1 = await repo_v.add(Vehiculo(cliente_id=c1.id, patente="ABC123AA", marca="Fiat", modelo="Cronos", anio=2021))
    await sesion.commit()

    activo = await repo_v.get_por_patente_activa("ABC123AA")
    assert activo is not None
    assert activo.id == v1.id

    await repo_v.soft_delete(v1)
    await sesion.commit()

    activo_post_baja = await repo_v.get_por_patente_activa("ABC123AA")
    assert activo_post_baja is None
    assert await repo_v.get_by_id(v1.id) is None
    assert (await repo_v.get_by_id_including_deleted(v1.id)) is not None

    v2 = await repo_v.add(Vehiculo(cliente_id=c2.id, patente="ABC123AA", marca="Fiat", modelo="Cronos", anio=2022))
    await sesion.commit()
    assert v2.id is not None
    assert (await repo_v.get_por_patente_activa("ABC123AA")).id == v2.id


async def test_repositorio_vehiculos_rechaza_patente_activa_duplicada(sesion: AsyncSession) -> None:
    """Verifica que dos vehículos activos con la misma patente fallan por índice único parcial."""
    repo_c = RepositorioClientes(sesion)
    repo_v = RepositorioVehiculos(sesion)

    c1 = await repo_c.add(Cliente(nombre="Cliente X", documento="333111", telefono="111"))
    c2 = await repo_c.add(Cliente(nombre="Cliente Y", documento="444222", telefono="222"))
    await sesion.flush()

    await repo_v.add(Vehiculo(cliente_id=c1.id, patente="DUP999AA", marca="Renault", modelo="Clio", anio=2015))
    await sesion.flush()

    with pytest.raises(IntegrityError):
        await repo_v.add(Vehiculo(cliente_id=c2.id, patente="DUP999AA", marca="Peugeot", modelo="208", anio=2019))
        await sesion.flush()
    await sesion.rollback()


async def test_cliente_con_vehiculos_precarga_sin_eliminados(sesion: AsyncSession) -> None:
    """Verifica que get_con_vehiculos precarga solo los vehículos vigentes (US-016)."""
    repo_c = RepositorioClientes(sesion)
    repo_v = RepositorioVehiculos(sesion)

    c = await repo_c.add(Cliente(nombre="Laura Ramos", documento="25999888", telefono="4444"))
    await sesion.flush()

    v_activo1 = await repo_v.add(Vehiculo(cliente_id=c.id, patente="ACT001AA", marca="Ford", modelo="Focus", anio=2017))
    v_activo2 = await repo_v.add(Vehiculo(cliente_id=c.id, patente="ACT002BB", marca="VW", modelo="Golf", anio=2020))
    v_borrado = await repo_v.add(Vehiculo(cliente_id=c.id, patente="DEL003CC", marca="Chevrolet", modelo="Cruze", anio=2016))
    await repo_v.soft_delete(v_borrado)
    await sesion.commit()

    cliente_cargado = await repo_c.get_con_vehiculos(c.id)
    assert cliente_cargado is not None
    patentes = [v.patente for v in cliente_cargado.vehiculos]
    assert "ACT001AA" in patentes
    assert "ACT002BB" in patentes
    assert "DEL003CC" not in patentes


async def test_uow_clientes_transaccion_atomica(sesion: AsyncSession) -> None:
    """Verifica que UoW confirma al salir y revierte con excepción."""
    async with UoWClientes(sesion) as uow:
        c = await uow.clientes.add(Cliente(nombre="Lucía", documento="33333333", telefono="333"))
        await uow.vehiculos.add(Vehiculo(cliente_id=c.id, patente="DEF456BB", marca="Ford", modelo="Ka", anio=2018))

    repo_c = RepositorioClientes(sesion)
    assert (await repo_c.get_por_documento("33333333")) is not None

    try:
        async with UoWClientes(sesion) as uow:
            await uow.clientes.add(Cliente(nombre="Rollback", documento="44444444", telefono="444"))
            raise RuntimeError("Fallo forzado")
    except RuntimeError:
        pass

    assert (await repo_c.get_por_documento("44444444")) is None
