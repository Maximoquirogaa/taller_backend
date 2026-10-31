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

from app.core.paginacion import PaginaDe, ParametrosPagina, construir_pagina
from app.core.security import hash_password, obtener_hash_ficticio, verificar_password
from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, Usuario
from app.modules.usuarios.repository import (
    RepositorioIntentos,
    RepositorioUsuarios,
    roles_vigentes_de,
)
from app.modules.usuarios.schemas import (
    MENSAJE_VENCIMIENTO_INVALIDO,
    ROL_ADMIN,
    EntradaAsignarRol,
    EntradaCambioPassword,
    EntradaCrearUsuario,
    EntradaRegistro,
)
from app.modules.usuarios.unit_of_work import UoWUsuarios

# ── Constantes del límite de intentos (RN-08) ────────────────────────────────

MAX_INTENTOS_FALLIDOS = 5  # 5 fallos del mismo email+IP disparan el límite
VENTANA_INTENTOS_SEGUNDOS = 60  # ventana de conteo (60 s)
ROL_CLIENTE = "CLIENTE"  # rol que el auto-registro asigna (consigna, US-003)

# ── Mensajes y acciones de la administración de personal (C-06) ──────────────

MENSAJE_EMAIL_USUARIO_DUPLICADO = "El email ya está registrado por otro usuario."
MENSAJE_USUARIO_NO_ENCONTRADO = "El usuario solicitado no existe."
MENSAJE_ROL_YA_ASIGNADO = "El usuario ya tiene ese rol vigente."
MENSAJE_ROL_NO_VIGENTE = "El usuario no tiene ese rol abierto."
MENSAJE_AUTORREVOCACION = "Un administrador no puede revocar su propio rol ADMIN."

ACCION_ALTA_PERSONAL = "alta_personal"
ACCION_ROL_OTORGADO = "rol_otorgado"
ACCION_ROL_REVOCADO = "rol_revocado"
ACCION_CAMBIO_PASSWORD = "cambio_password"


class CredencialesInvalidas(Exception):
    """Login que no corresponde o cambio con la contraseña actual incorrecta.

    El router responde 401 con un mensaje genérico e idéntico en todos los
    casos (RN-09): ninguna subclase expone el detalle exacto del fallo.
    """


class EmailUsuarioDuplicado(Exception):
    """El email ya pertenece a un usuario: el alta responde 409 sin escribir nada (RN-01)."""


class UsuarioNoEncontrado(Exception):
    """El usuario indicado en la ruta no existe (US-009/US-010, 404)."""


class RolYaAsignado(Exception):
    """El usuario ya tiene una asignación abierta y vigente del mismo rol (RN-03, 409)."""


class RolNoVigente(Exception):
    """El usuario no tiene ese rol abierto (inexistente, revocado o vencido): 404."""


class AutorrevocacionProhibida(Exception):
    """Un ADMIN intentó revocar su propio ADMIN: el sistema se quedaría sin administradores (RN-05, 409)."""


class VencimientoInvalido(Exception):
    """El vencimiento del rol no es futuro o no lleva zona horaria (US-009, 422)."""


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


async def crear_empleado(
    uow: UoWUsuarios,
    datos: EntradaCrearUsuario,
    actor_email: str,
) -> Usuario:
    """Da de alta un empleado con contraseña provisoria y audita el alta (US-008, RN-01).

    El router construye el UoW y este servicio lo abre; `hash_password` corre
    **antes** del `async with` (regla dura: bcrypt nunca dentro de la
    transacción). El usuario queda con `debe_cambiar_password=True` y el evento
    `alta_personal` se escribe en la **misma** transacción (design.md, decisión 2).

    Args:
        uow: transacción de usuarios construida por el router (la abre el servicio).
        datos: contrato validado (`email` único, `nombre`, contraseña política).
        actor_email: email del ADMIN autenticado (autor del evento, US-011).

    Returns:
        El `Usuario` creado (con `id` tras la confirmación del UoW).

    Raises:
        EmailUsuarioDuplicado: si el email ya pertenece a otro usuario (409): no
            queda ni el usuario ni el evento.
        ValueError: si la contraseña no cumpliera la política (el contrato ya la
            validó; fail-fast defensivo).
        sqlalchemy.exc.IntegrityError: si la base rechaza la escritura por una
            carrera de unicidad (el router lo traduce a 409).
    """
    hash_calculado = await hash_password(datos.password)  # fuera de la transacción

    async with uow:
        if await uow.usuarios.get_por_email(datos.email) is not None:
            raise EmailUsuarioDuplicado(MENSAJE_EMAIL_USUARIO_DUPLICADO)

        usuario = await uow.usuarios.add(
            Usuario(
                email=datos.email,
                nombre=datos.nombre,
                password_hash=hash_calculado,
                debe_cambiar_password=True,
            )
        )
        await uow.eventos.registrar(
            actor_email, f"{ACCION_ALTA_PERSONAL}: {usuario.email}"
        )
    return usuario


async def otorgar_rol(
    uow: UoWUsuarios,
    usuario_id: int,
    datos: EntradaAsignarRol,
    actor_id: int,
    actor_email: str,
) -> AsignacionRol:
    """Abre una asignación de rol con vigencia opcional y audita el cambio (US-009, RN-03).

    Distingue los tres estados de la fila abierta (design.md, decisión 4):

    - abierta **vigente** (`vence_en` nulo o futuro) → `RolYaAsignado` (409);
    - abierta **vencida** → se cierra con `revocada_en = ahora` (no es una
      revocación: es el cierre de una asignación que ya no otorgaba permisos) y
      se abre la nueva fila;
    - sin fila abierta (nunca asignada o revocada) → se abre directamente.

    Args:
        uow: transacción de usuarios construida por el router (la abre el servicio).
        usuario_id: destinatario del rol (de la ruta).
        datos: `rol` del catálogo y `vencimiento` ya validado y normalizado.
        actor_id: id del ADMIN autenticado (va en `otorgada_por`, nunca en la ruta).
        actor_email: email del ADMIN autenticado (autor del evento, US-011).

    Returns:
        La asignación recién abierta (con `id` tras la confirmación del UoW).

    Raises:
        VencimientoInvalido: si el vencimiento no fuera futuro (422 defensivo,
            el contrato ya lo validó).
        UsuarioNoEncontrado: si el usuario de la ruta no existe (404).
        RolYaAsignado: si la fila abierta del rol sigue vigente (409).
        sqlalchemy.exc.IntegrityError: si dos ADMIN compiten por el mismo rol:
            el índice parcial es la garantía final (el router lo traduce a 409).
    """
    ahora = datetime.now(UTC)
    if datos.vencimiento is not None and datos.vencimiento <= ahora:
        raise VencimientoInvalido(MENSAJE_VENCIMIENTO_INVALIDO)

    async with uow:
        if await uow.usuarios.get_by_id(usuario_id) is None:
            raise UsuarioNoEncontrado(MENSAJE_USUARIO_NO_ENCONTRADO)

        abierta = await uow.roles.get_abierta(usuario_id, datos.rol)
        if abierta is not None:
            vigente = abierta.vence_en is None or abierta.vence_en > ahora
            if vigente:
                raise RolYaAsignado(MENSAJE_ROL_YA_ASIGNADO)
            # Cierre de la asignación vencida: conserva `desde` y el `vence_en` pactado.
            await uow.roles.revocar(abierta, ahora)

        asignacion = await uow.roles.asignar(
            usuario_id,
            datos.rol,
            vence_en=datos.vencimiento,
            otorgada_por=actor_id,
        )
        await uow.eventos.registrar(
            actor_email, f"{ACCION_ROL_OTORGADO}: {datos.rol} (usuario {usuario_id})"
        )
    return asignacion


async def revocar_rol(
    uow: UoWUsuarios,
    usuario_id: int,
    rol: str,
    actor_id: int,
    actor_email: str,
) -> AsignacionRol:
    """Cierra la asignación abierta escribiendo `revocada_en` y audita la revocación (US-010).

    La autoprotección de RN-05 se comprueba **antes** de abrir la transacción y
    de tocar cualquier fila: un ADMIN no puede revocar su propio `ADMIN`, pero
    sí puede revocar el `ADMIN` de otro usuario. La fila nunca se borra
    (design.md, decisión 5): el cierre conserva `desde`, `vence_en` y el historial.

    Args:
        uow: transacción de usuarios construida por el router (la abre el servicio).
        usuario_id: usuario afectado (de la ruta).
        rol: rol del catálogo a revocar (de la ruta).
        actor_id: id del ADMIN autenticado (nunca de la ruta).
        actor_email: email del ADMIN autenticado (autor del evento, US-011).

    Returns:
        La asignación revocada (con `revocada_en` escrito y `desde` intacto).

    Raises:
        AutorrevocacionProhibida: si el ADMIN intenta revocar su propio ADMIN (409).
        UsuarioNoEncontrado: si el usuario de la ruta no existe (404).
        RolNoVigente: si no hay asignación abierta o está vencida (404): no se
            modifica ninguna fila ni se escribe evento.
    """
    if actor_id == usuario_id and rol == ROL_ADMIN:
        raise AutorrevocacionProhibida(MENSAJE_AUTORREVOCACION)

    ahora = datetime.now(UTC)
    async with uow:
        if await uow.usuarios.get_by_id(usuario_id) is None:
            raise UsuarioNoEncontrado(MENSAJE_USUARIO_NO_ENCONTRADO)

        abierta = await uow.roles.get_abierta(usuario_id, rol)
        if abierta is None or (abierta.vence_en is not None and abierta.vence_en <= ahora):
            raise RolNoVigente(MENSAJE_ROL_NO_VIGENTE)

        revocada = await uow.roles.revocar(abierta, ahora)
        await uow.eventos.registrar(
            actor_email, f"{ACCION_ROL_REVOCADO}: {rol} (usuario {usuario_id})"
        )
    return revocada


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
        # Auditoría en la MISMA transacción del cambio (design.md, decisión 2):
        # el actor es el propio usuario que cambió su contraseña (US-011).
        await uow.eventos.registrar(usuario.email, ACCION_CAMBIO_PASSWORD)
        # El instante del cambio quedó anotado ANTES de emitir el token nuevo
        # (Flujo 3, paso 3): el token que devolverá esta petición sale después.

    return await roles_vigentes_de(sesion, _exigir_id(usuario_actualizado))


async def listar_eventos(
    uow: UoWUsuarios,
    parametros: ParametrosPagina,
) -> PaginaDe[EventoSeguridad]:
    """Consulta paginada de `evento_seguridad`, del más reciente al más antiguo (US-011).

    Args:
        uow: transacción de usuarios abierta por el router (patrón de listados).
        parametros: `page`/`size` ya validados por `ParametrosPagina` (422 propio).

    Returns:
        La página de eventos con el envoltorio estándar; `construir_pagina` rechaza
        con 422 una página mayor a la última disponible.

    Raises:
        HTTPException(422): página inexistente (mensaje propio de `construir_pagina`).
    """
    items, total = await uow.eventos.buscar_paginado(
        offset=parametros.desplazamiento, limit=parametros.size
    )
    return construir_pagina(list(items), total=total, parametros=parametros)
