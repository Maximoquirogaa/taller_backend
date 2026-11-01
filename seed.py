"""Carga inicial del taller: deja la base en un estado conocido y reproducible.

Uso (spec `seed-inicial`, C-10):

    alembic upgrade head
    python seed.py

Qué hace:

1. Vacía las 13 tablas con `TRUNCATE ... RESTART IDENTITY CASCADE` (misma
   sentencia que usa `test/conftest.py`) y carga todo dentro de **una sola**
   transacción: si algo falla no queda una carga parcial.
2. Puebla el catálogo `estado_orden` (nace vacío por DD-01), los usuarios con
   sus roles vigentes, los clientes con sus vehículos, los repuestos, las
   órdenes con sus ítems e historiales, y un evento de seguridad de `SISTEMA`.
3. Es re-ejecutable: correrlo dos veces deja exactamente el mismo estado.

Las tres tablas de historial (`historial_estado_orden`, `movimiento_stock`,
`historial_precio_repuesto`) sólo reciben `INSERT`, como exige el disparador de
sólo agregado de C-09. El stock de cada repuesto queda respaldado por su
movimiento de alta (RN-14).

Credenciales ficticias (todas con la misma contraseña de demostración):

    Contraseña: Taller2026

    admin@example.com      ADMIN
    admin2@example.com     ADMIN
    recepcion@example.com  RECEPCION
    mecanico@example.com   MECANICO
    mecanico2@example.com  MECANICO
    cliente@example.com    CLIENTE (ficha de Laura Gómez)
    nuevo@example.com      MECANICO con cambio de contraseña pendiente

⚠️ El script borra los datos de trabajo de la base a la que apunte `POSTGRES_DB`.
No se ejecuta solo: hay que invocarlo a propósito con `python seed.py`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import cargar_settings
from app.core.database import crear_fabrica_sesiones, crear_motor
from app.core.security import hash_password
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import (
    EstadoOrden,
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)
from app.modules.repuestos.models import (
    HistorialPrecioRepuesto,
    MovimientoStock,
    Repuesto,
)
from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, Usuario

# ── Constantes de la carga ──────────────────────────────────────────────────

CONTRASENA_FICTICIA = "Taller2026"

EMAIL_ADMIN = "admin@example.com"
EMAIL_ADMIN_AUXILIAR = "admin2@example.com"
EMAIL_RECEPCION = "recepcion@example.com"
EMAIL_MECANICO = "mecanico@example.com"
EMAIL_MECANICO_AUXILIAR = "mecanico2@example.com"
EMAIL_CLIENTE = "cliente@example.com"
EMAIL_USUARIO_NUEVO = "nuevo@example.com"

CODIGO_FILTRO_ACEITE = "FIL-001"
CODIGO_PASTILLAS_FRENO = "PAS-001"
CODIGO_BUJIA = "BUJ-001"
CODIGO_ACEITE = "ACE-001"

PATENTE_ORDEN_PENDIENTE = "AB123CD"
PATENTE_ORDEN_EN_REPARACION = "AC789HI"

MOTIVO_STOCK_INICIAL = "Stock inicial"
ACCION_EVENTO_INICIAL = "Carga de los datos iniciales"
ACTOR_SISTEMA = "SISTEMA"

ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_EN_REPARACION = "EN_REPARACION"

# Orden de dependencias: las hijas primero para que el TRUNCATE no dependa del CASCADE.
TABLAS_INICIALES = (
    "historial_estado_orden",
    "item_orden",
    "orden_trabajo",
    "estado_orden",
    "historial_precio_repuesto",
    "movimiento_stock",
    "repuesto",
    "vehiculo",
    "cliente",
    "asignacion_rol",
    "intento_acceso",
    "evento_seguridad",
    "usuario",
)


class EstadoInicial(NamedTuple):
    """Fila del catálogo `estado_orden`."""

    codigo: str
    descripcion: str
    posicion: int
    es_final: bool


class UsuarioInicial(NamedTuple):
    """Usuario de demostración con su rol vigente."""

    email: str
    nombre: str
    rol: str
    debe_cambiar_password: bool = False


class VehiculoInicial(NamedTuple):
    """Vehículo de un cliente de la carga."""

    patente: str
    marca: str
    modelo: str
    anio: int


class ClienteInicial(NamedTuple):
    """Cliente con sus vehículos y el usuario web asociado (opcional)."""

    nombre: str
    documento: str
    telefono: str
    usuario_email: str | None
    vehiculos: tuple[VehiculoInicial, ...]


class RepuestoInicial(NamedTuple):
    """Repuesto con su precio vigente y el stock del alta inicial."""

    codigo: str
    descripcion: str
    precio: Decimal
    stock: int


class ItemOrdenInicial(NamedTuple):
    """Línea de una orden: código de repuesto y cantidad pedida."""

    codigo_repuesto: str
    cantidad: int


class OrdenInicial(NamedTuple):
    """Orden de trabajo de la carga, con su vehículo y su mecánico opcional."""

    patente: str
    estado: str
    falla: str
    mecanico_email: str | None
    items: tuple[ItemOrdenInicial, ...]


ESTADOS_INICIALES: tuple[EstadoInicial, ...] = (
    EstadoInicial(ESTADO_PENDIENTE, "Pendiente de reparación", 1, False),
    EstadoInicial(ESTADO_EN_REPARACION, "En reparación", 2, False),
    EstadoInicial("TERMINADA", "Terminada", 3, True),
    EstadoInicial("CANCELADA", "Cancelada", 4, True),
)

USUARIOS_INICIALES: tuple[UsuarioInicial, ...] = (
    UsuarioInicial(EMAIL_ADMIN, "Administrador del taller", "ADMIN"),
    UsuarioInicial(EMAIL_ADMIN_AUXILIAR, "Segundo administrador", "ADMIN"),
    UsuarioInicial(EMAIL_RECEPCION, "Recepción del taller", "RECEPCION"),
    UsuarioInicial(EMAIL_MECANICO, "Mecánico principal", "MECANICO"),
    UsuarioInicial(EMAIL_MECANICO_AUXILIAR, "Mecánico auxiliar", "MECANICO"),
    UsuarioInicial(EMAIL_CLIENTE, "Laura Gómez", "CLIENTE"),
    UsuarioInicial(EMAIL_USUARIO_NUEVO, "Mecánico nuevo", "MECANICO", True),
)

CLIENTES_INICIALES: tuple[ClienteInicial, ...] = (
    ClienteInicial(
        "Laura Gómez",
        "30111222",
        "11-5555-0101",
        EMAIL_CLIENTE,
        (
            VehiculoInicial(PATENTE_ORDEN_PENDIENTE, "Toyota", "Corolla", 2019),
            VehiculoInicial("AE456FG", "Ford", "Fiesta", 2015),
        ),
    ),
    ClienteInicial(
        "Jorge Pérez",
        "27888999",
        "11-5555-0202",
        None,
        (VehiculoInicial(PATENTE_ORDEN_EN_REPARACION, "Chevrolet", "Onix", 2021),),
    ),
)

REPUESTOS_INICIALES: tuple[RepuestoInicial, ...] = (
    RepuestoInicial(CODIGO_FILTRO_ACEITE, "Filtro de aceite", Decimal("8500.00"), 10),
    RepuestoInicial(CODIGO_PASTILLAS_FRENO, "Pastillas de freno", Decimal("12000.00"), 4),
    RepuestoInicial(CODIGO_BUJIA, "Bujía de encendido", Decimal("3500.00"), 2),
    RepuestoInicial(CODIGO_ACEITE, "Aceite por litro", Decimal("2500.00"), 20),
)

# El filtro tuvo un aumento previo (8000 → 8500) que queda en su historial (RN-20).
PRECIO_ANTERIOR_FILTRO = Decimal("8000.00")

ORDENES_INICIALES: tuple[OrdenInicial, ...] = (
    OrdenInicial(
        PATENTE_ORDEN_PENDIENTE,
        ESTADO_PENDIENTE,
        "Ruido en el motor al arrancar",
        None,
        (ItemOrdenInicial(CODIGO_FILTRO_ACEITE, 1),),
    ),
    OrdenInicial(
        PATENTE_ORDEN_EN_REPARACION,
        ESTADO_EN_REPARACION,
        "Cambio de bujías y puesta a punto",
        EMAIL_MECANICO,
        # 4 bujías contra un stock de 2: el caso de stock insuficiente de la consigna.
        (ItemOrdenInicial(CODIGO_BUJIA, 4),),
    ),
)


# ── Carga ───────────────────────────────────────────────────────────────────


async def cargar_datos_iniciales(
    fabrica: async_sessionmaker[AsyncSession],
) -> None:
    """Deja la base en el estado inicial del taller en una única transacción.

    Args:
        fabrica: fábrica de sesiones (la de la app en `main()`, la de la suite
            de pruebas en los tests).

    Raises:
        sqlalchemy.exc.SQLAlchemyError: cualquier fallo de la base; al estar
            todo dentro de un solo bloque, no queda una carga parcial.
    """
    ahora = datetime.now(timezone.utc)
    # El hash se calcula antes de abrir la transacción (y fuera del bucle de
    # eventos): bcrypt nunca corre dentro del UoW. Una sola vez para los 7 usuarios.
    hash_compartido = await hash_password(CONTRASENA_FICTICIA)

    async with fabrica() as sesion, sesion.begin():
        tablas = ", ".join(TABLAS_INICIALES)
        await sesion.execute(text(f"TRUNCATE TABLE {tablas} RESTART IDENTITY CASCADE"))

        # 1. Catálogo de estados: las órdenes le apuntan por FK (RN-19, DD-01).
        for datos_estado in ESTADOS_INICIALES:
            sesion.add(EstadoOrden(**datos_estado._asdict()))
        await sesion.flush()

        # 2. Usuarios y sus roles vigentes, otorgados por el administrador.
        usuarios: dict[str, Usuario] = {}
        for datos_usuario in USUARIOS_INICIALES:
            usuario = Usuario(
                email=datos_usuario.email,
                nombre=datos_usuario.nombre,
                password_hash=hash_compartido,
                debe_cambiar_password=datos_usuario.debe_cambiar_password,
            )
            sesion.add(usuario)
            usuarios[datos_usuario.email] = usuario
        await sesion.flush()

        admin = usuarios[EMAIL_ADMIN]
        for datos_usuario in USUARIOS_INICIALES:
            sesion.add(
                AsignacionRol(
                    usuario_id=usuarios[datos_usuario.email].id,
                    rol=datos_usuario.rol,
                    desde=ahora,
                    otorgada_por=admin.id,
                )
            )
        await sesion.flush()

        # 3. Clientes y vehículos (Laura queda vinculada al usuario `cliente@`).
        clientes: dict[str, Cliente] = {}
        for datos_cliente in CLIENTES_INICIALES:
            cliente = Cliente(
                usuario_id=(
                    usuarios[datos_cliente.usuario_email].id
                    if datos_cliente.usuario_email is not None
                    else None
                ),
                nombre=datos_cliente.nombre,
                documento=datos_cliente.documento,
                telefono=datos_cliente.telefono,
            )
            sesion.add(cliente)
            clientes[datos_cliente.nombre] = cliente
        await sesion.flush()

        vehiculos: dict[str, Vehiculo] = {}
        for datos_cliente in CLIENTES_INICIALES:
            cliente = clientes[datos_cliente.nombre]
            for datos_vehiculo in datos_cliente.vehiculos:
                vehiculo = Vehiculo(
                    cliente_id=cliente.id,
                    patente=datos_vehiculo.patente,
                    marca=datos_vehiculo.marca,
                    modelo=datos_vehiculo.modelo,
                    anio=datos_vehiculo.anio,
                )
                sesion.add(vehiculo)
                vehiculos[datos_vehiculo.patente] = vehiculo
        await sesion.flush()

        # 4. Repuestos: el stock sólo existe con su movimiento de alta (RN-14).
        repuestos: dict[str, Repuesto] = {}
        for datos_repuesto in REPUESTOS_INICIALES:
            repuesto = Repuesto(
                codigo=datos_repuesto.codigo,
                descripcion=datos_repuesto.descripcion,
                precio=datos_repuesto.precio,
                stock=datos_repuesto.stock,
            )
            sesion.add(repuesto)
            repuestos[datos_repuesto.codigo] = repuesto
        await sesion.flush()

        for datos_repuesto in REPUESTOS_INICIALES:
            if datos_repuesto.stock == 0:
                continue
            sesion.add(
                MovimientoStock(
                    repuesto_id=repuestos[datos_repuesto.codigo].id,
                    orden_id=None,
                    usuario_id=admin.id,
                    cantidad=datos_repuesto.stock,
                    motivo=MOTIVO_STOCK_INICIAL,
                    cuando=ahora,
                )
            )
        await sesion.flush()

        # 5. Órdenes con sus ítems, totales e historial coherente con el estado.
        ordenes: dict[str, OrdenTrabajo] = {}
        for datos_orden in ORDENES_INICIALES:
            total = sum(
                (
                    repuestos[item.codigo_repuesto].precio * item.cantidad
                    for item in datos_orden.items
                ),
                Decimal("0.00"),
            )
            orden = OrdenTrabajo(
                vehiculo_id=vehiculos[datos_orden.patente].id,
                mecanico_id=(
                    usuarios[datos_orden.mecanico_email].id
                    if datos_orden.mecanico_email is not None
                    else None
                ),
                estado=datos_orden.estado,
                falla=datos_orden.falla,
                creada_en=ahora,
                total=total,
            )
            sesion.add(orden)
            ordenes[datos_orden.patente] = orden
        await sesion.flush()

        # La transición de estado es un instante posterior al alta: el historial
        # se lee ordenado por `cuando` y así el relato queda en el orden correcto.
        ahora_transicion = ahora + timedelta(seconds=1)

        for datos_orden in ORDENES_INICIALES:
            orden = ordenes[datos_orden.patente]
            for item in datos_orden.items:
                repuesto = repuestos[item.codigo_repuesto]
                sesion.add(
                    ItemOrden(
                        orden_id=orden.id,
                        repuesto_id=repuesto.id,
                        cantidad=item.cantidad,
                        precio_unitario=repuesto.precio,
                    )
                )

            sesion.add(
                HistorialEstadoOrden(
                    orden_id=orden.id,
                    desde_estado=None,
                    hasta_estado=ESTADO_PENDIENTE,
                    usuario_id=None,
                    cuando=ahora,
                )
            )
            if datos_orden.estado == ESTADO_EN_REPARACION and datos_orden.mecanico_email:
                sesion.add(
                    HistorialEstadoOrden(
                        orden_id=orden.id,
                        desde_estado=ESTADO_PENDIENTE,
                        hasta_estado=ESTADO_EN_REPARACION,
                        usuario_id=usuarios[datos_orden.mecanico_email].id,
                        cuando=ahora_transicion,
                    )
                )
        await sesion.flush()

        # 6. Historial de precios del filtro (8000 → 8500) y evento de seguridad.
        filtro = repuestos[CODIGO_FILTRO_ACEITE]
        sesion.add(
            HistorialPrecioRepuesto(
                repuesto_id=filtro.id,
                usuario_id=admin.id,
                precio_anterior=PRECIO_ANTERIOR_FILTRO,
                precio_nuevo=filtro.precio,
                cuando=ahora,
            )
        )
        sesion.add(
            EventoSeguridad(
                actor=ACTOR_SISTEMA,
                accion=ACCION_EVENTO_INICIAL,
                cuando=ahora,
            )
        )


async def _contar_filas(fabrica: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Cuenta las filas de las 13 tablas para el resumen de `main()`."""
    conteos: dict[str, int] = {}
    async with fabrica() as sesion:
        for tabla in TABLAS_INICIALES:
            resultado = await sesion.execute(text(f'SELECT count(*) FROM "{tabla}"'))
            conteos[tabla] = int(resultado.scalar_one())
    return conteos


def main() -> None:
    """Carga los datos iniciales sobre `POSTGRES_DB` y muestra el resumen."""
    settings = cargar_settings()
    motor = crear_motor(
        settings.database_url,
        echo=settings.sql_echo,
        pool_size=settings.pool_size,
    )
    fabrica = crear_fabrica_sesiones(motor)

    async def _ejecutar_carga() -> dict[str, int]:
        try:
            await cargar_datos_iniciales(fabrica)
            return await _contar_filas(fabrica)
        finally:
            await motor.dispose()

    conteos = asyncio.run(_ejecutar_carga())

    ancho = max(len(tabla) for tabla in conteos)
    print("Datos iniciales cargados:")
    for tabla, cantidad in conteos.items():
        print(f"  {tabla:<{ancho}} {cantidad:>4}")
    print()
    print("Usuarios de demostración (contraseña: " + CONTRASENA_FICTICIA + "):")
    for datos_usuario in USUARIOS_INICIALES:
        sufijo = " (debe cambiar la contraseña)" if datos_usuario.debe_cambiar_password else ""
        print(f"  {datos_usuario.email:<24} {datos_usuario.rol}{sufijo}")
    print()
    print("La orden EN_REPARACION pide 4 bujías con stock 2 (caso de stock insuficiente).")


if __name__ == "__main__":
    main()
