"""Tests de integración de `POST /auth/registro` (RN-02, US-003).

Comprueba el spec `user-auth`: 201 con las filas atómicas (usuario + rol
CLIENTE + intento inicial), 409 con email duplicado, 422 con contrato
estricto y ninguna respuesta que exponga la contraseña o el hash.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.usuarios.models import AsignacionRol, IntentoAcceso, Usuario

CORREO_NUEVO = "martin@example.com"
NOMBRE_NUEVO = "Martín Ferreyra"
CONTRASENA_NUEVA = "estudio-pass-2026"


@pytest.fixture
async def sesion_pruebas(
    fabrica_pruebas: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Sesión directa a `taller_test` para asertar lo que la API dejó en la base."""
    async with fabrica_pruebas() as session:
        yield session


@pytest.mark.parametrize(
    "cuerpo, motivo",
    [
        ({"email": CORREO_NUEVO, "nombre": NOMBRE_NUEVO, "password": CONTRASENA_NUEVA, "admin": True},
         "campo extra (?) extra=\"forbid\""),
        ({"email": CORREO_NUEVO, "nombre": NOMBRE_NUEVO, "password": "a" * 73 + "1"},
         "contraseña de 74 caracteres (más de 72 bytes)"),
        ({"email": CORREO_NUEVO, "nombre": NOMBRE_NUEVO, "password": "pass sin numeros"},
         "contraseña sin dígitos"),
        ({"email": "no-es-un-correo", "nombre": NOMBRE_NUEVO, "password": CONTRASENA_NUEVA},
         "email mal formado"),
    ],
)
async def test_registro_rechaza_contrato_con_422(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession, cuerpo: dict[str, object], motivo: str
) -> None:
    """Entrada inválida termina en 422: ningún dato inválido puede terminar en 500 (RN-18)."""
    respuesta = await cliente_auth.post("/auth/registro", json=cuerpo)
    assert respuesta.status_code == 422, f"{motivo}: {respuesta.text}"
    total = (await sesion_pruebas.execute(select(func.count()).select_from(Usuario))).scalar_one()
    assert total == 0  # ninguna fila escrita antes de validar el contrato


async def test_registro_exitoso_deja_filas_atomicas(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """201 con usuario hasheado + rol CLIENTE + intento inicial (RN-02, US-003)."""
    respuesta = await cliente_auth.post(
        "/auth/registro",
        json={"email": CORREO_NUEVO, "nombre": NOMBRE_NUEVO, "password": CONTRASENA_NUEVA},
    )
    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["email"] == CORREO_NUEVO
    assert cuerpo["rol"] == "CLIENTE"

    usuario = (await sesion_pruebas.execute(select(Usuario))).scalar_one()
    assert usuario.email == CORREO_NUEVO
    assert usuario.activo is True
    assert usuario.debe_cambiar_password is False
    roles = (await sesion_pruebas.execute(select(AsignacionRol))).scalars().all()
    assert [rol.rol for rol in roles] == ["CLIENTE"]  # asignación abierta por defecto
    intentos = (await sesion_pruebas.execute(select(IntentoAcceso))).scalars().all()
    assert len(intentos) == 1 and intentos[0].exito is True  # registro inicial de acceso


async def test_registro_no_expone_la_contrasena(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """Ni el cuerpo de la respuesta ni la base contienen el texto plano (RN-18)."""
    respuesta = await cliente_auth.post(
        "/auth/registro",
        json={"email": CORREO_NUEVO, "nombre": NOMBRE_NUEVO, "password": CONTRASENA_NUEVA},
    )
    assert CONTRASENA_NUEVA not in respuesta.text
    usuario = (await sesion_pruebas.execute(select(Usuario))).scalar_one()
    assert usuario.password_hash.startswith("$2b$")
    assert usuario.password_hash != CONTRASENA_NUEVA


async def test_registro_email_duplicado_responde_409(
    cliente_auth: AsyncClient, sesion_pruebas: AsyncSession
) -> None:
    """Unicidad garantizada por la base (RN-01): IntegrityError → 409 con mensaje propio."""
    primera = await cliente_auth.post(
        "/auth/registro",
        json={"email": CORREO_NUEVO, "nombre": NOMBRE_NUEVO, "password": CONTRASENA_NUEVA},
    )
    assert primera.status_code == 201
    segunda = await cliente_auth.post(
        "/auth/registro",
        json={"email": CORREO_NUEVO, "nombre": "Otro Nombre", "password": "otra-clave-9"},
    )
    assert segunda.status_code == 409, segunda.text
    assert "mensaje" in segunda.text.lower() or segunda.json() != {}
    total_usuarios = (
        await sesion_pruebas.execute(select(func.count()).select_from(Usuario))
    ).scalar_one()
    total_roles = (
        await sesion_pruebas.execute(select(func.count()).select_from(AsignacionRol))
    ).scalar_one()
    assert total_usuarios == 1 and total_roles == 1  # sin filas a medias del segundo intento
