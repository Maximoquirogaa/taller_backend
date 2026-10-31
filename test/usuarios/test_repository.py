"""Tests de repositorios y UoW del módulo usuarios (tasks 2.1 y 2.3, C-06).

Verifica:
- `RepositorioRoles`: `get_abierta` (solo `revocada_en IS NULL`), `revocar` que
  escribe la marca sin borrar la fila y `get_historial` ordenado por `desde`
  (RN-03/RN-04 y design.md, decisión 5).
- `RepositorioEventos`: `registrar` con `flush` (nunca `commit`) y
  `buscar_paginado` con orden `cuando DESC, id DESC` y ventana respetada.
- `UoWUsuarios`: el rol y su evento se confirman juntos y, si el bloque falla,
  no queda ninguna de las dos filas (design.md, decisión 2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, Usuario
from app.modules.usuarios.repository import RepositorioEventos, RepositorioRoles
from app.modules.usuarios.unit_of_work import UoWUsuarios


async def _crear_usuario(
    sesion: AsyncSession,
    email: str = "mecanico@taller.test",
) -> Usuario:
    """Siembra un usuario mínimo y devuelve la fila con id."""
    usuario = Usuario(
        email=email,
        nombre="Usuario Test",
        password_hash="$2b$12$hash-de-prueba-no-usable",
    )
    sesion.add(usuario)
    await sesion.flush()
    return usuario


async def _contar(
    fabrica: async_sessionmaker[AsyncSession],
    modelo: type[AsignacionRol] | type[EventoSeguridad],
) -> int:
    """Cuenta filas del modelo en una sesión nueva (lee solo lo confirmado)."""
    async with fabrica() as verificacion:
        return int(
            (await verificacion.execute(select(func.count()).select_from(modelo))).scalar_one()
        )


async def test_roles_get_abierta_devuelve_solo_la_fila_sin_revocar(sesion: AsyncSession) -> None:
    """`get_abierta` filtra por `revocada_en IS NULL` y devuelve `None` si no hay ninguna."""
    usuario = await _crear_usuario(sesion)
    repo = RepositorioRoles(sesion)
    abierta = await repo.add(AsignacionRol(usuario_id=usuario.id, rol="MECANICO"))
    await repo.add(
        AsignacionRol(
            usuario_id=usuario.id,
            rol="RECEPCION",
            revocada_en=datetime.now(UTC),
        )
    )

    encontrada = await repo.get_abierta(usuario.id, "MECANICO")
    assert encontrada is not None
    assert encontrada.id == abierta.id

    assert await repo.get_abierta(usuario.id, "RECEPCION") is None  # revocada
    assert await repo.get_abierta(usuario.id, "ADMIN") is None  # nunca asignada


async def test_roles_revocar_escribe_revocada_en_sin_borrar_la_fila(sesion: AsyncSession) -> None:
    """`revocar` marca el cierre con `flush` y la fila sigue existiendo (RN-04)."""
    usuario = await _crear_usuario(sesion)
    repo = RepositorioRoles(sesion)
    asignacion = await repo.add(AsignacionRol(usuario_id=usuario.id, rol="MECANICO"))
    cuando = datetime.now(UTC)

    revocada = await repo.revocar(asignacion, cuando)

    assert revocada.revocada_en == cuando
    assert revocada.desde is not None  # el `desde` original se conserva
    filas = (
        (await sesion.execute(select(AsignacionRol).where(AsignacionRol.id == asignacion.id)))
        .scalars()
        .all()
    )
    assert len(filas) == 1  # nunca se borra la fila
    assert filas[0].revocada_en == cuando
    assert await repo.get_abierta(usuario.id, "MECANICO") is None


async def test_roles_get_historial_ordena_por_desde(sesion: AsyncSession) -> None:
    """`get_historial` devuelve todas las asignaciones (abiertas y cerradas) por `desde`."""
    usuario = await _crear_usuario(sesion)
    repo = RepositorioRoles(sesion)
    ahora = datetime.now(UTC)
    await repo.add(
        AsignacionRol(usuario_id=usuario.id, rol="RECEPCION", desde=ahora - timedelta(days=1))
    )
    await repo.add(
        AsignacionRol(usuario_id=usuario.id, rol="ADMIN", desde=ahora - timedelta(days=3))
    )
    await repo.add(
        AsignacionRol(
            usuario_id=usuario.id,
            rol="MECANICO",
            desde=ahora - timedelta(days=2),
            revocada_en=ahora,
        )
    )

    historial = await repo.get_historial(usuario.id)

    assert [fila.rol for fila in historial] == ["ADMIN", "MECANICO", "RECEPCION"]
    assert [fila.desde for fila in historial] == sorted(fila.desde for fila in historial)


async def test_roles_get_historial_no_mezcla_usuarios(sesion: AsyncSession) -> None:
    """Triangulación: el historial de un usuario no incluye las filas de otro."""
    usuario = await _crear_usuario(sesion, email="uno@taller.test")
    otro = await _crear_usuario(sesion, email="dos@taller.test")
    repo = RepositorioRoles(sesion)
    await repo.add(AsignacionRol(usuario_id=usuario.id, rol="MECANICO"))
    await repo.add(AsignacionRol(usuario_id=otro.id, rol="ADMIN"))

    historial = await repo.get_historial(usuario.id)

    assert [fila.rol for fila in historial] == ["MECANICO"]
    assert all(fila.usuario_id == usuario.id for fila in historial)


async def test_eventos_registrar_agrega_sin_commit(sesion: AsyncSession) -> None:
    """`registrar` agrega el evento con `flush`: visible en la sesión, sin confirmar."""
    repo = RepositorioEventos(sesion)

    evento = await repo.registrar("admin@taller.test", "alta_personal: nuevo@taller.test")

    assert evento.id is not None
    assert evento.actor == "admin@taller.test"
    assert evento.accion.startswith("alta_personal")


async def test_eventos_buscar_paginado_ordena_desc_y_respeta_la_ventana(
    sesion: AsyncSession,
) -> None:
    """`buscar_paginado` ordena `cuando DESC, id DESC` y devuelve `(items, total)`."""
    repo = RepositorioEventos(sesion)
    ahora = datetime.now(UTC)
    for indice in range(3):
        await repo.add(
            EventoSeguridad(
                cuando=ahora - timedelta(minutes=indice),
                actor="admin@taller.test",
                accion=f"evento-{indice}",
            )
        )

    items, total = await repo.buscar_paginado(offset=0, limit=2)

    assert total == 3
    assert [evento.accion for evento in items] == ["evento-0", "evento-1"]

    segunda_pagina, total_segunda = await repo.buscar_paginado(offset=2, limit=2)
    assert total_segunda == 3
    assert [evento.accion for evento in segunda_pagina] == ["evento-2"]


async def test_uow_confirma_rol_y_evento_juntos(
    sesion: AsyncSession,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> None:
    """Rol + evento dentro del mismo `async with UoWUsuarios` se confirman juntos (decisión 2)."""
    usuario = await _crear_usuario(sesion)
    await sesion.commit()

    async with UoWUsuarios(sesion) as uow:
        await uow.roles.asignar(usuario.id, "MECANICO")
        await uow.eventos.registrar("admin@taller.test", "rol_otorgado: MECANICO")

    assert await _contar(fabrica_pruebas, AsignacionRol) == 1
    assert await _contar(fabrica_pruebas, EventoSeguridad) == 1


async def test_uow_revierte_rol_y_evento_si_el_bloque_falla(
    sesion: AsyncSession,
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> None:
    """Una excepción dentro del bloque no deja ni el rol ni su evento (atomicidad)."""
    usuario = await _crear_usuario(sesion)
    await sesion.commit()

    with pytest.raises(RuntimeError):
        async with UoWUsuarios(sesion) as uow:
            await uow.roles.asignar(usuario.id, "MECANICO")
            await uow.eventos.registrar("admin@taller.test", "rol_otorgado: MECANICO")
            raise RuntimeError("falla simulada dentro del UoW")

    assert await _contar(fabrica_pruebas, AsignacionRol) == 0
    assert await _contar(fabrica_pruebas, EventoSeguridad) == 0
