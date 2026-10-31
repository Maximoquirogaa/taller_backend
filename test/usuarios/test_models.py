"""Guardas del esquema de acceso del que depende C-06 (task 1.2).

C-06 **no** cambia modelos (design.md, decisión 3): estas pruebas documentan las
restricciones que ya garantiza `001_esquema_inicial` y fallan si una migración
futura rompe el índice parcial de RN-03 o el catálogo de roles:

- `uq_asignacion_rol_abierta (usuario_id, rol) WHERE revocada_en IS NULL`:
  dos asignaciones abiertas del mismo rol son imposibles.
- CHECK del catálogo `ADMIN/RECEPCION/MECANICO/CLIENTE`.
- Escribir `revocada_en` conserva `desde` y libera el índice para abrir una
  fila nueva del mismo rol (reasignación sin borrar historial).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usuarios.models import AsignacionRol, Usuario


async def _crear_usuario(sesion: AsyncSession) -> Usuario:
    """Siembra un usuario mínimo y devuelve la fila con id."""
    usuario = Usuario(
        email="mecanico@taller.test",
        nombre="Mecánico Test",
        password_hash="$2b$12$hash-de-prueba-no-usable",
    )
    sesion.add(usuario)
    await sesion.flush()
    return usuario


async def test_indice_parcial_impide_dos_asignaciones_abiertas_del_mismo_rol(
    sesion: AsyncSession,
) -> None:
    """Dos filas abiertas del mismo (usuario, rol) violan `uq_asignacion_rol_abierta` (RN-03)."""
    usuario = await _crear_usuario(sesion)
    sesion.add(AsignacionRol(usuario_id=usuario.id, rol="MECANICO"))
    await sesion.flush()

    with pytest.raises(IntegrityError):
        sesion.add(AsignacionRol(usuario_id=usuario.id, rol="MECANICO"))
        await sesion.flush()
    await sesion.rollback()


async def test_check_rechaza_un_rol_fuera_del_catalogo(sesion: AsyncSession) -> None:
    """El CHECK del catálogo rechaza roles que no son ADMIN/RECEPCION/MECANICO/CLIENTE."""
    usuario = await _crear_usuario(sesion)

    with pytest.raises(IntegrityError):
        sesion.add(AsignacionRol(usuario_id=usuario.id, rol="SUPERADMIN"))
        await sesion.flush()
    await sesion.rollback()


async def test_revocar_conserva_desde_y_permite_abrir_una_fila_nueva(
    sesion: AsyncSession,
) -> None:
    """Marcar `revocada_en` conserva la fila anterior y libera el índice para el mismo rol (RN-03)."""
    usuario = await _crear_usuario(sesion)
    desde_original = datetime.now(UTC) - timedelta(days=30)
    anterior = AsignacionRol(usuario_id=usuario.id, rol="MECANICO", desde=desde_original)
    sesion.add(anterior)
    await sesion.flush()

    anterior.revocada_en = datetime.now(UTC)
    await sesion.flush()

    nueva = AsignacionRol(usuario_id=usuario.id, rol="MECANICO")
    sesion.add(nueva)
    await sesion.flush()

    filas = (
        (
            await sesion.execute(
                select(AsignacionRol)
                .where(
                    AsignacionRol.usuario_id == usuario.id,
                    AsignacionRol.rol == "MECANICO",
                )
                .order_by(AsignacionRol.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(filas) == 2  # ninguna fila se borró
    assert filas[0].revocada_en is not None
    assert filas[0].desde == desde_original  # el `desde` original queda intacto
    assert filas[1].revocada_en is None
