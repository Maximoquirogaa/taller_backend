"""Repositorios genéricos: `flush()` y nunca `commit()` (spec `data-persistence`, D5).

El test central demuestra el contrato: después de `add()` la fila tiene PK pero
**no** está confirmada; recién el commit del UoW la hace visible a otra sesión.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.repository import BaseRepository, SoftDeleteRepository
from app.modules.usuarios.models import AsignacionRol, Usuario


def _usuario(email: str = "laura@taller.test", nombre: str = "Laura Gómez") -> Usuario:
    """Usuario mínimo válido para los tests de repositorio."""
    return Usuario(
        email=email,
        nombre=nombre,
        password_hash="$2b$12$hashDeMentiraParaLosTests",
    )


class RepositorioDeAsignaciones(SoftDeleteRepository[AsignacionRol]):
    """Soft delete sobre `revocada_en`: el modelo de prueba sin tabla nueva.

    `SoftDeleteRepository` se ejercita con una tabla real (regla dura: el esquema
    sale solo de Alembic, no se inventan tablas para los tests) usando la columna
    de revocación de roles como marca de baja.
    """

    campo_baja = "revocada_en"
    modelo = AsignacionRol


async def test_add_hace_flush_y_no_confirma(
    sesion: AsyncSession, fabrica_pruebas: async_sessionmaker[AsyncSession]
) -> None:
    """`add()` resuelve la PK con `flush()`, pero la fila no está confirmada."""
    repositorio = BaseRepository(sesion, Usuario)

    usuario = await repositorio.add(_usuario())

    assert usuario.id is not None, "el flush debería haber resuelto la PK"
    async with fabrica_pruebas() as otra_sesion:
        assert await otra_sesion.get(Usuario, usuario.id) is None

    await sesion.commit()  # el commit es del UoW; acá se simula ese rol

    async with fabrica_pruebas() as otra_sesion:
        assert await otra_sesion.get(Usuario, usuario.id) is not None


def test_los_repositorios_no_exponen_commit(sesion: AsyncSession) -> None:
    """Ningún repositorio puede confirmar por su cuenta: no hay `commit` (D5)."""
    assert not hasattr(BaseRepository(sesion, Usuario), "commit")
    assert not hasattr(RepositorioDeAsignaciones(sesion), "commit")


async def test_get_by_id_get_all_y_count(sesion: AsyncSession) -> None:
    """Las lecturas básicas devuelven lo que hay, en el orden de inserción."""
    repositorio = BaseRepository(sesion, Usuario)
    creados = [
        await repositorio.add(_usuario("a@taller.test", "Ana")),
        await repositorio.add(_usuario("b@taller.test", "Beto")),
        await repositorio.add(_usuario("c@taller.test", "Carla")),
    ]

    assert await repositorio.count() == 3
    assert [usuario.email for usuario in await repositorio.get_all()] == [
        usuario.email for usuario in creados
    ]
    assert await repositorio.get_by_id(creados[1].id) == creados[1]
    assert await repositorio.get_by_id(9999) is None


async def test_get_all_respeta_offset_y_limit(sesion: AsyncSession) -> None:
    """La página se pide con offset/limit sobre la misma consulta del total."""
    repositorio = BaseRepository(sesion, Usuario)
    for indice in range(5):
        await repositorio.add(_usuario(f"u{indice}@taller.test", f"Usuario {indice}"))

    pagina = await repositorio.get_all(offset=2, limit=2)

    assert [usuario.email for usuario in pagina] == ["u2@taller.test", "u3@taller.test"]
    assert await repositorio.count() == 5


async def test_count_respeta_los_filtros(sesion: AsyncSession) -> None:
    """`count(*filtros)` cuenta lo mismo que la página, no toda la tabla (spec pagination)."""
    repositorio = BaseRepository(sesion, Usuario)
    await repositorio.add(_usuario("freno@taller.test", "Freno"))
    await repositorio.add(_usuario("bujia@taller.test", "Bujía"))
    await repositorio.add(_usuario("filtro@taller.test", "Filtro"))

    filtro = Usuario.email.like("%filtro%")

    assert await repositorio.count(filtro) == 1
    assert len(await repositorio.get_all(filtro)) == 1
    assert await repositorio.count() == 3


async def test_update_aplica_cambios_y_no_confirma(
    sesion: AsyncSession, fabrica_pruebas: async_sessionmaker[AsyncSession]
) -> None:
    """`update()` cambia el objeto y hace flush, sin confirmar la transacción."""
    repositorio = BaseRepository(sesion, Usuario)
    usuario = await repositorio.add(_usuario(nombre="Laura"))
    await sesion.commit()

    await repositorio.update(usuario, {"nombre": "Laura Gómez"})

    assert usuario.nombre == "Laura Gómez"
    async with fabrica_pruebas() as otra_sesion:
        otro = await otra_sesion.get(Usuario, usuario.id)
        assert otro is not None
        assert otro.nombre == "Laura"

    await sesion.commit()

    async with fabrica_pruebas() as otra_sesion:
        otro = await otra_sesion.get(Usuario, usuario.id)
        assert otro is not None
        assert otro.nombre == "Laura Gómez"


async def test_delete_borra_y_no_confirma(
    sesion: AsyncSession, fabrica_pruebas: async_sessionmaker[AsyncSession]
) -> None:
    """`delete()` borra con flush; la fila desaparece para todos recién al confirmar."""
    repositorio = BaseRepository(sesion, Usuario)
    usuario = await repositorio.add(_usuario())
    await sesion.commit()

    await repositorio.delete(usuario)

    assert await repositorio.count() == 0
    async with fabrica_pruebas() as otra_sesion:
        assert await otra_sesion.get(Usuario, usuario.id) is not None

    await sesion.commit()

    async with fabrica_pruebas() as otra_sesion:
        assert await otra_sesion.get(Usuario, usuario.id) is None


async def test_soft_delete_filtra_los_dados_de_baja(sesion: AsyncSession) -> None:
    """`SoftDeleteRepository` esconde los dados de baja en lectura y en `count`."""
    usuarios = BaseRepository(sesion, Usuario)
    usuario = await usuarios.add(_usuario())
    asignaciones = RepositorioDeAsignaciones(sesion)
    vigente = await asignaciones.add(AsignacionRol(usuario_id=usuario.id, rol="MECANICO"))
    revocada = await asignaciones.add(AsignacionRol(usuario_id=usuario.id, rol="ADMIN"))

    await asignaciones.soft_delete(revocada)

    assert await asignaciones.count() == 1
    assert [fila.id for fila in await asignaciones.get_all()] == [vigente.id]
    assert await asignaciones.get_by_id(revocada.id) is None
    assert await asignaciones.get_by_id(vigente.id) is not None


async def test_soft_delete_conserva_la_fila(sesion: AsyncSession) -> None:
    """La baja es lógica: la fila sigue existiendo y se puede leer explícitamente."""
    usuarios = BaseRepository(sesion, Usuario)
    usuario = await usuarios.add(_usuario())
    asignaciones = RepositorioDeAsignaciones(sesion)
    asignacion = await asignaciones.add(AsignacionRol(usuario_id=usuario.id, rol="ADMIN"))

    momento = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    await asignaciones.soft_delete(asignacion, cuando=momento)

    recuperada = await asignaciones.get_by_id_including_deleted(asignacion.id)
    assert recuperada is not None
    assert recuperada.revocada_en == momento
    assert await usuarios.count() == 1  # el usuario no se toca


async def test_soft_delete_usa_el_reloj_cuando_no_se_indica(sesion: AsyncSession) -> None:
    """Sin `cuando`, la marca de baja la pone la aplicación con la hora UTC actual."""
    usuarios = BaseRepository(sesion, Usuario)
    usuario = await usuarios.add(_usuario())
    asignaciones = RepositorioDeAsignaciones(sesion)
    asignacion = await asignaciones.add(AsignacionRol(usuario_id=usuario.id, rol="CLIENTE"))

    antes = datetime.now(UTC)
    await asignaciones.soft_delete(asignacion)

    assert asignacion.revocada_en is not None
    assert antes <= asignacion.revocada_en <= datetime.now(UTC)


async def test_get_all_no_arrastra_estado_de_consultas_previas(sesion: AsyncSession) -> None:
    """Dos consultas con filtros distintos no se contaminan (sin estado compartido)."""
    repositorio = BaseRepository(sesion, Usuario)
    await repositorio.add(_usuario("uno@taller.test"))
    await repositorio.add(_usuario("dos@taller.test"))

    primero = await repositorio.get_all(Usuario.email == "uno@taller.test")
    segundo = await repositorio.get_all(Usuario.email == "dos@taller.test")

    assert [usuario.email for usuario in primero] == ["uno@taller.test"]
    assert [usuario.email for usuario in segundo] == ["dos@taller.test"]


@pytest.mark.parametrize("email", ["x@taller.test", "y@taller.test"])
async def test_add_devuelve_la_entidad_persistida(sesion: AsyncSession, email: str) -> None:
    """`add()` devuelve la misma entidad, ya sincronizada y con PK."""
    repositorio = BaseRepository(sesion, Usuario)

    usuario = await repositorio.add(_usuario(email))

    assert usuario.id is not None
    guardado = (await sesion.execute(select(Usuario).where(Usuario.email == email))).scalar_one()
    assert guardado is usuario
