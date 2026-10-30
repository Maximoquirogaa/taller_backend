"""Lógica de negocio del módulo usuarios (capa Service).

Todas las multi-escrituras viven en un solo bloque `async with UoWUsuarios`
(RN-02). bcrypt corre **antes** de abrir la transacción (regla dura: HASH antes
del UoW). El intento de acceso del login se registra en una sesión y
transacción **propias siempre confirmadas** (DD-07): es la única escritura del
proyecto que no comparte transacción con su petición, porque el fallo que se
cuenta (RN-08) es el mismo que revertiría la transacción principal.

El límite de intentos (RN-08) se cuenta **sobre la tabla `intento_acceso`**
(consigna de la KB: "Conteo sobre intento_acceso"); un login correcto reinicia
la cuenta sin borrar filas: el conteo solo abarca fallos posteriores al último
éxito del par (email, ip).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password, obtener_hash_ficticio, verificar_password
from app.modules.usuarios.models import Usuario
from app.modules.usuarios.repository import (
    RepositorioIntentos,
    RepositorioUsuarios,
    roles_vigentes_de,
)
from app.modules.usuarios.schemas import EntradaCambioPassword, EntradaRegistro
from app.modules.usuarios.unit_of_work import UoWUsuarios

# ── Constantes del límite de intentos (RN-08) ────────────────────────────────

MAX_INTENTOS_FALLIDOS = 5  # 5 fallos del mismo email+IP disparan el límite
VENTANA_INTENTOS_SEGUNDOS = 60  # ventana de conteo (60 s)
ROL_CLIENTE = "CLIENTE"  # rol que el auto-registro asigna (consigna, US-003)


class CredencialesInvalidas(Exception):
    """Login que no corresponde o cambio con la contraseña actual incorrecta.

    El router responde 401 con un mensaje genérico e idéntico en todos los
    casos (RN-09): ninguna subclase expone el detalle exacto del fallo.
    """


@dataclass
class LimiteIntentosAlcanzado(Exception):
    """El par (email, ip) ya acumuló `MAX_INTENTOS_FALLIDOS` (→ 429 + Retry-After)."""

    segundos_espera: int


class ContrasenaActualIncorrecta(CredencialesInvalidas):
    """El cambio de contraseña no verificó la actual (→ 401, nada se modifica)."""


def _exigir_id(usuario: Usuario) -> int:
    """Devuelve el id de un usuario ya persistido o falla rápido.

    Args:
        usuario: fila cargada/creada en la transacción.

    Returns:
        El `usuario.id` garantizado como `int`.

    Raises:
        ValueError: si el id sigue siendo `None` (fila no sincronizada):
            es un defecto interno, no una entrada del cliente.
    """
    if usuario.id is None:
        raise ValueError("El usuario debería tener id tras el flush de la transacción")
    return usuario.id


def _limite_tiempo_espera() -> int:
    """`Retry-After` cuando el límite ya está alcanzado.

    Los fallos contados están dentro de la ventana de 60 s: pasados 60 segundos
    sin nuevos intentos, la ventana se vacía (el conteo se hace sobre la tabla
    y nadie más escribe). Devolver la ventana completa es el techo justo.

    Returns:
        Segundos a pedir esperar al cliente (`Retry-After`).
    """
    return VENTANA_INTENTOS_SEGUNDOS


async def registrar_cliente(
    sesion: AsyncSession,
    datos: EntradaRegistro,
    ip: str,
    costo_bcrypt: int,
) -> Usuario:
    """Crea la cuenta de cliente: usuario + rol CLIENTE + intento inicial en un UoW (RN-02).

    El hash de la contraseña se calcula **antes** de abrir el UoW (regla dura:
    bcrypt nunca dentro de la transacción). El choque de unicidad lo decide la
    base (RN-01) y sube como `IntegrityError` que el router traduce a 409.

    Args:
        sesion: sesión de la petición (dueña de la transacción del UoW).
        datos: contrato validado (`email`, `nombre`, `password`).
        ip: IP de origen del intento de registro.
        costo_bcrypt: `Settings.bcrypt_cost`.

    Returns:
        El `Usuario` recién creado (con `id` tras el `flush` del UoW).

    Raises:
        ValueError: si la contraseña viola la política o el usuario quedó sin id.
        TypeError: si algún parámetro no es del tipo esperado (fail-fast).
        sqlalchemy.exc.IntegrityError: si la base rechaza la escritura (el
            router lo traduce a 409 con mensaje propio).
    """
    hash_calculado = await hash_password(datos.password, costo_bcrypt)
    async with UoWUsuarios(sesion) as uow:
        usuario = await uow.usuarios.add(
            Usuario(email=datos.email, nombre=datos.nombre, password_hash=hash_calculado)
        )
        await uow.roles.asignar(_exigir_id(usuario), ROL_CLIENTE)
        await uow.intentos.register_intento(datos.email, ip, exito=True)  # intento inicial
    return usuario


async def autentica(
    sesion: AsyncSession,
    fabrica_auditoria: async_sessionmaker[AsyncSession],
    email: str,
    contrasena: str,
    ip: str,
    costo_bcrypt: int,
) -> tuple[Usuario, list[str]]:
    """Verifica credenciales con límite de intentos (RN-08) y usuarios vigentes (RN-09).

    Flujo (Flujo 2 de la KB):
    1. **Primero** el límite: contar fallos del par (email, ip) sobre `intento_acceso`;
       si alcanzan 5 → `LimiteIntentosAlcanzado` (429) sin verificar contraseña.
    2. Verificar contra el hash del usuario, o contra el **hash ficticio** si el
       email no existe (mismo mensaje y tiempo, DD-06/RN-09).
    3. Anotar el intento (éxito o fallo) en sesión/transacción propias SIEMPRE
       confirmadas (DD-07).
    4. Con éxito: roles vigentes desde la base (RN-04) para el token del router.

    Args:
        sesion: sesión de la petición (lee el usuario y consulta roles).
        fabrica_auditoria: fábrica de sesiones (`app.state.fabrica_sesiones`)
            para abrir las sesiones **propias** del conteo y del intento (DD-07).
        email: email propuesto en el login.
        contrasena: contraseña propuesta (≤ 72 bytes, garantizada por el contrato).
        ip: IP de origen (límite por par email+IP).
        costo_bcrypt: costo para el hash ficticio del primer uso (DD-06).

    Returns:
        Tupla `(usuario, roles_vigentes)`: el token lo arma el router con el
        secreto y el vencimiento de Settings.

    Raises:
        ValueError: si un hash guardado no fuera bcrypt válido (`verificar_password`)
            o el usuario persistido saliera sin id.
        TypeError: si algún parámetro no es del tipo esperado (fail-fast).
        LimiteIntentosAlcanzado: si el par (email, ip) ya superó el límite; lleva
            los segundos de espera para la cabecera `Retry-After`.
        CredencialesInvalidas: si la verificación falla o el usuario está desactivado.
    """
    # 1. Límite de intentos → 429 sin tocar bcrypt (RN-08): contador desde la tabla.
    async with fabrica_auditoria() as sesion_lectura:
        lecturas = RepositorioIntentos(sesion_lectura)
        fallos = await lecturas.contar_fallos_recientes(
            email, ip, VENTANA_INTENTOS_SEGUNDOS
        )
    if fallos >= MAX_INTENTOS_FALLIDOS:
        raise LimiteIntentosAlcanzado(segundos_espera=_limite_tiempo_espera())

    # 2. Verificación bcrypt (con hash real o ficticio: mismo tiempo, DD-06).
    usuarios = RepositorioUsuarios(sesion)
    usuario = await usuarios.get_por_email(email)
    hash_objetivo = (
        usuario.password_hash
        if usuario is not None
        else await obtener_hash_ficticio(costo_bcrypt)
    )
    coincide = await verificar_password(contrasena, hash_objetivo)

    # 3. Anotar el intento: sesión y transacción PROPIAS, siempre confirmadas (DD-07).
    exito = coincide and usuario is not None and usuario.activo
    async with fabrica_auditoria() as sesion_intento:
        intentos = RepositorioIntentos(sesion_intento)
        await intentos.register_intento(email, ip, exito)
        async with UoWUsuarios(sesion_intento):
            pass  # el UoW confirma al salir sin excepción (transacción de auditoría)

    if not exito:
        raise CredencialesInvalidas  # mensaje genérico; lo traduce el router

    # 4. Roles vigentes en la base para el token informativo (RN-04).
    roles = await roles_vigentes_de(sesion, _exigir_id(usuario))
    return usuario, roles


async def cambiar_password(
    sesion: AsyncSession,
    usuario: Usuario,
    datos: EntradaCambioPassword,
    costo_bcrypt: int,
) -> list[str]:
    """Cambia la contraseña con verificación de la actual (RN-07, Flujo 3).

    Secuencia (Flujo 3 de la KB): verificación de la actual → hash de la nueva
    **fuera** de la transacción → UoW que actualiza hash, anota el instante del
    cambio y limpia la bandera → **después** del cambio anotado se calculan los
    roles vigentes para el token nuevo que el router convertirá en cookie.

    Args:
        sesion: sesión de la petición (la transacción la abre el UoW).
        usuario: fila cargada en la petición (dependencia `usuario_actual`).
        datos: contratos `password_actual` / `password_nueva` (validados).
        costo_bcrypt: `Settings.bcrypt_cost`.

    Returns:
        Roles vigentes del usuario tras el cambio (listos para el token nuevo).

    Raises:
        ContrasenaActualIncorrecta: si la actual no coincide: nada se modifica.
        ValueError: si la nueva contraseña viola la política (el contrato ya la
            validó; fail-fast defensivo) o el usuario quedó sin id.
        TypeError: fail-fast tipográfico.
    """
    coincide_actual = await verificar_password(datos.password_actual, usuario.password_hash)
    if not coincide_actual:
        raise ContrasenaActualIncorrecta

    hash_nuevo = await hash_password(datos.password_nueva, costo_bcrypt)  # fuera de la transacción
    async with UoWUsuarios(sesion) as uow:
        usuario_actualizado = await uow.usuarios.update(
            usuario,
            {
                "password_hash": hash_nuevo,
                "password_cambiada_en": datetime.now(UTC),
                "debe_cambiar_password": False,
            },
        )
        # El instante del cambio quedó anotado ANTES de emitir el token nuevo
        # (Flujo 3, paso 3): el token que devolverá esta petición sale después.

    return await roles_vigentes_de(sesion, _exigir_id(usuario_actualizado))
