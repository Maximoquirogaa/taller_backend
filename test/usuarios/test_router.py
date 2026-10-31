"""Tests HTTP del módulo usuarios (C-06).

Cubre, por grupo de tareas:
- Alta de personal con contraseña provisoria (US-008, RN-01).
- Otorgamiento de rol con vigencia (US-009, RN-03).
- Revocación de rol sin borrar la fila (US-010, RN-04) y autoprotección (RN-05).
- Consulta paginada de eventos (US-011).
- Auditoría del cambio de contraseña y desbloqueo de la provisoria (RN-06/RN-07).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mensajes_auth import NOMBRE_COOKIE_SESION
from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, Usuario
from test.usuarios.conftest import autenticar_usuario

CORREO_ADMIN = "admin@taller.com"
CONTRASENA_PROVISORIA = "provisoria-2026"


async def _contar(sesion_db: AsyncSession, modelo: type) -> int:
    """Cuenta filas del modelo con una consulta fresca (lee lo confirmado)."""
    return int(
        (await sesion_db.execute(select(func.count()).select_from(modelo))).scalar_one()
    )


async def _contar_asignaciones_de(sesion_db: AsyncSession, usuario_id: int) -> int:
    """Cuenta las asignaciones de rol de un usuario (abiertas o cerradas)."""
    return int(
        (
            await sesion_db.execute(
                select(func.count())
                .select_from(AsignacionRol)
                .where(AsignacionRol.usuario_id == usuario_id)
            )
        ).scalar_one()
    )


async def _eventos(
    sesion_db: AsyncSession, actor: str | None = None
) -> list[EventoSeguridad]:
    """Lee los eventos de seguridad (opcionalmente filtrados por actor)."""
    consulta = (
        select(EventoSeguridad)
        .order_by(EventoSeguridad.id)
        .execution_options(populate_existing=True)
    )
    if actor is not None:
        consulta = consulta.where(EventoSeguridad.actor == actor)
    return list((await sesion_db.execute(consulta)).scalars().all())


# ── Grupo 3: alta de personal (US-008) ───────────────────────────────────────


async def test_alta_personal_admin_exitosa_con_provisoria_y_evento(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /usuarios: 201 con provisoria, sin hash en el cuerpo y evento del alta (US-008)."""
    await autenticar_usuario(cliente_http, sesion_db, CORREO_ADMIN, "ADMIN")

    respuesta = await cliente_http.post(
        "/usuarios",
        json={
            "email": "nuevo@taller.com",
            "nombre": "Nuevo Empleado",
            "password": CONTRASENA_PROVISORIA,
        },
    )

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["email"] == "nuevo@taller.com"
    assert cuerpo["nombre"] == "Nuevo Empleado"
    assert cuerpo["activo"] is True
    assert cuerpo["debe_cambiar_password"] is True
    assert "password" not in cuerpo
    assert "password_hash" not in cuerpo
    assert "$2b$" not in respuesta.text

    creado = (
        await sesion_db.execute(select(Usuario).where(Usuario.email == "nuevo@taller.com"))
    ).scalar_one()
    assert creado.debe_cambiar_password is True
    assert creado.password_hash.startswith("$2b$")
    assert creado.password_hash != CONTRASENA_PROVISORIA

    eventos = await _eventos(sesion_db, actor=CORREO_ADMIN)
    assert len(eventos) == 1
    assert eventos[0].accion.startswith("alta_personal")
    assert "nuevo@taller.com" in eventos[0].accion


async def test_alta_personal_email_duplicado_409_sin_usuario_ni_evento(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /usuarios: email ya registrado → 409 propio, sin usuario nuevo ni evento (RN-01)."""
    await autenticar_usuario(cliente_http, sesion_db, CORREO_ADMIN, "ADMIN")

    respuesta = await cliente_http.post(
        "/usuarios",
        json={
            "email": CORREO_ADMIN,
            "nombre": "Otro Administrador",
            "password": CONTRASENA_PROVISORIA,
        },
    )

    assert respuesta.status_code == 409
    detalle = respuesta.json()["detail"]
    assert isinstance(detalle, str) and detalle.strip()
    assert "duplicate" not in detalle.lower()  # sin texto de PostgreSQL (RN-18)
    assert "usuario_email_key" not in detalle

    assert await _contar(sesion_db, Usuario) == 1  # solo el ADMIN sembrado
    assert await _contar(sesion_db, EventoSeguridad) == 0


@pytest.mark.parametrize(
    "cuerpo",
    [
        pytest.param(
            {
                "email": "contrato@taller.com",
                "nombre": "Contrato",
                "password": CONTRASENA_PROVISORIA,
                "campo_extra": "no permitido",
            },
            id="campo-extra",
        ),
        pytest.param(
            {"email": "no-es-email", "nombre": "Contrato", "password": CONTRASENA_PROVISORIA},
            id="email-invalido",
        ),
        pytest.param(
            {"email": "contrato@taller.com", "nombre": "Contrato", "password": "a" * 72 + "1"},
            id="password-73-bytes",
        ),
        pytest.param(
            {"email": "contrato@taller.com", "nombre": "", "password": CONTRASENA_PROVISORIA},
            id="nombre-vacio",
        ),
    ],
)
async def test_contrato_alta_personal_rechaza_con_422_sin_filas(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
    cuerpo: dict[str, str],
) -> None:
    """Contrato estricto del alta: 422 propio sin abrir transacción ni escribir filas."""
    await autenticar_usuario(cliente_http, sesion_db, CORREO_ADMIN, "ADMIN")

    respuesta = await cliente_http.post("/usuarios", json=cuerpo)

    assert respuesta.status_code == 422, respuesta.text
    assert isinstance(respuesta.json()["detail"], list)  # validación del contrato
    assert await _contar(sesion_db, Usuario) == 1
    assert await _contar(sesion_db, EventoSeguridad) == 0


@pytest.mark.parametrize("rol", ["RECEPCION", "MECANICO", "CLIENTE"])
async def test_alta_personal_no_admin_403(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
    rol: str,
) -> None:
    """POST /usuarios: sin rol ADMIN vigente responde 403 y no crea el usuario."""
    await autenticar_usuario(cliente_http, sesion_db, f"{rol.lower()}@taller.com", rol)

    respuesta = await cliente_http.post(
        "/usuarios",
        json={
            "email": "intruso@taller.com",
            "nombre": "Intruso",
            "password": CONTRASENA_PROVISORIA,
        },
    )

    assert respuesta.status_code == 403
    assert await _contar(sesion_db, Usuario) == 1
    assert await _contar(sesion_db, EventoSeguridad) == 0


async def test_alta_personal_sin_sesion_401(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /usuarios: sin cookie de sesión responde 401 (nunca 403)."""
    cliente_http.cookies.clear()

    respuesta = await cliente_http.post(
        "/usuarios",
        json={
            "email": "sin-sesion@taller.com",
            "nombre": "Sin Sesión",
            "password": CONTRASENA_PROVISORIA,
        },
    )

    assert respuesta.status_code == 401
    assert await _contar(sesion_db, Usuario) == 0


# ── Grupo 4: otorgamiento de rol con vigencia (US-009, RN-03) ─────────────────


async def _crear_usuario_sin_rol(sesion_db: AsyncSession, email: str) -> Usuario:
    """Siembra un usuario sin asignaciones de rol (destinatario de un otorgamiento)."""
    usuario = Usuario(
        email=email,
        nombre="Personal Sin Rol",
        password_hash="$2b$12$hash-de-prueba-no-usable",
    )
    sesion_db.add(usuario)
    await sesion_db.commit()
    return usuario


async def test_roles_otorgar_sin_vencimiento_201_con_evento(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /usuarios/{id}/roles: abierto, `otorgada_por` = ADMIN y evento `rol_otorgado` (US-009)."""
    admin = await autenticar_usuario(cliente_http, sesion_db, CORREO_ADMIN, "ADMIN")
    destino = await _crear_usuario_sin_rol(sesion_db, "destino@taller.com")

    respuesta = await cliente_http.post(
        f"/usuarios/{destino.id}/roles", json={"rol": "MECANICO"}
    )

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["usuario_id"] == destino.id
    assert cuerpo["rol"] == "MECANICO"
    assert cuerpo["vence_en"] is None
    assert cuerpo["revocada_en"] is None
    assert cuerpo["otorgada_por"] == admin.id
    assert cuerpo["desde"] is not None

    eventos = await _eventos(sesion_db, actor=CORREO_ADMIN)
    assert len(eventos) == 1
    assert eventos[0].accion.startswith("rol_otorgado")
    assert "MECANICO" in eventos[0].accion


async def test_roles_otorgar_con_vencimiento_futuro_201(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /usuarios/{id}/roles: el vencimiento con zona se persiste normalizado a UTC."""
    await autenticar_usuario(cliente_http, sesion_db, CORREO_ADMIN, "ADMIN")
    destino = await _crear_usuario_sin_rol(sesion_db, "destino@taller.com")

    respuesta = await cliente_http.post(
        f"/usuarios/{destino.id}/roles",
        json={"rol": "RECEPCION", "vencimiento": "2030-01-01T10:00:00-03:00"},
    )

    assert respuesta.status_code == 201, respuesta.text
    vence_en = datetime.fromisoformat(respuesta.json()["vence_en"])
    assert vence_en == datetime(2030, 1, 1, 13, 0, tzinfo=UTC)
    assert vence_en.tzinfo is not None


async def test_roles_otorgar_rol_ya_vigente_409_sin_segunda_fila_ni_evento(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /usuarios/{id}/roles: rol ya abierto y vigente → 409 sin segunda fila ni evento (RN-03)."""
    await autenticar_usuario(cliente_http, sesion_db, CORREO_ADMIN, "ADMIN")
    destino = await _crear_usuario_sin_rol(sesion_db, "destino@taller.com")

    primera = await cliente_http.post(f"/usuarios/{destino.id}/roles", json={"rol": "MECANICO"})
    assert primera.status_code == 201, primera.text

    respuesta = await cliente_http.post(f"/usuarios/{destino.id}/roles", json={"rol": "MECANICO"})

    assert respuesta.status_code == 409
    assert isinstance(respuesta.json()["detail"], str)
    assert await _contar_asignaciones_de(sesion_db, destino.id) == 1
    assert await _contar(sesion_db, EventoSeguridad) == 1


@pytest.mark.parametrize(
    "vencimiento",
    [
        pytest.param("2030-01-01T10:00:00", id="sin-zona-horaria"),
        pytest.param("2020-01-01T10:00:00+00:00", id="en-el-pasado"),
    ],
)
async def test_roles_otorgar_vencimiento_invalido_422(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
    vencimiento: str,
) -> None:
    """POST /usuarios/{id}/roles: vencimiento sin zona o pasado → 422 sin abrir la asignación."""
    await autenticar_usuario(cliente_http, sesion_db, CORREO_ADMIN, "ADMIN")
    destino = await _crear_usuario_sin_rol(sesion_db, "destino@taller.com")

    respuesta = await cliente_http.post(
        f"/usuarios/{destino.id}/roles",
        json={"rol": "MECANICO", "vencimiento": vencimiento},
    )

    assert respuesta.status_code == 422, respuesta.text
    assert await _contar_asignaciones_de(sesion_db, destino.id) == 0
    assert await _contar(sesion_db, EventoSeguridad) == 0


async def test_roles_otorgar_usuario_inexistente_404(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /usuarios/{id}/roles: usuario inexistente → 404 sin escribir la asignación."""
    await autenticar_usuario(cliente_http, sesion_db, CORREO_ADMIN, "ADMIN")

    respuesta = await cliente_http.post("/usuarios/999999/roles", json={"rol": "MECANICO"})

    assert respuesta.status_code == 404
    assert await _contar_asignaciones_de(sesion_db, 999999) == 0
    assert await _contar(sesion_db, EventoSeguridad) == 0


async def test_roles_otorgar_no_admin_403(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /usuarios/{id}/roles: un MECANICO no puede otorgar roles (403)."""
    await autenticar_usuario(cliente_http, sesion_db, "mecanico@taller.com", "MECANICO")
    destino = await _crear_usuario_sin_rol(sesion_db, "destino@taller.com")

    respuesta = await cliente_http.post(
        f"/usuarios/{destino.id}/roles", json={"rol": "ADMIN"}
    )

    assert respuesta.status_code == 403
    assert await _contar_asignaciones_de(sesion_db, destino.id) == 0


# ── Grupo 5: revocación de rol (US-010, RN-04, RN-05) ────────────────────────


async def test_roles_revocar_admin_200_conserva_desde_y_audita(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """DELETE /usuarios/{id}/roles/{rol}: 200, `revocada_en` escrito, `desde` conservado y evento."""
    await autenticar_usuario(cliente_http, sesion_db, CORREO_ADMIN, "ADMIN")
    destino = await _crear_usuario_sin_rol(sesion_db, "destino@taller.com")
    otorgada = await cliente_http.post(
        f"/usuarios/{destino.id}/roles", json={"rol": "RECEPCION"}
    )
    assert otorgada.status_code == 201, otorgada.text
    desde_original = datetime.fromisoformat(otorgada.json()["desde"])

    respuesta = await cliente_http.delete(f"/usuarios/{destino.id}/roles/RECEPCION")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["rol"] == "RECEPCION"
    assert cuerpo["revocada_en"] is not None
    assert datetime.fromisoformat(cuerpo["desde"]) == desde_original

    fila = (
        await sesion_db.execute(
            select(AsignacionRol)
            .where(AsignacionRol.usuario_id == destino.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert fila.revocada_en is not None  # la fila se conserva (nunca DELETE)
    assert fila.desde == desde_original

    eventos = await _eventos(sesion_db, actor=CORREO_ADMIN)
    assert [evento.accion.split(":")[0] for evento in eventos] == [
        "rol_otorgado",
        "rol_revocado",
    ]
    assert "RECEPCION" in eventos[1].accion


async def test_roles_revocar_permiso_perdido_alcanza_la_sesion_abierta(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """RN-04: revocado el rol, la misma cookie recibe 403 en la petición siguiente."""
    mecanico = await autenticar_usuario(
        cliente_http, sesion_db, "mecanico@taller.com", "MECANICO"
    )
    token_mecanico = cliente_http.cookies.get(NOMBRE_COOKIE_SESION)
    assert token_mecanico is not None

    cliente_http.cookies.clear()
    antes = await cliente_http.get(
        "/repuestos", cookies={NOMBRE_COOKIE_SESION: token_mecanico}
    )
    assert antes.status_code == 200, antes.text

    await autenticar_usuario(cliente_http, sesion_db, CORREO_ADMIN, "ADMIN")
    revocacion = await cliente_http.delete(f"/usuarios/{mecanico.id}/roles/MECANICO")
    assert revocacion.status_code == 200, revocacion.text

    cliente_http.cookies.clear()
    despues = await cliente_http.get(
        "/repuestos", cookies={NOMBRE_COOKIE_SESION: token_mecanico}
    )
    assert despues.status_code == 403  # sin esperar al vencimiento del token


@pytest.mark.parametrize("estado", ["nunca-asignado", "ya-revocado", "vencido"])
async def test_roles_revocar_rol_no_abierto_404_sin_modificar(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
    estado: str,
) -> None:
    """DELETE .../roles/{rol}: rol inexistente, revocado o vencido → 404 sin escribir evento."""
    await autenticar_usuario(cliente_http, sesion_db, CORREO_ADMIN, "ADMIN")
    destino = await _crear_usuario_sin_rol(sesion_db, "destino@taller.com")
    ahora = datetime.now(UTC)

    if estado == "ya-revocado":
        sesion_db.add(
            AsignacionRol(
                usuario_id=destino.id,
                rol="MECANICO",
                revocada_en=ahora - timedelta(minutes=1),
            )
        )
        await sesion_db.commit()
    elif estado == "vencido":
        sesion_db.add(
            AsignacionRol(
                usuario_id=destino.id,
                rol="MECANICO",
                desde=ahora - timedelta(days=60),
                vence_en=ahora - timedelta(days=1),
            )
        )
        await sesion_db.commit()

    respuesta = await cliente_http.delete(f"/usuarios/{destino.id}/roles/MECANICO")

    assert respuesta.status_code == 404, respuesta.text
    assert await _contar(sesion_db, EventoSeguridad) == 0
    abiertas = list(
        (
            await sesion_db.execute(
                select(AsignacionRol)
                .where(AsignacionRol.usuario_id == destino.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    if estado == "nunca-asignado":
        assert abiertas == []
    else:
        assert len(abiertas) == 1
        if estado == "ya-revocado":
            assert abiertas[0].revocada_en is not None  # la que ya estaba cerrada
        else:
            assert abiertas[0].revocada_en is None  # la vencida queda intacta


async def test_roles_revocar_no_admin_403(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """DELETE .../roles/{rol}: un MECANICO no puede revocar roles (403)."""
    await autenticar_usuario(cliente_http, sesion_db, "mecanico@taller.com", "MECANICO")
    destino = await _crear_usuario_sin_rol(sesion_db, "destino@taller.com")
    sesion_db.add(AsignacionRol(usuario_id=destino.id, rol="RECEPCION"))
    await sesion_db.commit()

    respuesta = await cliente_http.delete(f"/usuarios/{destino.id}/roles/RECEPCION")

    assert respuesta.status_code == 403
    fila = (
        await sesion_db.execute(
            select(AsignacionRol)
            .where(AsignacionRol.usuario_id == destino.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert fila.revocada_en is None  # la asignación sigue abierta


