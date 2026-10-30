"""Modelos de acceso: estructura declarada y reglas que garantiza PostgreSQL.

Spec `access-data-model`. Los primeros tests son estructurales (metadata, sin
base); los últimos van contra `taller_test` y comprueban que la base —y no la
aplicación— rechaza lo que corresponde (D9).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.modules.usuarios.models import (
    ROLES_VALIDOS,
    AsignacionRol,
    EventoSeguridad,
    IntentoAcceso,
    Usuario,
)

TABLAS_DE_ACCESO = {"usuario", "asignacion_rol", "intento_acceso", "evento_seguridad"}


def test_metadata_registra_las_cuatro_tablas_de_acceso() -> None:
    """Las 4 tablas de acceso quedan registradas en el metadata de SQLModel (D6)."""
    assert TABLAS_DE_ACCESO <= set(SQLModel.metadata.tables)


def test_usuario_email_es_unico() -> None:
    """`usuario.email` es UNIQUE (spec: email de usuario único)."""
    tabla = Usuario.__table__
    unicos = {
        tuple(sorted(columna.name for columna in restriccion.columns))
        for restriccion in tabla.constraints
        if isinstance(restriccion, UniqueConstraint)
    }
    assert ("email",) in unicos
    assert tabla.c.email.unique is True


def test_usuario_declara_los_campos_del_modelo_de_datos() -> None:
    """Los campos de `usuario` son los de la KB (04 §usuario), sin columnas de más."""
    assert set(Usuario.__table__.columns.keys()) == {
        "id",
        "email",
        "nombre",
        "password_hash",
        "activo",
        "debe_cambiar_password",
        "password_cambiada_en",
    }


def test_asignacion_rol_declara_los_campos_del_modelo_de_datos() -> None:
    """Los campos de `asignacion_rol` son los de la KB (04 §asignacion_rol)."""
    assert set(AsignacionRol.__table__.columns.keys()) == {
        "id",
        "usuario_id",
        "rol",
        "desde",
        "vence_en",
        "revocada_en",
        "otorgada_por",
    }


def test_intento_acceso_declara_los_campos_del_modelo_de_datos() -> None:
    """Los campos de `intento_acceso` son los de la KB (04 §intento_acceso)."""
    assert set(IntentoAcceso.__table__.columns.keys()) == {
        "id",
        "cuando",
        "email",
        "ip",
        "exito",
    }


def test_evento_seguridad_declara_los_campos_del_modelo_de_datos() -> None:
    """Los campos de `evento_seguridad` son los de la KB (04 §evento_seguridad)."""
    assert set(EventoSeguridad.__table__.columns.keys()) == {
        "id",
        "cuando",
        "actor",
        "accion",
    }


@pytest.mark.parametrize(
    "tabla",
    [Usuario.__table__, AsignacionRol.__table__, IntentoAcceso.__table__, EventoSeguridad.__table__],
    ids=["usuario", "asignacion_rol", "intento_acceso", "evento_seguridad"],
)
def test_columnas_temporales_son_timestamptz(tabla) -> None:  # noqa: ANN001
    """Toda columna temporal es `datetime` con `timezone=True` → `timestamptz` (D7)."""
    temporales = [columna for columna in tabla.columns if isinstance(columna.type, DateTime)]
    assert temporales, f"{tabla.name} debería tener al menos una columna temporal"
    assert all(columna.type.timezone is True for columna in temporales)


def test_intento_acceso_no_tiene_fk_y_si_indice_por_email_ip_y_cuando() -> None:
    """El intento sobrevive al rollback del usuario (DD-07): sin FK, con índice."""
    tabla = IntentoAcceso.__table__
    assert not tabla.foreign_keys
    indices = {
        tuple(columna.name for columna in indice.columns): indice
        for indice in tabla.indexes
    }
    assert ("email", "ip", "cuando") in indices


def test_evento_seguridad_actor_es_texto_y_no_tiene_fk() -> None:
    """`evento_seguridad.actor` es texto libre y la tabla no referencia a nadie."""
    tabla = EventoSeguridad.__table__
    assert not tabla.foreign_keys
    tipo = tabla.c.actor.type
    # SQLModel envuelve `str` en `AutoString` (TypeDecorator sobre String).
    assert isinstance(getattr(tipo, "impl", tipo), String)


def test_asignacion_rol_referencia_al_usuario() -> None:
    """`usuario_id` y `otorgada_por` apuntan a `usuario.id`."""
    tabla = AsignacionRol.__table__
    assert {fk.target_fullname for fk in tabla.foreign_keys} == {"usuario.id"}


def test_asignacion_rol_tiene_check_del_catalogo_de_roles() -> None:
    """El CHECK de `rol` nombra los cuatro roles del catálogo (D2, RN-01)."""
    checks = [
        restriccion
        for restriccion in AsignacionRol.__table__.constraints
        if isinstance(restriccion, CheckConstraint)
    ]
    assert checks, "asignacion_rol debería declarar un CheckConstraint"
    texto = " ".join(str(restriccion.sqltext) for restriccion in checks)
    assert all(f"'{rol}'" in texto for rol in ROLES_VALIDOS)


def test_asignacion_rol_tiene_indice_unico_parcial_de_abiertas() -> None:
    """Índice único parcial `(usuario_id, rol) WHERE revocada_en IS NULL` (D3)."""
    indices = {indice.name: indice for indice in AsignacionRol.__table__.indexes}
    indice = indices["uq_asignacion_rol_abierta"]
    assert indice.unique is True
    assert [columna.name for columna in indice.columns] == ["usuario_id", "rol"]
    condicion = indice.dialect_options["postgresql"]["where"]
    assert "revocada_en IS NULL" in str(condicion)


# ─────────────────────────────────────────────────────────────────────────────
# Base real: lo que rechaza PostgreSQL (task 2.3)
# ─────────────────────────────────────────────────────────────────────────────


def _usuario(email: str = "laura@taller.test") -> Usuario:
    """Usuario mínimo válido para los tests de integridad."""
    return Usuario(
        email=email,
        nombre="Laura Gómez",
        password_hash="$2b$12$hashDeMentiraParaLosTests",
    )


async def test_email_duplicado_rechazado_por_la_base(sesion: AsyncSession) -> None:
    """Dos usuarios con el mismo email: la base rechaza el segundo (IntegrityError)."""
    sesion.add(_usuario("repetido@taller.test"))
    await sesion.flush()

    sesion.add(_usuario("repetido@taller.test"))
    with pytest.raises(IntegrityError):
        await sesion.flush()
    await sesion.rollback()


async def test_segunda_asignacion_abierta_del_mismo_rol_rechazada(
    sesion: AsyncSession,
) -> None:
    """Sin `revocada_en`, el índice único parcial rechaza el segundo MECANICO (D3)."""
    usuario = _usuario()
    sesion.add(usuario)
    await sesion.flush()

    sesion.add(AsignacionRol(usuario_id=usuario.id, rol="MECANICO"))
    await sesion.flush()

    sesion.add(AsignacionRol(usuario_id=usuario.id, rol="MECANICO"))
    with pytest.raises(IntegrityError):
        await sesion.flush()
    await sesion.rollback()


async def test_rol_revocado_permite_reasignar_y_la_fila_revocada_sigue(
    sesion: AsyncSession,
) -> None:
    """Con `revocada_en` seteado se acepta la re-asignación; nadie borra la fila vieja."""
    usuario = _usuario()
    sesion.add(usuario)
    await sesion.flush()

    revocada = AsignacionRol(usuario_id=usuario.id, rol="MECANICO")
    sesion.add(revocada)
    await sesion.flush()
    revocada.revocada_en = datetime.now(UTC)
    await sesion.flush()

    nueva = AsignacionRol(usuario_id=usuario.id, rol="MECANICO")
    sesion.add(nueva)
    await sesion.flush()

    filas = (
        await sesion.execute(
            select(AsignacionRol).where(
                AsignacionRol.usuario_id == usuario.id,
                AsignacionRol.rol == "MECANICO",
            )
        )
    ).scalars().all()
    assert len(filas) == 2
    assert {fila.revocada_en is None for fila in filas} == {True, False}


async def test_rol_fuera_de_catalogo_rechazado_por_check(sesion: AsyncSession) -> None:
    """Un rol distinto de los cuatro del catálogo viola el CHECK de la base (D2)."""
    usuario = _usuario()
    sesion.add(usuario)
    await sesion.flush()

    sesion.add(AsignacionRol(usuario_id=usuario.id, rol="GERENTE"))
    with pytest.raises(IntegrityError):
        await sesion.flush()
    await sesion.rollback()


async def test_intento_de_acceso_sobrevive_sin_usuario(sesion: AsyncSession) -> None:
    """El intento se registra sin que exista el usuario (sin FK, DD-07)."""
    sesion.add(IntentoAcceso(email="fantasma@taller.test", ip="10.0.0.7", exito=False))
    await sesion.flush()

    filas = (await sesion.execute(select(IntentoAcceso))).scalars().all()
    assert len(filas) == 1
    assert filas[0].cuando is not None
