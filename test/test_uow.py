"""Unit of Work: una operación = una transacción (spec `data-persistence`, D4).

Cubre los cuatro escenarios del spec: commit al salir sin excepción, rollback con
propagación, sesión que sigue viva después del bloque y atomicidad multi-tabla.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.repository import BaseRepository
from app.core.unit_of_work import UnitOfWork
from app.modules.usuarios.models import AsignacionRol, Usuario


def _usuario(email: str = "laura@taller.test") -> Usuario:
    """Usuario mínimo válido para los tests del UoW."""
    return Usuario(
        email=email,
        nombre="Laura Gómez",
        password_hash="$2b$12$hashDeMentiraParaLosTests",
    )


async def _contar_usuarios(fabrica: async_sessionmaker[AsyncSession]) -> int:
    """Cuenta usuarios desde una sesión ajena al UoW (lo que ve la base)."""
    async with fabrica() as otra_sesion:
        return await BaseRepository(otra_sesion, Usuario).count()


async def test_commit_al_salir_sin_excepcion(
    sesion: AsyncSession, fabrica_pruebas: async_sessionmaker[AsyncSession]
) -> None:
    """Al terminar el bloque sin excepción, todo queda confirmado."""
    async with UnitOfWork(sesion) as uow:
        repositorio = BaseRepository(uow.session, Usuario)
        await repositorio.add(_usuario("a@taller.test"))
        await repositorio.add(_usuario("b@taller.test"))

    assert await _contar_usuarios(fabrica_pruebas) == 2


async def test_excepcion_revierte_todo_y_se_propaga(
    sesion: AsyncSession, fabrica_pruebas: async_sessionmaker[AsyncSession]
) -> None:
    """Una excepción dentro del bloque revierte las escrituras y sigue subiendo."""
    with pytest.raises(RuntimeError, match="falla de negocio"):
        async with UnitOfWork(sesion) as uow:
            repositorio = BaseRepository(uow.session, Usuario)
            await repositorio.add(_usuario("a@taller.test"))
            await repositorio.add(_usuario("b@taller.test"))
            raise RuntimeError("falla de negocio")

    assert await _contar_usuarios(fabrica_pruebas) == 0


async def test_la_sesion_sigue_usable_despues_del_bloque(sesion: AsyncSession) -> None:
    """El UoW no cierra la sesión: queda abierta y los objetos confirmados legibles."""
    async with UnitOfWork(sesion) as uow:
        usuario = await BaseRepository(uow.session, Usuario).add(_usuario())

    assert sesion.is_active, "la sesión debe seguir abierta después del commit"
    # `expire_on_commit=False`: los atributos se leen sin refrescar.
    assert usuario.email == "laura@taller.test"
    assert usuario.id is not None

    # Y sigue sirviendo para nuevas operaciones.
    async with UnitOfWork(sesion) as uow:
        await BaseRepository(uow.session, Usuario).add(_usuario("otro@taller.test"))
    assert await BaseRepository(sesion, Usuario).count() == 2


async def test_la_sesion_sigue_usable_despues_del_rollback(sesion: AsyncSession) -> None:
    """Tras un rollback la sesión también queda utilizable (no se cierra ni queda rota)."""
    with pytest.raises(ValueError, match="corte"):
        async with UnitOfWork(sesion) as uow:
            await BaseRepository(uow.session, Usuario).add(_usuario())
            raise ValueError("corte")

    assert sesion.is_active
    repositorio = BaseRepository(sesion, Usuario)
    assert await repositorio.count() == 0
    await repositorio.add(_usuario("nuevo@taller.test"))
    assert await repositorio.count() == 1


async def test_atomicidad_multi_tabla(
    sesion: AsyncSession, fabrica_pruebas: async_sessionmaker[AsyncSession]
) -> None:
    """Escritura en dos tablas con fallo en la segunda: no queda ninguna de las dos."""
    with pytest.raises(IntegrityError):
        async with UnitOfWork(sesion) as uow:
            usuarios = BaseRepository(uow.session, Usuario)
            usuario = await usuarios.add(_usuario())
            # Rol fuera de catálogo: la base rechaza esta segunda escritura.
            await BaseRepository(uow.session, AsignacionRol).add(
                AsignacionRol(usuario_id=usuario.id, rol="GERENTE")
            )

    async with fabrica_pruebas() as otra_sesion:
        usuarios = BaseRepository(otra_sesion, Usuario)
        asignaciones = BaseRepository(otra_sesion, AsignacionRol)
        assert await usuarios.count() == 0
        assert await asignaciones.count() == 0


async def test_el_uow_expone_la_misma_sesion_que_recibe(sesion: AsyncSession) -> None:
    """El UoW administra la sesión de la petición, no crea una propia (D4)."""
    async with UnitOfWork(sesion) as uow:
        assert uow.session is sesion
