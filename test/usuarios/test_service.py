"""Tests de la capa de servicio del módulo usuarios (C-06).

Verifica las reglas que no se pueden observar solo por HTTP:
- `crear_empleado`: bcrypt se calcula **antes** de abrir el UoW (regla dura) y el
  hash guardado verifica contra la contraseña provisoria (task 3.3).
- `crear_empleado`: el evento del alta se escribe en la misma transacción (US-011).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    COSTO_BCRYPT_PREDETERMINADO,
    hash_password,
    verificar_password,
)
from app.modules.usuarios import service as servicio_usuarios
from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, Usuario
from app.modules.usuarios.schemas import (
    EntradaAsignarRol,
    EntradaCambioPassword,
    EntradaCrearUsuario,
)
from app.modules.usuarios.unit_of_work import UoWUsuarios

CONTRASENA_PROVISORIA = "provisoria-2026"
CORREO_ADMIN = "admin@taller.com"


async def test_crear_empleado_hashea_antes_de_abrir_el_uow(
    sesion_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El hash se calcula con la sesión **sin** transacción abierta (HASH antes del UoW)."""
    transaccion_abierta_al_hashear: list[bool] = []
    original: Callable[[str, int], Awaitable[str]] = servicio_usuarios.hash_password

    async def espia(contrasena: str, costo: int = COSTO_BCRYPT_PREDETERMINADO) -> str:
        """Anota si la sesión ya tenía transacción al momento de hashear."""
        transaccion_abierta_al_hashear.append(sesion_db.in_transaction())
        return await original(contrasena, costo)

    monkeypatch.setattr(servicio_usuarios, "hash_password", espia)

    usuario = await servicio_usuarios.crear_empleado(
        UoWUsuarios(sesion_db),
        EntradaCrearUsuario(
            email="empleado@taller.com",
            nombre="Empleado Nuevo",
            password=CONTRASENA_PROVISORIA,
        ),
        actor_email=CORREO_ADMIN,
    )

    assert transaccion_abierta_al_hashear == [False]
    assert usuario.debe_cambiar_password is True
    assert usuario.activo is True
    assert usuario.email == "empleado@taller.com"
    assert await verificar_password(CONTRASENA_PROVISORIA, usuario.password_hash)


async def test_crear_empleado_escribe_el_evento_del_alta_en_el_mismo_uow(
    sesion_db: AsyncSession,
) -> None:
    """El alta deja su `evento_seguridad` con el email del ADMIN como actor (US-011)."""
    await servicio_usuarios.crear_empleado(
        UoWUsuarios(sesion_db),
        EntradaCrearUsuario(
            email="empleado@taller.com",
            nombre="Empleado Nuevo",
            password=CONTRASENA_PROVISORIA,
        ),
        actor_email=CORREO_ADMIN,
    )

    eventos = list((await sesion_db.execute(select(EventoSeguridad))).scalars().all())
    assert len(eventos) == 1
    assert eventos[0].actor == CORREO_ADMIN
    assert eventos[0].accion.startswith("alta_personal")
    assert "empleado@taller.com" in eventos[0].accion

    total = int(
        (await sesion_db.execute(select(func.count()).select_from(Usuario))).scalar_one()
    )
    assert total == 1


# ── Grupo 4: reasignación de un rol vencido (design.md, decisión 4) ──────────


async def _sembrar_usuario(sesion_db: AsyncSession, email: str, nombre: str) -> Usuario:
    """Siembra un usuario mínimo (sin roles) y devuelve la fila con id."""
    usuario = Usuario(
        email=email,
        nombre=nombre,
        password_hash="$2b$12$hash-de-prueba-no-usable",
    )
    sesion_db.add(usuario)
    await sesion_db.flush()
    await sesion_db.commit()
    return usuario


async def test_otorgar_rol_vencido_cierra_la_fila_anterior_y_abre_una_nueva(
    sesion_db: AsyncSession,
) -> None:
    """Una fila abierta vencida se cierra con `revocada_en` y se abre otra, sin tocar el historial."""
    actor = await _sembrar_usuario(sesion_db, CORREO_ADMIN, "Admin Test")
    destino = await _sembrar_usuario(sesion_db, "destino@taller.com", "Destino Test")

    ahora = datetime.now(UTC)
    desde_anterior = ahora - timedelta(days=60)
    vencimiento_anterior = ahora - timedelta(days=1)
    sesion_db.add(
        AsignacionRol(
            usuario_id=destino.id,
            rol="MECANICO",
            desde=desde_anterior,
            vence_en=vencimiento_anterior,
            otorgada_por=actor.id,
        )
    )
    await sesion_db.commit()

    nueva = await servicio_usuarios.otorgar_rol(
        UoWUsuarios(sesion_db),
        destino.id,
        EntradaAsignarRol(rol="MECANICO"),
        actor_id=actor.id,
        actor_email=actor.email,
    )

    filas = list(
        (
            await sesion_db.execute(
                select(AsignacionRol)
                .order_by(AsignacionRol.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    assert len(filas) == 2  # ninguna fila se borró
    anterior, abierta = filas
    assert anterior.revocada_en is not None  # cerrada al reasignar
    assert anterior.desde == desde_anterior  # historial intacto
    assert anterior.vence_en == vencimiento_anterior  # el vencimiento pactado no se falsea
    assert abierta.revocada_en is None
    assert abierta.vence_en is None
    assert abierta.otorgada_por == actor.id
    assert nueva.id == abierta.id

    eventos = list((await sesion_db.execute(select(EventoSeguridad))).scalars().all())
    assert len(eventos) == 1  # el cierre por vencimiento no es una revocación
    assert eventos[0].accion.startswith("rol_otorgado")


# ── Grupo 5: autoprotección del ADMIN (RN-05) ────────────────────────────────


async def test_revocar_rol_autorrevocacion_admin_prohibida(
    sesion_db: AsyncSession,
) -> None:
    """Un ADMIN no puede revocar su propio ADMIN: excepción, fila intacta y sin evento (RN-05)."""
    admin = await _sembrar_usuario(sesion_db, CORREO_ADMIN, "Admin Test")
    sesion_db.add(AsignacionRol(usuario_id=admin.id, rol="ADMIN"))
    await sesion_db.commit()

    with pytest.raises(servicio_usuarios.AutorrevocacionProhibida):
        await servicio_usuarios.revocar_rol(
            UoWUsuarios(sesion_db),
            admin.id,
            "ADMIN",
            actor_id=admin.id,
            actor_email=admin.email,
        )

    fila = (
        await sesion_db.execute(
            select(AsignacionRol)
            .where(AsignacionRol.usuario_id == admin.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert fila.revocada_en is None  # la asignación permanece abierta
    eventos = list((await sesion_db.execute(select(EventoSeguridad))).scalars().all())
    assert eventos == []  # sin evento de revocación


async def test_revocar_rol_admin_de_otro_usuario_procede(
    sesion_db: AsyncSession,
) -> None:
    """Revocar el ADMIN de **otro** usuario sí procede: la regla es solo autoprotección (RN-05)."""
    admin = await _sembrar_usuario(sesion_db, CORREO_ADMIN, "Admin Test")
    otro = await _sembrar_usuario(sesion_db, "otro-admin@taller.com", "Otro Admin")
    sesion_db.add(AsignacionRol(usuario_id=admin.id, rol="ADMIN"))
    asignacion = AsignacionRol(usuario_id=otro.id, rol="ADMIN")
    sesion_db.add(asignacion)
    await sesion_db.commit()
    desde_original = asignacion.desde

    revocada = await servicio_usuarios.revocar_rol(
        UoWUsuarios(sesion_db),
        otro.id,
        "ADMIN",
        actor_id=admin.id,
        actor_email=admin.email,
    )

    assert revocada.revocada_en is not None
    assert revocada.desde == desde_original
    eventos = list((await sesion_db.execute(select(EventoSeguridad))).scalars().all())
    assert len(eventos) == 1
    assert eventos[0].accion.startswith("rol_revocado")
    assert eventos[0].actor == CORREO_ADMIN


# ── Grupo 7: auditoría del cambio de contraseña (US-011) ─────────────────────


async def _sembrar_usuario_con_password(
    sesion_db: AsyncSession, email: str, password: str
) -> Usuario:
    """Siembra un usuario con contraseña verificable (bcrypt real)."""
    usuario = Usuario(
        email=email,
        nombre="Usuario Password",
        password_hash=await hash_password(password, COSTO_BCRYPT_PREDETERMINADO),
    )
    sesion_db.add(usuario)
    await sesion_db.commit()
    return usuario


async def test_cambiar_password_escribe_evento_del_cambio(sesion_db: AsyncSession) -> None:
    """Un cambio exitoso deja `cambio_password` con el email del usuario como actor (US-011)."""
    usuario = await _sembrar_usuario_con_password(
        sesion_db, "usuario@taller.com", "actual-2026"
    )

    roles = await servicio_usuarios.cambiar_password(
        sesion_db,
        usuario,
        EntradaCambioPassword(
            password_actual="actual-2026", password_nueva="nueva-2026"
        ),
        COSTO_BCRYPT_PREDETERMINADO,
    )

    assert roles == []
    eventos = list((await sesion_db.execute(select(EventoSeguridad))).scalars().all())
    assert len(eventos) == 1
    assert eventos[0].actor == "usuario@taller.com"
    assert eventos[0].accion.startswith("cambio_password")

    guardado = (
        await sesion_db.execute(
            select(Usuario)
            .where(Usuario.email == "usuario@taller.com")
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert await verificar_password("nueva-2026", guardado.password_hash)
    assert guardado.debe_cambiar_password is False


async def test_cambiar_password_rechazado_no_escribe_evento(sesion_db: AsyncSession) -> None:
    """Con la contraseña actual incorrecta no se modifica nada ni se audita (RN-07)."""
    usuario = await _sembrar_usuario_con_password(
        sesion_db, "usuario@taller.com", "actual-2026"
    )

    with pytest.raises(servicio_usuarios.ContrasenaActualIncorrecta):
        await servicio_usuarios.cambiar_password(
            sesion_db,
            usuario,
            EntradaCambioPassword(
                password_actual="equivocada-2026", password_nueva="nueva-2026"
            ),
            COSTO_BCRYPT_PREDETERMINADO,
        )

    eventos = list((await sesion_db.execute(select(EventoSeguridad))).scalars().all())
    assert eventos == []


