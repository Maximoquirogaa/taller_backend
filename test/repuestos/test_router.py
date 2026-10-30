"""Tests de endpoints HTTP y control de acceso del módulo repuestos (Task 4.2, C-05).

Verifica:
- `GET /repuestos`: paginación, filtros `q`, parámetros ligados y seguridad contra injection (US-017, RN-18).
- `POST /repuestos`: alta con stock inicial como movimiento atómico (US-018, RN-14), 409 en duplicados (RN-01).
- `PATCH /repuestos/{id}`: modificación con `exclude_unset`, historial al cambiar precio (RN-20),
  rechazo de `stock` directo (422, RN-14).
- `DELETE /repuestos/{id}`: baja lógica (US-020, RN-16) y re-registro de código (RN-01).
- `POST /repuestos/{id}/reponer`: incremento de stock con movimiento (US-021, RN-14).
- `GET /repuestos/{id}/movimientos` y `.../precios`: auditoría (US-022).
- RBAC: permisos por rol (ADMIN para escrituras, RECEPCION/MECANICO para consultas) y 401 sin sesión.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.repuestos.models import Repuesto
from test.repuestos.conftest import autenticar_usuario


async def test_alta_repuesto_admin_exitoso_y_duplicado(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /repuestos: ADMIN crea repuesto con stock inicial (201) y código duplicado da 409 (US-018, RN-01)."""
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")

    payload = {
        "codigo": "FIL-ACE-01",
        "descripcion": "Filtro de aceite motor",
        "precio": "8500.00",
        "stock_inicial": 10,
    }
    res = await cliente_http.post("/repuestos", json=payload)
    assert res.status_code == 201
    datos = res.json()
    assert datos["codigo"] == "FIL-ACE-01"
    assert datos["stock"] == 10
    assert Decimal(str(datos["precio"])) == Decimal("8500.00")
    repuesto_id = datos["id"]

    # Verifica movimiento de stock inicial registrado
    res_movs = await cliente_http.get(f"/repuestos/{repuesto_id}/movimientos")
    assert res_movs.status_code == 200
    movs = res_movs.json()
    assert len(movs) == 1
    assert movs[0]["cantidad"] == 10
    assert movs[0]["motivo"] == "Stock inicial"

    # Conflicto por código duplicado activo (RN-01)
    res_dup = await cliente_http.post("/repuestos", json=payload)
    assert res_dup.status_code == 409


async def test_alta_repuesto_rechaza_campos_extra(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /repuestos: extra='forbid' rechaza campos no autorizados con 422."""
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")

    payload = {
        "codigo": "EXTRA-01",
        "descripcion": "Repuesto",
        "precio": "100.00",
        "campo_desconocido": "invalido",
    }
    res = await cliente_http.post("/repuestos", json=payload)
    assert res.status_code == 422


async def test_alta_repuesto_permisos_mecanico_rechazado(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /repuestos: MECANICO no tiene permisos para crear repuestos (403)."""
    await autenticar_usuario(cliente_http, sesion_db, "mecanico@taller.test", "MECANICO")

    payload = {
        "codigo": "MEC-01",
        "descripcion": "Repuesto",
        "precio": "500.00",
    }
    res = await cliente_http.post("/repuestos", json=payload)
    assert res.status_code == 403


async def test_catalogo_busqueda_paginacion_y_seguridad(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """GET /repuestos: búsqueda por q con parámetros ligados y paginación (US-017, RN-18)."""
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")

    # Insertamos repuestos directamente en la base
    sesion_db.add(Repuesto(codigo="BUJ-01", descripcion="Bujía de cobre", precio=Decimal("1500.00"), stock=10))
    sesion_db.add(Repuesto(codigo="BUJ-02", descripcion="Bujía de platino", precio=Decimal("3000.00"), stock=6))
    sesion_db.add(Repuesto(codigo="PAS-01", descripcion="Pastillas delanteras", precio=Decimal("8000.00"), stock=4))
    await sesion_db.commit()

    # Búsqueda coincidente
    res = await cliente_http.get("/repuestos?q=bujia&page=1&size=10")
    assert res.status_code == 200
    datos = res.json()
    assert datos["total"] == 2
    assert len(datos["items"]) == 2

    # Parámetros ligados / Intento de SQL injection (RN-18)
    res_sqli = await cliente_http.get("/repuestos?q=' OR 1=1 --")
    assert res_sqli.status_code == 200
    datos_sqli = res_sqli.json()
    assert datos_sqli["total"] == 0
    assert datos_sqli["items"] == []


async def test_actualizar_repuesto_precio_e_historial(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """PATCH /repuestos/{id}: si cambia el precio, crea historial en la misma transacción (US-019, RN-20)."""
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")

    rep = Repuesto(codigo="PRIC-01", descripcion="Aceite 1L", precio=Decimal("8000.00"), stock=5)
    sesion_db.add(rep)
    await sesion_db.commit()

    # Modificación de precio
    res = await cliente_http.patch(f"/repuestos/{rep.id}", json={"precio": "8500.00"})
    assert res.status_code == 200
    assert Decimal(str(res.json()["precio"])) == Decimal("8500.00")

    # Verifica línea en historial
    res_hist = await cliente_http.get(f"/repuestos/{rep.id}/precios")
    assert res_hist.status_code == 200
    hist = res_hist.json()
    assert len(hist) == 1
    assert Decimal(str(hist[0]["precio_anterior"])) == Decimal("8000.00")
    assert Decimal(str(hist[0]["precio_nuevo"])) == Decimal("8500.00")

    # Modificación exclusiva de descripción NO añade línea al historial
    res_desc = await cliente_http.patch(f"/repuestos/{rep.id}", json={"descripcion": "Aceite 1L Premium"})
    assert res_desc.status_code == 200

    res_hist2 = await cliente_http.get(f"/repuestos/{rep.id}/precios")
    assert len(res_hist2.json()) == 1

    # Intento de editar stock directamente en PATCH es rechazado con 422 (RN-14)
    res_stock = await cliente_http.patch(f"/repuestos/{rep.id}", json={"stock": 100})
    assert res_stock.status_code == 422


async def test_reponer_stock_exitoso(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """POST /repuestos/{id}/reponer: suma stock y anota movimiento (US-021, RN-14)."""
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")

    rep = Repuesto(codigo="REP-01", descripcion="Líquido de frenos", precio=Decimal("3500.00"), stock=2)
    sesion_db.add(rep)
    await sesion_db.commit()

    res = await cliente_http.post(f"/repuestos/{rep.id}/reponer", json={"cantidad": 5, "motivo": "Compra distribuidora"})
    assert res.status_code == 200
    assert res.json()["stock"] == 7

    res_movs = await cliente_http.get(f"/repuestos/{rep.id}/movimientos")
    assert res_movs.status_code == 200
    movs = res_movs.json()
    assert len(movs) == 1
    assert movs[0]["cantidad"] == 5
    assert movs[0]["motivo"] == "Compra distribuidora"


async def test_baja_logica_y_re_registro(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
) -> None:
    """DELETE /repuestos/{id}: baja lógica y liberación del código para re-registro (US-020, RN-01, RN-16)."""
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")

    res_alta = await cliente_http.post(
        "/repuestos",
        json={"codigo": "DEL-01", "descripcion": "Repuesto a borrar", "precio": "100.00", "stock_inicial": 0},
    )
    rep_id = res_alta.json()["id"]

    # Baja lógica
    res_del = await cliente_http.delete(f"/repuestos/{rep_id}")
    assert res_del.status_code == 204

    # Ya no aparece en el catálogo
    res_get = await cliente_http.get(f"/repuestos/{rep_id}/movimientos")
    assert res_get.status_code == 404

    # Re-registro con el mismo código es permitido (RN-01)
    res_re = await cliente_http.post(
        "/repuestos",
        json={"codigo": "DEL-01", "descripcion": "Repuesto re-registrado", "precio": "120.00", "stock_inicial": 1},
    )
    assert res_re.status_code == 201


async def test_rutas_protegidas_sin_autenticacion(cliente_http: AsyncClient) -> None:
    """Rutas protegidas sin cookie de sesión deben responder 401."""
    res_get = await cliente_http.get("/repuestos")
    assert res_get.status_code == 401

    res_post = await cliente_http.post("/repuestos", json={"codigo": "X", "descripcion": "Y", "precio": "10.00"})
    assert res_post.status_code == 401
