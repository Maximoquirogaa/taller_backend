"""Tests de endpoints HTTP del módulo órdenes (Tasks 3.1, 3.2, 3.5, 3.6, 4.x, 5.x, 6.x, 7.x).

Cubre: apertura `POST /ordenes`, listado `GET /ordenes`, detalle
`GET /ordenes/{id}`, catálogo `GET /estados-orden` y órdenes propias
`GET /mis-ordenes`, con sus códigos de estado, RBAC y contratos (422/403/401/404/409/405).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.ordenes.models import (
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)
from app.modules.repuestos.models import MovimientoStock, Repuesto
from app.modules.usuarios.models import Usuario
from app.core import security
from app.core.mensajes_auth import NOMBRE_COOKIE_SESION
from main import settings
from test.ordenes.conftest import (
    autenticar_usuario,
    crear_cliente,
    crear_repuesto,
    crear_vehiculo,
    insertar_catalogo,
)

ROLES_STAFF = ("ADMIN", "RECEPCION", "MECANICO")


async def _crear_usuario(sesion_db: AsyncSession, email: str, rol: str) -> Usuario:
    """Crea un usuario con rol asignado y lo confirma; devuelve el usuario."""
    usuario = Usuario(
        email=email, nombre=email.split("@")[0], password_hash="x",
        activo=True, debe_cambiar_password=False,
    )
    sesion_db.add(usuario)
    await sesion_db.flush()
    asignacion = AsignacionRol(usuario_id=usuario.id, rol=rol)
    sesion_db.add(asignacion)
    await sesion_db.commit()
    await sesion_db.refresh(usuario)
    return usuario


async def _autenticar_y_cliente(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
    email: str,
    rol: str,
    *,
    documento: str,
) -> tuple[object, object]:
    """Autentica y crea la ficha de cliente ligada al usuario; devuelve ambos.

    `autenticar_usuario` ya crea el usuario y lo confirma; se reusa su id para
    ligar la ficha de cliente (evita duplicar el usuario).
    """
    usuario = await autenticar_usuario(cliente_http, sesion_db, email, rol)
    cliente = await crear_cliente(
        sesion_db, nombre="Usuario", documento=documento, usuario_id=usuario.id
    )
    return usuario, cliente


async def _insertar_orden(
    sesion_db: AsyncSession,
    *,
    vehiculo_id: int,
    estado: str = "PENDIENTE",
    falla: str = "Falla",
    total: str = "0.00",
    mecanico_id: int | None = None,
    items: list[tuple[int, int, str]] | None = None,
    historial: list[tuple[str | None, str, int | None]] | None = None,
) -> int:
    """Inserta una orden directamente (setup de pruebas de lectura) y devuelve su id."""
    orden = OrdenTrabajo(
        vehiculo_id=vehiculo_id,
        estado=estado,
        falla=falla,
        total=Decimal(total),
        mecanico_id=mecanico_id,
    )
    sesion_db.add(orden)
    await sesion_db.flush()
    for repuesto_id, cantidad, precio in (items or []):
        sesion_db.add(
            ItemOrden(
                orden_id=orden.id,
                repuesto_id=repuesto_id,
                cantidad=cantidad,
                precio_unitario=Decimal(precio),
            )
        )
    for desde_estado, hasta_estado, usuario_id in (historial or []):
        sesion_db.add(
            HistorialEstadoOrden(
                orden_id=orden.id,
                desde_estado=desde_estado,
                hasta_estado=hasta_estado,
                usuario_id=usuario_id,
                cuando=datetime.now(UTC),
            )
        )
    await sesion_db.commit()
    await sesion_db.refresh(orden)
    return orden.id


# ── POST /ordenes ──────────────────────────────────────────────────────────


async def test_apertura_orden_exitoso(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """RECEPCION abre orden con dos repuestos → 201, PENDIENTE, precios copiados,
    total del servidor y historial nulo → PENDIENTE (US-023, RN-10)."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    r1 = await crear_repuesto(sesion_db, codigo="R1", precio="100.00")
    r2 = await crear_repuesto(sesion_db, codigo="R2", precio="200.00")

    res = await cliente_http.post(
        "/ordenes",
        json={
            "vehiculo_id": vehiculo.id,
            "falla": "Ruido en el motor",
            "items": [
                {"repuesto_id": r1.id, "cantidad": 2},
                {"repuesto_id": r2.id, "cantidad": 1},
            ],
        },
    )
    assert res.status_code == 201
    datos = res.json()
    assert datos["estado"] == "PENDIENTE"
    assert Decimal(str(datos["total"])) == Decimal("400.00")
    items = {item["repuesto_id"]: item for item in datos["items"]}
    assert items[r1.id]["precio_unitario"] == "100.00"
    assert items[r1.id]["cantidad"] == 2
    assert items[r2.id]["precio_unitario"] == "200.00"
    assert items[r2.id]["cantidad"] == 1
    assert len(datos["historial"]) == 1
    assert datos["historial"][0]["desde_estado"] is None
    assert datos["historial"][0]["hasta_estado"] == "PENDIENTE"
    assert "password_hash" not in datos


async def test_apertura_409_catalogo_vacio(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Catálogo vacío → 409 (RN-19; la migración deja la tabla vacía, DD-01)."""
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")

    res = await cliente_http.post(
        "/ordenes",
        json={"vehiculo_id": vehiculo.id, "falla": "Falla", "items": [{"repuesto_id": 1, "cantidad": 1}]},
    )
    assert res.status_code == 409


async def test_apertura_422_campos_prohibidos(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """`precio_unitario`, `total`, `estado` y campos extra en el cuerpo → 422 (extra="forbid")."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuesto = await crear_repuesto(sesion_db, codigo="R1", precio="100.00")

    base = {
        "vehiculo_id": vehiculo.id,
        "falla": "Falla",
        "items": [{"repuesto_id": repuesto.id, "cantidad": 1}],
    }
    for campo, valor in (
        ("precio_unitario", "50.00"),
        ("total", "50.00"),
        ("estado", "PENDIENTE"),
        ("campo_inexistente", "x"),
    ):
        res = await cliente_http.post("/ordenes", json={**base, campo: valor})
        assert res.status_code == 422, f"campo {campo!r} debe ser 422"


async def test_apertura_422_items_vacio(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """`items=[]` viola min_length=1 → 422 sin abrir el UoW."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")

    res = await cliente_http.post(
        "/ordenes",
        json={"vehiculo_id": vehiculo.id, "falla": "Falla", "items": []},
    )
    assert res.status_code == 422


async def test_apertura_409_repuesto_repetido(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Mismo repuesto dos veces → 409 (UNIQUE compuesto, RN-10)."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuesto = await crear_repuesto(sesion_db, codigo="R1", precio="100.00")

    res = await cliente_http.post(
        "/ordenes",
        json={
            "vehiculo_id": vehiculo.id,
            "falla": "Falla",
            "items": [
                {"repuesto_id": repuesto.id, "cantidad": 1},
                {"repuesto_id": repuesto.id, "cantidad": 2},
            ],
        },
    )
    assert res.status_code == 409


async def test_apertura_403_sin_rol_escritura(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """MECANICO y CLIENTE no pueden abrir órdenes → 403."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")

    for rol in ("MECANICO", "CLIENTE"):
        await autenticar_usuario(cliente_http, sesion_db, f"{rol.lower()}@taller.test", rol)
        res = await cliente_http.post(
            "/ordenes",
            json={
                "vehiculo_id": vehiculo.id,
                "falla": "Falla",
                "items": [{"repuesto_id": 1, "cantidad": 1}],
            },
        )
        assert res.status_code == 403, f"{rol} debe recibir 403"


async def test_apertura_401_sin_cookie(cliente_http: AsyncClient) -> None:
    """Sin cookie de sesión → 401."""
    res = await cliente_http.post(
        "/ordenes",
        json={"vehiculo_id": 1, "falla": "Falla", "items": [{"repuesto_id": 1, "cantidad": 1}]},
    )
    assert res.status_code == 401


# ── GET /ordenes ───────────────────────────────────────────────────────────


async def _crear_ordenes_ejemplo(sesion_db: AsyncSession, vehiculo_id: int) -> list[int]:
    ids = []
    for i, estado in enumerate(["PENDIENTE", "TERMINADA", "PENDIENTE"]):
        ids.append(
            await _insertar_orden(
                sesion_db,
                vehiculo_id=vehiculo_id,
                estado=estado,
                falla=f"Falla {i}",
                total="0.00",
            )
        )
    return ids


async def test_listado_ordenes_ok(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """ADMIN/RECEPCION/MECANICO listan → 200 con {items,total,page,size,pages}, descendente."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    await _crear_ordenes_ejemplo(sesion_db, vehiculo.id)

    res = await cliente_http.get("/ordenes?page=1&size=10")
    assert res.status_code == 200
    datos = res.json()
    assert set(datos) == {"items", "total", "page", "size", "pages"}
    assert datos["total"] == 3
    assert len(datos["items"]) == 3
    assert [i["falla"] for i in datos["items"]] == ["Falla 2", "Falla 1", "Falla 0"]


async def test_listado_filtro_estado(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """`?estado=PENDIENTE` solo devuelve pendientes con total coherente."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    await _crear_ordenes_ejemplo(sesion_db, vehiculo.id)

    res = await cliente_http.get("/ordenes?estado=PENDIENTE")
    assert res.status_code == 200
    datos = res.json()
    assert datos["total"] == 2
    assert all(i["estado"] == "PENDIENTE" for i in datos["items"])


async def test_listado_estado_fuera_de_contrato_422(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """`?estado=INVENTADO` está fuera del contrato → 422 (D6)."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")

    res = await cliente_http.get("/ordenes?estado=INVENTADO")
    assert res.status_code == 422


async def test_listado_paginacion_invalida_422(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """`?page=0` y `?size=500` → 422."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")

    res = await cliente_http.get("/ordenes?page=0")
    assert res.status_code == 422
    res = await cliente_http.get("/ordenes?size=500")
    assert res.status_code == 422


async def test_listado_cliente_403(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """CLIENTE no puede usar el tablero → 403."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "cliente@taller.test", "CLIENTE")

    res = await cliente_http.get("/ordenes")
    assert res.status_code == 403


async def test_listado_sin_cookie_401(cliente_http: AsyncClient) -> None:
    """Sin cookie → 401."""
    res = await cliente_http.get("/ordenes")
    assert res.status_code == 401


# ── GET /ordenes/{id} ──────────────────────────────────────────────────────


async def test_detalle_staff_ve_cualquiera(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """ADMIN/RECEPCION/MECANICO ven cualquier orden → 200 con vehículo, cliente, ítems, historial."""
    await insertar_catalogo(sesion_db)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    r1 = await crear_repuesto(sesion_db, codigo="R1", precio="100.00")
    orden_id = await _insertar_orden(
        sesion_db,
        vehiculo_id=vehiculo.id,
        estado="PENDIENTE",
        falla="Falla",
        total="100.00",
        items=[(r1.id, 1, "100.00")],
        historial=[(None, "PENDIENTE", None)],
    )

    for rol in ROLES_STAFF:
        await autenticar_usuario(cliente_http, sesion_db, f"{rol.lower()}@taller.test", rol)
        res = await cliente_http.get(f"/ordenes/{orden_id}")
        assert res.status_code == 200, f"{rol} debe ver la orden"
        datos = res.json()
        assert datos["vehiculo"]["patente"] == "AAA111"
        assert datos["cliente"]["nombre"] == "Ana"
        assert len(datos["items"]) == 1
        assert datos["items"][0]["repuesto"]["codigo"] == "R1"
        assert len(datos["historial"]) == 1


async def test_detalle_cliente_dueno_200(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """El CLIENTE dueño del vehículo ve su orden → 200 (RN-17)."""
    await insertar_catalogo(sesion_db)
    usuario, cliente = await _autenticar_y_cliente(
        cliente_http, sesion_db, "cliente@taller.test", "CLIENTE", documento="1"
    )
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    orden_id = await _insertar_orden(
        sesion_db, vehiculo_id=vehiculo.id, estado="PENDIENTE", falla="Falla", total="0.00"
    )

    res = await cliente_http.get(f"/ordenes/{orden_id}")
    assert res.status_code == 200


async def test_detalle_cliente_ajeno_403(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """CLIENTE ajeno → 403 sin datos de la orden (RN-17)."""
    await insertar_catalogo(sesion_db)
    _, cliente_prop = await _autenticar_y_cliente(
        cliente_http, sesion_db, "propio@taller.test", "CLIENTE", documento="1"
    )
    _, cliente_ajeno = await _autenticar_y_cliente(
        cliente_http, sesion_db, "ajeno@taller.test", "CLIENTE", documento="2"
    )
    vehiculo_prop = await crear_vehiculo(sesion_db, cliente_id=cliente_prop.id, patente="PPP111")
    orden_id = await _insertar_orden(
        sesion_db, vehiculo_id=vehiculo_prop.id, estado="PENDIENTE", falla="Falla", total="0.00"
    )

    # La cookie quedó en el usuario ajeno (último autenticar_usuario)
    res = await cliente_http.get(f"/ordenes/{orden_id}")
    assert res.status_code == 403


async def test_detalle_inexistente_404(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Id inexistente → 404."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")

    res = await cliente_http.get("/ordenes/999999")
    assert res.status_code == 404


async def test_detalle_sin_cookie_401(cliente_http: AsyncClient) -> None:
    """Sin cookie → 401."""
    res = await cliente_http.get("/ordenes/1")
    assert res.status_code == 401


async def test_c15_detalle_mismo_numero_de_consultas(
    cliente_http: AsyncClient,
    sesion_db: AsyncSession,
    motor_pruebas: AsyncEngine,
) -> None:
    """C-15: el detalle de 2 y 4 ítems hace la misma cantidad de consultas (≤ 6 SELECT)."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    repuestos = [
        await crear_repuesto(sesion_db, codigo=f"R{i}", precio=f"{100 * (i + 1)}.00")
        for i in range(4)
    ]

    orden_2 = await _insertar_orden(
        sesion_db,
        vehiculo_id=vehiculo.id,
        estado="PENDIENTE",
        falla="2 items",
        total="0.00",
        items=[(repuestos[0].id, 1, "100.00"), (repuestos[1].id, 1, "200.00")],
    )
    orden_4 = await _insertar_orden(
        sesion_db,
        vehiculo_id=vehiculo.id,
        estado="PENDIENTE",
        falla="4 items",
        total="0.00",
        items=[
            (repuestos[0].id, 1, "100.00"),
            (repuestos[1].id, 1, "200.00"),
            (repuestos[2].id, 1, "300.00"),
            (repuestos[3].id, 1, "400.00"),
        ],
    )

    contador = {"n": 0}

    def listener(conn, cursor, statement, parameters, context, executemany) -> None:
        contador["n"] += 1

    event.listen(motor_pruebas.sync_engine, "before_cursor_execute", listener)
    try:
        contador["n"] = 0
        res2 = await cliente_http.get(f"/ordenes/{orden_2}")
        consultas_2 = contador["n"]

        contador["n"] = 0
        res4 = await cliente_http.get(f"/ordenes/{orden_4}")
        consultas_4 = contador["n"]
    finally:
        event.remove(motor_pruebas.sync_engine, "before_cursor_execute", listener)

    assert res2.status_code == 200 and res4.status_code == 200
    assert consultas_2 == consultas_4, f"{consultas_2} vs {consultas_4} consultas"
    assert consultas_2 <= 6, f"demasiadas consultas: {consultas_2}"


# ── GET /estados-orden ─────────────────────────────────────────────────────


async def test_estados_orden_ok(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Catálogo cargado → 200 ordenado por posición, finales marcados (US-029, RN-19)."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "cliente@taller.test", "CLIENTE")

    res = await cliente_http.get("/estados-orden")
    assert res.status_code == 200
    estados = res.json()
    assert [e["codigo"] for e in estados] == ["PENDIENTE", "EN_REPARACION", "TERMINADA", "CANCELADA"]
    assert [e["posicion"] for e in estados] == [1, 2, 3, 4]
    assert {e["codigo"] for e in estados if e["es_final"]} == {"TERMINADA", "CANCELADA"}


async def test_estados_orden_vacio(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Catálogo vacío → 200 con [] (DD-01)."""
    await autenticar_usuario(cliente_http, sesion_db, "cliente@taller.test", "CLIENTE")

    res = await cliente_http.get("/estados-orden")
    assert res.status_code == 200
    assert res.json() == []


async def test_estados_orden_cualquier_autenticado(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Cualquier autenticado (incluido CLIENTE) → 200."""
    await insertar_catalogo(sesion_db)
    for rol in ("ADMIN", "RECEPCION", "MECANICO", "CLIENTE"):
        await autenticar_usuario(cliente_http, sesion_db, f"{rol.lower()}@taller.test", rol)
        res = await cliente_http.get("/estados-orden")
        assert res.status_code == 200, f"{rol} debe recibir 200"


async def test_estados_orden_sin_cookie_401(cliente_http: AsyncClient) -> None:
    """Sin cookie → 401."""
    res = await cliente_http.get("/estados-orden")
    assert res.status_code == 401


async def test_estados_orden_metodo_escritura_405(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Método de escritura sobre /estados-orden → 405."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")

    for metodo in ("post", "put", "delete"):
        res = await getattr(cliente_http, metodo)("/estados-orden")
        assert res.status_code == 405, f"{metodo.upper()} debe ser 405"


# ── GET /mis-ordenes ───────────────────────────────────────────────────────


async def test_mis_ordenes_cliente_propias(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """CLIENTE con dos vehículos ve sólo sus órdenes paginadas (RN-17)."""
    await insertar_catalogo(sesion_db)
    usuario, cliente = await _autenticar_y_cliente(
        cliente_http, sesion_db, "cliente@taller.test", "CLIENTE", documento="1"
    )
    v1 = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="V11111")
    v2 = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="V22222")
    await _insertar_orden(sesion_db, vehiculo_id=v1.id, estado="PENDIENTE", total="10.00")
    await _insertar_orden(sesion_db, vehiculo_id=v2.id, estado="TERMINADA", total="20.00")

    res = await cliente_http.get("/mis-ordenes?page=1&size=10")
    assert res.status_code == 200
    datos = res.json()
    assert datos["total"] == 2
    assert len(datos["items"]) == 2


async def test_mis_ordenes_no_ve_ajenas(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Otro CLIENTE no ve órdenes ajenas y su total es 0."""
    await insertar_catalogo(sesion_db)
    _, cliente1 = await _autenticar_y_cliente(
        cliente_http, sesion_db, "cliente1@taller.test", "CLIENTE", documento="1"
    )
    v1 = await crear_vehiculo(sesion_db, cliente_id=cliente1.id, patente="PROP111")
    await _insertar_orden(sesion_db, vehiculo_id=v1.id, estado="PENDIENTE", total="10.00")

    # Cambiar la cookie al cliente 2 (que no tiene órdenes)
    await _autenticar_y_cliente(
        cliente_http, sesion_db, "cliente2@taller.test", "CLIENTE", documento="2"
    )
    res = await cliente_http.get("/mis-ordenes")
    assert res.status_code == 200
    datos = res.json()
    assert datos["total"] == 0
    assert datos["items"] == []


async def test_mis_ordenes_sin_ficha_de_cliente(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Usuario sin ficha de cliente → 200 con items=[], total=0, pages=1 (D9)."""
    await insertar_catalogo(sesion_db)
    # autenticar_usuario crea al usuario pero no hay ficha de cliente ligada
    await autenticar_usuario(cliente_http, sesion_db, "staffsinficha@taller.test", "MECANICO")

    res = await cliente_http.get("/mis-ordenes")
    assert res.status_code == 200
    datos = res.json()
    assert datos["items"] == []
    assert datos["total"] == 0
    assert datos["pages"] == 1


async def test_mis_ordenes_page_0_422(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """`?page=0` → 422."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "cliente@taller.test", "CLIENTE")

    res = await cliente_http.get("/mis-ordenes?page=0")
    assert res.status_code == 422


async def test_mis_ordenes_sin_cookie_401(cliente_http: AsyncClient) -> None:
    """Sin cookie → 401."""
    res = await cliente_http.get("/mis-ordenes")
    assert res.status_code == 401


async def test_listado_filtro_sin_resultados(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Filtro sin coincidencias → 200 con página 1 vacía y total 0 (borde de paginación)."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    await _crear_ordenes_ejemplo(sesion_db, vehiculo.id)  # PENDIENTE y TERMINADA, sin CANCELADA

    res = await cliente_http.get("/ordenes?estado=CANCELADA&page=1&size=10")
    assert res.status_code == 200
    datos = res.json()
    assert datos["total"] == 0
    assert datos["items"] == []
    assert datos["pages"] == 1


async def test_listado_pagina_inexistente_422(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Página más allá de la última → 422 (borde de paginación)."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    await _crear_ordenes_ejemplo(sesion_db, vehiculo.id)  # 3 órdenes, con size=1 hay 3 páginas

    res = await cliente_http.get("/ordenes?page=999&size=1")
    assert res.status_code == 422


async def test_detalle_sin_items(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Detalle de orden sin ítems → items=[] y sin fallar (staff ve cualquiera)."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="AAA111")
    orden_id = await _insertar_orden(
        sesion_db,
        vehiculo_id=vehiculo.id,
        estado="PENDIENTE",
        falla="Sin items",
        total="0.00",
        historial=[(None, "PENDIENTE", None)],
    )

    res = await cliente_http.get(f"/ordenes/{orden_id}")
    assert res.status_code == 200
    datos = res.json()
    assert datos["items"] == []
    assert len(datos["historial"]) == 1


async def test_mis_ordenes_vehiculo_baja_no_aparece(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Orden de un vehículo dado de baja no aparece en /mis-ordenes (RN-17)."""
    await insertar_catalogo(sesion_db)
    usuario, cliente = await _autenticar_y_cliente(
        cliente_http, sesion_db, "cliente@taller.test", "CLIENTE", documento="1"
    )
    v_activo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="ACT111")
    v_baja = await crear_vehiculo(
        sesion_db, cliente_id=cliente.id, patente="BAJA111", borrado_en=datetime.now(UTC)
    )
    await _insertar_orden(sesion_db, vehiculo_id=v_activo.id, estado="PENDIENTE", total="10.00")
    await _insertar_orden(sesion_db, vehiculo_id=v_baja.id, estado="PENDIENTE", total="20.00")

    res = await cliente_http.get("/mis-ordenes?page=1&size=10")
    assert res.status_code == 200
    datos = res.json()
    assert datos["total"] == 1
    assert len(datos["items"]) == 1
    assert datos["items"][0]["patente"] == "ACT111"


async def test_rutas_heredan_control_cambio_pendiente_protegido(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Las 5 rutas de órdenes heredan `exige_sin_cambio_pendiente` → 403 con la
    bandera activa (DD-10, RN-06, task 8.4; seleccionable con -k "protegido")."""
    await insertar_catalogo(sesion_db)
    hash_pass = await security.hash_password("password-test-123")
    usuario = Usuario(
        email="pendiente@taller.test", nombre="Pendiente", password_hash=hash_pass,
        activo=True, debe_cambiar_password=True,
    )
    sesion_db.add(usuario)
    await sesion_db.flush()
    await sesion_db.commit()
    await sesion_db.refresh(usuario)

    token = security.crear_token_acceso(
        id_usuario=usuario.id, roles=["CLIENTE"], secreto=settings.secret_key,
        expira_en_segundos=1800,
    )
    cliente_http.cookies.set(NOMBRE_COOKIE_SESION, token)

    cliente = await crear_cliente(sesion_db, nombre="Pendiente", documento="9", usuario_id=usuario.id)
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="PEN111")

    assert (await cliente_http.post("/ordenes", json={
        "vehiculo_id": vehiculo.id, "falla": "F", "items": [{"repuesto_id": 1, "cantidad": 1}]})).status_code == 403
    assert (await cliente_http.get("/ordenes")).status_code == 403
    assert (await cliente_http.get("/ordenes/1")).status_code == 403
    assert (await cliente_http.get("/estados-orden")).status_code == 403
    assert (await cliente_http.get("/mis-ordenes")).status_code == 403
    # Transiciones de C-08: heredan el control del grupo protegido.
    assert (await cliente_http.post("/ordenes/1/iniciar")).status_code == 403
    assert (await cliente_http.post("/ordenes/1/terminar")).status_code == 403
    assert (await cliente_http.post("/ordenes/1/cancelar")).status_code == 403

# -- POST /ordenes/{id}/iniciar (tasks 2.3, 2.4) -----------------------------


async def test_iniciar_orden_mecanico_exitoso(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """MECANICO inicia PENDIENTE ? 200, EN_REPARACION, mecanico_id e historial."""
    await insertar_catalogo(sesion_db)
    mecanico = await autenticar_usuario(
        cliente_http, sesion_db, "meca@taller.test", "MECANICO"
    )
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="INI111")
    orden_id = await _insertar_orden(
        sesion_db,
        vehiculo_id=vehiculo.id,
        estado="PENDIENTE",
        historial=[(None, "PENDIENTE", mecanico.id)],
    )

    res = await cliente_http.post(f"/ordenes/{orden_id}/iniciar")

    assert res.status_code == 200
    datos = res.json()
    assert datos["estado"] == "EN_REPARACION"
    assert datos["mecanico_id"] == mecanico.id
    assert datos["historial"][-1]["desde_estado"] == "PENDIENTE"
    assert datos["historial"][-1]["hasta_estado"] == "EN_REPARACION"


async def test_iniciar_orden_ya_en_reparacion_409(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Orden ya EN_REPARACION ? 409 y no se agrega historial."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "meca@taller.test", "MECANICO")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="INI222")
    orden_id = await _insertar_orden(
        sesion_db,
        vehiculo_id=vehiculo.id,
        estado="EN_REPARACION",
        historial=[(None, "PENDIENTE", None), ("PENDIENTE", "EN_REPARACION", None)],
    )

    res = await cliente_http.post(f"/ordenes/{orden_id}/iniciar")

    assert res.status_code == 409
    historial = await sesion_db.execute(
        select(func.count())
        .select_from(HistorialEstadoOrden)
        .where(HistorialEstadoOrden.orden_id == orden_id)
    )
    assert int(historial.scalar_one()) == 2


@pytest.mark.parametrize("rol", ["CLIENTE", "RECEPCION", "ADMIN"])
async def test_iniciar_orden_sin_rol_mecanico_403(
    cliente_http: AsyncClient, sesion_db: AsyncSession, rol: str
) -> None:
    """Un usuario sin rol MECANICO vigente ? 403 y el estado no cambia."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, f"{rol.lower()}@taller.test", rol)
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="INI333")
    orden_id = await _insertar_orden(sesion_db, vehiculo_id=vehiculo.id)

    res = await cliente_http.post(f"/ordenes/{orden_id}/iniciar")

    assert res.status_code == 403
    estado = await sesion_db.execute(
        select(OrdenTrabajo.estado).where(OrdenTrabajo.id == orden_id)
    )
    assert estado.scalar_one() == "PENDIENTE"


async def test_iniciar_orden_inexistente_404(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Orden inexistente ? 404."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "meca@taller.test", "MECANICO")

    res = await cliente_http.post("/ordenes/999999/iniciar")
    assert res.status_code == 404


async def test_iniciar_orden_sin_cookie_401(cliente_http: AsyncClient) -> None:
    """Sin cookie ? 401."""
    res = await cliente_http.post("/ordenes/1/iniciar")
    assert res.status_code == 401


# -- POST /ordenes/{id}/terminar (tasks 3.3, 3.4) ----------------------------


async def _preparar_terminar(
    sesion_db: AsyncSession,
    *,
    sufijo: str,
    stock: int = 10,
    cantidad: int = 2,
) -> tuple[int, int]:
    """Crea cliente/veh�culo/repuesto/orden EN_REPARACION; devuelve (orden, repuesto)."""
    cliente = await crear_cliente(
        sesion_db, nombre=f"Ana {sufijo}", documento=f"doc-{sufijo}"
    )
    vehiculo = await crear_vehiculo(
        sesion_db, cliente_id=cliente.id, patente=f"TER{sufijo}"
    )
    repuesto = await crear_repuesto(
        sesion_db, codigo=f"RT-{sufijo}", precio="100.00", stock=stock
    )
    orden_id = await _insertar_orden(
        sesion_db,
        vehiculo_id=vehiculo.id,
        estado="EN_REPARACION",
        items=[(repuesto.id, cantidad, "100.00")],
        historial=[(None, "PENDIENTE", None), ("PENDIENTE", "EN_REPARACION", None)],
    )
    return orden_id, repuesto.id


async def _stock_persistido(sesion_db: AsyncSession, repuesto_id: int) -> int:
    valor = await sesion_db.execute(
        select(Repuesto.stock).where(Repuesto.id == repuesto_id)
    )
    return int(valor.scalar_one())


async def _movimientos_de(sesion_db: AsyncSession, orden_id: int) -> int:
    valor = await sesion_db.execute(
        select(func.count())
        .select_from(MovimientoStock)
        .where(MovimientoStock.orden_id == orden_id)
    )
    return int(valor.scalar_one())


async def test_terminar_orden_mecanico_asignado_exitoso(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Mec�nico asignado + stock suficiente ? 200, TERMINADA, stock y movimientos."""
    await insertar_catalogo(sesion_db)
    mecanico = await autenticar_usuario(
        cliente_http, sesion_db, "meca@taller.test", "MECANICO"
    )
    orden_id, repuesto_id = await _preparar_terminar(sesion_db, sufijo="mec")
    # Asigna el mec�nico autenticado a la orden EN_REPARACION
    orden = await sesion_db.get(OrdenTrabajo, orden_id)
    orden.mecanico_id = mecanico.id
    await sesion_db.commit()

    res = await cliente_http.post(f"/ordenes/{orden_id}/terminar")

    assert res.status_code == 200
    datos = res.json()
    assert datos["estado"] == "TERMINADA"
    assert datos["historial"][-1]["desde_estado"] == "EN_REPARACION"
    assert datos["historial"][-1]["hasta_estado"] == "TERMINADA"
    assert await _stock_persistido(sesion_db, repuesto_id) == 8
    assert await _movimientos_de(sesion_db, orden_id) == 1


async def test_terminar_orden_admin_ajena_exitoso(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """ADMIN no asignado termina la orden ? 200."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")
    orden_id, repuesto_id = await _preparar_terminar(sesion_db, sufijo="adm")

    res = await cliente_http.post(f"/ordenes/{orden_id}/terminar")

    assert res.status_code == 200
    assert res.json()["estado"] == "TERMINADA"
    assert await _stock_persistido(sesion_db, repuesto_id) == 8


async def test_terminar_orden_stock_insuficiente_409_sin_escrituras(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Stock insuficiente ? 409 sin cambios en stock, movimientos ni historial."""
    await insertar_catalogo(sesion_db)
    mecanico = await autenticar_usuario(
        cliente_http, sesion_db, "meca@taller.test", "MECANICO"
    )
    orden_id, repuesto_id = await _preparar_terminar(
        sesion_db, sufijo="ins", stock=1, cantidad=3
    )
    orden = await sesion_db.get(OrdenTrabajo, orden_id)
    orden.mecanico_id = mecanico.id
    await sesion_db.commit()

    res = await cliente_http.post(f"/ordenes/{orden_id}/terminar")

    assert res.status_code == 409
    assert await _stock_persistido(sesion_db, repuesto_id) == 1
    assert await _movimientos_de(sesion_db, orden_id) == 0
    estado = await sesion_db.execute(
        select(OrdenTrabajo.estado).where(OrdenTrabajo.id == orden_id)
    )
    assert estado.scalar_one() == "EN_REPARACION"
    historial = await sesion_db.execute(
        select(func.count())
        .select_from(HistorialEstadoOrden)
        .where(HistorialEstadoOrden.orden_id == orden_id)
    )
    assert int(historial.scalar_one()) == 2


async def test_terminar_orden_ajena_403(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """MECANICO no asignado y sin ADMIN ? 403 (antes que el estado)."""
    await insertar_catalogo(sesion_db)
    mecanico = await autenticar_usuario(
        cliente_http, sesion_db, "meca@taller.test", "MECANICO"
    )
    await autenticar_usuario(
        cliente_http, sesion_db, "otro@taller.test", "MECANICO"
    )
    orden_id, _ = await _preparar_terminar(sesion_db, sufijo="aje")
    orden = await sesion_db.get(OrdenTrabajo, orden_id)
    orden.mecanico_id = mecanico.id
    await sesion_db.commit()

    # La cookie vigente es la del �ltimo usuario autenticado ("otro").
    res = await cliente_http.post(f"/ordenes/{orden_id}/terminar")

    assert res.status_code == 403
    estado = await sesion_db.execute(
        select(OrdenTrabajo.estado).where(OrdenTrabajo.id == orden_id)
    )
    assert estado.scalar_one() == "EN_REPARACION"


async def test_terminar_orden_ya_terminada_409(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Orden ya TERMINADA (con mec�nico asignado) ? 409."""
    await insertar_catalogo(sesion_db)
    mecanico = await autenticar_usuario(
        cliente_http, sesion_db, "meca@taller.test", "MECANICO"
    )
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="TERFIN")
    orden_id = await _insertar_orden(
        sesion_db,
        vehiculo_id=vehiculo.id,
        estado="TERMINADA",
        mecanico_id=mecanico.id,
    )

    res = await cliente_http.post(f"/ordenes/{orden_id}/terminar")
    assert res.status_code == 409


async def test_terminar_orden_inexistente_404(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Orden inexistente ? 404."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")

    res = await cliente_http.post("/ordenes/999999/terminar")
    assert res.status_code == 404


async def test_terminar_orden_sin_cookie_401(cliente_http: AsyncClient) -> None:
    """Sin cookie ? 401."""
    res = await cliente_http.post("/ordenes/1/terminar")
    assert res.status_code == 401


# -- POST /ordenes/{id}/cancelar (tasks 4.3, 4.4) ----------------------------


async def test_cancelar_orden_recepcion_exitoso(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """RECEPCION cancela PENDIENTE ? 200 y CANCELADA con historial."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="CAN111")
    orden_id = await _insertar_orden(
        sesion_db,
        vehiculo_id=vehiculo.id,
        historial=[(None, "PENDIENTE", None)],
    )

    res = await cliente_http.post(f"/ordenes/{orden_id}/cancelar")

    assert res.status_code == 200
    datos = res.json()
    assert datos["estado"] == "CANCELADA"
    assert datos["historial"][-1]["desde_estado"] == "PENDIENTE"
    assert datos["historial"][-1]["hasta_estado"] == "CANCELADA"


async def test_cancelar_orden_duenio_exitoso(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """El due�o del veh�culo cancela su orden PENDIENTE ? 200."""
    await insertar_catalogo(sesion_db)
    duenio = await autenticar_usuario(
        cliente_http, sesion_db, "duenio@taller.test", "CLIENTE"
    )
    cliente = await crear_cliente(
        sesion_db, nombre="Due�o", documento="2", usuario_id=duenio.id
    )
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="CAN222")
    orden_id = await _insertar_orden(
        sesion_db,
        vehiculo_id=vehiculo.id,
        historial=[(None, "PENDIENTE", None)],
    )

    res = await cliente_http.post(f"/ordenes/{orden_id}/cancelar")
    assert res.status_code == 200
    assert res.json()["estado"] == "CANCELADA"


async def test_cancelar_orden_ajena_403_no_409(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Usuario ajeno sobre PENDIENTE ? 403 (no 409) y no cambia el estado."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "ajeno@taller.test", "CLIENTE")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="CAN333")
    orden_id = await _insertar_orden(sesion_db, vehiculo_id=vehiculo.id)

    res = await cliente_http.post(f"/ordenes/{orden_id}/cancelar")

    assert res.status_code == 403
    estado = await sesion_db.execute(
        select(OrdenTrabajo.estado).where(OrdenTrabajo.id == orden_id)
    )
    assert estado.scalar_one() == "PENDIENTE"


async def test_cancelar_orden_terminada_409(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Con relaci�n v�lida pero orden TERMINADA ? 409."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    cliente = await crear_cliente(sesion_db, nombre="Ana", documento="1")
    vehiculo = await crear_vehiculo(sesion_db, cliente_id=cliente.id, patente="CAN444")
    orden_id = await _insertar_orden(
        sesion_db, vehiculo_id=vehiculo.id, estado="TERMINADA"
    )

    res = await cliente_http.post(f"/ordenes/{orden_id}/cancelar")
    assert res.status_code == 409


async def test_cancelar_orden_inexistente_404(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Orden inexistente ? 404."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")

    res = await cliente_http.post("/ordenes/999999/cancelar")
    assert res.status_code == 404


async def test_cancelar_orden_sin_cookie_401(cliente_http: AsyncClient) -> None:
    """Sin cookie ? 401."""
    res = await cliente_http.post("/ordenes/1/cancelar")
    assert res.status_code == 401


# -- DELETE /vehiculos/{id} con �rdenes abiertas (task 5.1, RN-16) -----------


async def _vehiculo_con_orden(
    sesion_db: AsyncSession, *, sufijo: str, estado: str | None
) -> tuple[int, int]:
    """Crea veh�culo (y orden opcional) y devuelve (vehiculo_id, orden_id|0)."""
    cliente = await crear_cliente(
        sesion_db, nombre=f"Ana {sufijo}", documento=f"doc-baja-{sufijo}"
    )
    vehiculo = await crear_vehiculo(
        sesion_db, cliente_id=cliente.id, patente=f"BAJ{sufijo}"
    )
    orden_id = 0
    if estado is not None:
        orden_id = await _insertar_orden(
            sesion_db, vehiculo_id=vehiculo.id, estado=estado
        )
    return vehiculo.id, orden_id


@pytest.mark.parametrize("estado", ["PENDIENTE", "EN_REPARACION"])
async def test_baja_vehiculo_con_ordenes_abiertas_409(
    cliente_http: AsyncClient, sesion_db: AsyncSession, estado: str
) -> None:
    """Veh�culo con orden no final ? 409 y sigue vigente (RN-16)."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    vehiculo_id, _ = await _vehiculo_con_orden(
        sesion_db, sufijo=estado[:3], estado=estado
    )

    res = await cliente_http.delete(f"/vehiculos/{vehiculo_id}")

    assert res.status_code == 409
    from app.modules.clientes.models import Vehiculo

    borrado = await sesion_db.execute(
        select(Vehiculo.borrado_en).where(Vehiculo.id == vehiculo_id)
    )
    assert borrado.scalar_one() is None


@pytest.mark.parametrize("estado", [None, "TERMINADA", "CANCELADA"])
async def test_baja_vehiculo_sin_ordenes_abiertas_204(
    cliente_http: AsyncClient, sesion_db: AsyncSession, estado: str | None
) -> None:
    """Sin �rdenes o solo finales ? 204 con `borrado_en` seteado (RN-16)."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")
    sufijo = (estado or "sin")[:3]
    vehiculo_id, _ = await _vehiculo_con_orden(
        sesion_db, sufijo=sufijo, estado=estado
    )

    res = await cliente_http.delete(f"/vehiculos/{vehiculo_id}")

    assert res.status_code == 204
    from app.modules.clientes.models import Vehiculo

    borrado = await sesion_db.execute(
        select(Vehiculo.borrado_en).where(Vehiculo.id == vehiculo_id)
    )
    assert borrado.scalar_one() is not None


async def test_baja_vehiculo_inexistente_404(
    cliente_http: AsyncClient, sesion_db: AsyncSession
) -> None:
    """Veh�culo inexistente ? 404."""
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "recepcion@taller.test", "RECEPCION")

    res = await cliente_http.delete("/vehiculos/999999")
    assert res.status_code == 404


async def test_terminar_notifica_solo_tras_commit(
    cliente_http: AsyncClient, sesion_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La notificación se encola solo si la transacción confirmó (D6, task 3.5)."""
    from app.modules.ordenes import router as router_ordenes_modulo

    llamadas: list[int] = []

    async def _notificacion_falsa(orden_id: int) -> None:
        llamadas.append(orden_id)

    monkeypatch.setattr(
        router_ordenes_modulo, "notificar_orden_terminada", _notificacion_falsa
    )
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")
    orden_id, _ = await _preparar_terminar(sesion_db, sufijo="not")

    res = await cliente_http.post(f"/ordenes/{orden_id}/terminar")

    assert res.status_code == 200
    assert llamadas == [orden_id]


async def test_terminar_con_409_no_notifica(
    cliente_http: AsyncClient, sesion_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con rollback por stock insuficiente no se ejecuta la notificación (D6)."""
    from app.modules.ordenes import router as router_ordenes_modulo

    llamadas: list[int] = []

    async def _notificacion_falsa(orden_id: int) -> None:
        llamadas.append(orden_id)

    monkeypatch.setattr(
        router_ordenes_modulo, "notificar_orden_terminada", _notificacion_falsa
    )
    await insertar_catalogo(sesion_db)
    await autenticar_usuario(cliente_http, sesion_db, "admin@taller.test", "ADMIN")
    orden_id, _ = await _preparar_terminar(
        sesion_db, sufijo="not2", stock=0, cantidad=5
    )

    res = await cliente_http.post(f"/ordenes/{orden_id}/terminar")

    assert res.status_code == 409
    assert llamadas == []
