"""Tests de integración para los endpoints de clientes y vehículos (Tasks 3.1, 3.2, 3.3).

Verifica:
- `POST /clientes`: alta sin usuario (RECEPCION/ADMIN), 409 por documento repetido, 422 por contrato estricto.
- `GET /clientes/{id}`: detalle de cliente con vehículos precargados, 404 si no existe.
- `POST /clientes/{id}/vehiculos`: alta de vehículo, 404 cliente, 409 patente activa repetida, 422 año fuera de rango.
- `DELETE /vehiculos/{id}`: baja lógica (204), liberación de patente para re-registro.
- `GET /mis-vehiculos`: aislamiento estricto por usuario autenticado (RN-17).
- Hereda control de cambio obligatorio de contraseña (DD-10, RN-06).
- Peticiones sin autenticación responden 401 (DD-04).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.mensajes_auth import NOMBRE_COOKIE_SESION
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.usuarios.models import AsignacionRol, Usuario
from main import settings
from test.clientes.conftest import autenticar_cliente


async def test_alta_cliente_exitoso_y_duplicado(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """POST /clientes: RECEPCION crea cliente (201) y documento duplicado da 409 (US-012, RN-01)."""
    await autenticar_cliente(cliente_http, sesion_db, "recepcion@example.com", "RECEPCION")

    payload = {"nombre": "Juan Pérez", "documento": "28111222", "telefono": "11-4444-5555"}
    res = await cliente_http.post("/clientes", json=payload)
    assert res.status_code == 201
    datos = res.json()
    assert datos["id"] is not None
    assert datos["nombre"] == "Juan Pérez"
    assert datos["documento"] == "28111222"
    assert datos["usuario_id"] is None

    res_dup = await cliente_http.post("/clientes", json=payload)
    assert res_dup.status_code == 409
    assert "documento" in res_dup.json()["detail"].lower()


async def test_alta_cliente_rechaza_campos_extra(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """POST /clientes: extra="forbid" rechaza campos no contemplados con 422."""
    await autenticar_cliente(cliente_http, sesion_db, "admin@example.com", "ADMIN")

    payload = {
        "nombre": "Ana Gomez",
        "documento": "35123456",
        "telefono": "11-2222-3333",
        "campo_invalido": "hack",
    }
    res = await cliente_http.post("/clientes", json=payload)
    assert res.status_code == 422


async def test_alta_cliente_permisos_mecanico_rechazado(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """POST /clientes: MECANICO no tiene permiso para crear clientes (403)."""
    await autenticar_cliente(cliente_http, sesion_db, "mecanico@example.com", "MECANICO")

    payload = {"nombre": "Pedro", "documento": "12345678", "telefono": "111"}
    res = await cliente_http.post("/clientes", json=payload)
    assert res.status_code == 403


async def test_detalle_cliente_con_vehiculos_precargados(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """GET /clientes/{id}: detalle con vehículos sin N+1 (US-016)."""
    await autenticar_cliente(cliente_http, sesion_db, "recepcion@example.com", "RECEPCION")

    c = Cliente(nombre="Laura Ramos", documento="30999888", telefono="4444")
    sesion_db.add(c)
    await sesion_db.flush()

    v1 = Vehiculo(cliente_id=c.id, patente="AA111BB", marca="Toyota", modelo="Yaris", anio=2021)
    v2 = Vehiculo(cliente_id=c.id, patente="CC222DD", marca="Ford", modelo="Ka", anio=2019)
    sesion_db.add_all([v1, v2])
    await sesion_db.commit()

    res = await cliente_http.get(f"/clientes/{c.id}")
    assert res.status_code == 200
    datos = res.json()
    assert datos["id"] == c.id
    assert len(datos["vehiculos"]) == 2
    patentes = [v["patente"] for v in datos["vehiculos"]]
    assert "AA111BB" in patentes
    assert "CC222DD" in patentes

    res_404 = await cliente_http.get("/clientes/99999")
    assert res_404.status_code == 404


async def test_alta_vehiculo_y_baja_logica_con_re_registro(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """POST /clientes/{id}/vehiculos y DELETE /vehiculos/{id} (US-013, US-014, RN-01, RN-16)."""
    await autenticar_cliente(cliente_http, sesion_db, "recepcion@example.com", "RECEPCION")

    c1 = Cliente(nombre="Cliente 1", documento="10000001", telefono="111")
    c2 = Cliente(nombre="Cliente 2", documento="10000002", telefono="222")
    sesion_db.add_all([c1, c2])
    await sesion_db.commit()

    payload_v = {"patente": "ABC123ZZ", "marca": "Peugeot", "modelo": "208", "anio": 2022}
    res_v = await cliente_http.post(f"/clientes/{c1.id}/vehiculos", json=payload_v)
    assert res_v.status_code == 201
    vehiculo_id = res_v.json()["id"]

    # Año fuera de rango → 422
    res_anio = await cliente_http.post(f"/clientes/{c1.id}/vehiculos", json={**payload_v, "anio": 1940})
    assert res_anio.status_code == 422

    # Patente activa repetida en otro cliente → 409 (RN-01)
    res_rep = await cliente_http.post(f"/clientes/{c2.id}/vehiculos", json=payload_v)
    assert res_rep.status_code == 409

    # Cliente inexistente → 404
    res_cli_404 = await cliente_http.post("/clientes/99999/vehiculos", json=payload_v)
    assert res_cli_404.status_code == 404

    # Baja lógica
    res_del = await cliente_http.delete(f"/vehiculos/{vehiculo_id}")
    assert res_del.status_code == 204

    # Segunda baja → 404 (ya está dado de baja)
    res_del_repetida = await cliente_http.delete(f"/vehiculos/{vehiculo_id}")
    assert res_del_repetida.status_code == 404

    # Re-registro de la misma patente en cliente 2 ahora es exitoso (índice parcial)
    res_rereg = await cliente_http.post(f"/clientes/{c2.id}/vehiculos", json=payload_v)
    assert res_rereg.status_code == 201


async def test_mis_vehiculos_aislamiento_estricto(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """GET /mis-vehiculos: un cliente solo ve los suyos (US-015, RN-17)."""
    u_laura = await autenticar_cliente(cliente_http, sesion_db, "laura@example.com", "CLIENTE", "Laura")
    c_laura = Cliente(usuario_id=u_laura.id, nombre="Laura", documento="20999111", telefono="111")

    c_jorge = Cliente(nombre="Jorge", documento="15888222", telefono="222")
    sesion_db.add_all([c_laura, c_jorge])
    await sesion_db.flush()

    v_laura = Vehiculo(cliente_id=c_laura.id, patente="LAU111", marca="Ford", modelo="Fiesta", anio=2016)
    v_jorge = Vehiculo(cliente_id=c_jorge.id, patente="JOR222", marca="Chevrolet", modelo="Corsa", anio=2010)
    sesion_db.add_all([v_laura, v_jorge])
    await sesion_db.commit()

    res = await cliente_http.get("/mis-vehiculos")
    assert res.status_code == 200
    vehiculos = res.json()
    assert len(vehiculos) == 1
    assert vehiculos[0]["patente"] == "LAU111"


async def test_mis_vehiculos_sin_ficha_devuelve_vacio(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """GET /mis-vehiculos: usuario sin ficha de cliente asociada devuelve lista vacía con 200."""
    await autenticar_cliente(cliente_http, sesion_db, "sin_auto@example.com", "CLIENTE")

    res = await cliente_http.get("/mis-vehiculos")
    assert res.status_code == 200
    assert res.json() == []


async def test_rutas_protegidas_sin_autenticacion_dan_401(
    cliente_http: AsyncClient,
) -> None:
    """Petición sin cookie de sesión responde 401 en todas las rutas protegidas (DD-04)."""
    assert (await cliente_http.get("/mis-vehiculos")).status_code == 401
    assert (await cliente_http.get("/clientes/1")).status_code == 401
    assert (await cliente_http.post("/clientes", json={"nombre": "a", "documento": "1", "telefono": "1"})).status_code == 401
    assert (await cliente_http.delete("/vehiculos/1")).status_code == 401


async def test_rutas_bloqueadas_si_cambio_password_pendiente(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Usuario con debe_cambiar_password=True recibe 403 en el grupo protegido (DD-10, RN-06)."""
    hash_pass = await security.hash_password("clave-temp-123")
    usuario = Usuario(
        email="pendiente@example.com",
        nombre="Pendiente",
        password_hash=hash_pass,
        activo=True,
        debe_cambiar_password=True,
    )
    sesion_db.add(usuario)
    await sesion_db.flush()

    sesion_db.add(AsignacionRol(usuario_id=usuario.id, rol="RECEPCION"))
    await sesion_db.commit()

    token = security.crear_token_acceso(
        id_usuario=usuario.id,
        roles=["RECEPCION"],
        secreto=settings.secret_key,
        expira_en_segundos=1800,
    )
    cliente_http.cookies.set(NOMBRE_COOKIE_SESION, token)

    res = await cliente_http.get("/clientes/1")
    assert res.status_code == 403
