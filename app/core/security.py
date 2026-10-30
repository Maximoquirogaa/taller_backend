"""Herramientas de seguridad: bcrypt asincrónico y JWT (reglas duras del proyecto).

- bcrypt NUNCA corre dentro del bucle de eventos (`to_thread`) ni dentro de una
  transacción: el hash se calcula **antes** de abrir el Unit of Work. Cada
  operación bcrypt limita su concurrencia con un semáforo (CLAUDE.md: bcrypt
  bloquea un hilo del pool).
- bcrypt 5 rechaza contraseñas de más de 72 bytes con su propio ValueError:
  `validar_password` se el aplica **antes** de hashear (fail-fast, AGENTS.md) y
  el contrato de entrada (`Schemas`) la aplica también → 422 sin llegar acá.
- JWT (PyJWT) firmado con `SECRET_KEY`: el token lleva `sub`, `iat` con
  fracciones (sin truncar a segundos, RN-07/DD-05), `exp` y los roles vigentes
  (informativos; la autorización consulta la base en cada petición, RN-04).
- `obtener_hash_ficticio` (DD-06/RN-09): verificación contra un hash inventado
  cuando el email no existe, para que el login tarde igual exista o no la cuenta.
  Se calcula en la primera llamada y se reutiliza (nunca se construye al
  importar; DD-09 — el único costo es una sola verificación bcrypt inicial).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import bcrypt
import jwt

from app.modules.usuarios.models import Usuario

# ── Constantes (sin números mágicos en el cuerpo de las funciones) ───────────

MAX_BICITOS_CONTRASENA = 72  # límite de entrada del algoritmo bcrypt
MIN_LONGITUD_CONTRASENA = 8  # política mínima de contraseña del TP
COSTO_BCRYPT_PREDETERMINADO = 12  # SU-02: coincide con Settings.bcrypt_cost
MIN_COSTO_BCRYPT = 4  # rango válido de rounds según bcrypt
MAX_COSTO_BCRYPT = 31
LIMITE_CONCURRENCIA_BCRYPT = 10  # semáforo: hilos de bcrypt simultáneos
ALGORITMO_JWT = "HS256"
EXPIRACION_MINIMA_SEGUNDOS = 1  # un token sin vencimiento no es aceptable
MENSAJE_TIPO_INCORRECTO = "El valor ingresado debe ser una cadena de texto"
MENSAJE_TOKEN_INVALIDO = "El token de sesión no es válido"
PREFIJO_HASH_BCRYPT = "$2b$"
MENSAJE_VACIA = "La contraseña no puede estar vacía"
MENSAJE_CORTA = (
    f"La contraseña es demasiado corta: debe tener al menos {MIN_LONGITUD_CONTRASENA} caracteres"
)
MENSAJE_LARGA = (
    f"La contraseña es demasiado larga: no debe superar los {MAX_BICITOS_CONTRASENA} caracteres"
)
MENSAJE_ESPACIOS = "La contraseña no debe contener espacios en blanco"
MENSAJE_SIN_NUMERO = "La contraseña debe incluir al menos un número"
MENSAJE_COSTO = f"El costo bcrypt debe estar entre {MIN_COSTO_BCRYPT} y {MAX_COSTO_BCRYPT}"

_semaforo_bcrypt = asyncio.Semaphore(LIMITE_CONCURRENCIA_BCRYPT)
_hash_ficticio: str | None = None  # singleton perezoso (ver `obtener_hash_ficticio`)


class TokenInvalido(ValueError):
    """Token de sesión inválido: vencido, mal firmado, sin claims o malformado.

    La dependencia de usuario actual la traduce a `HTTPException(401)`; acá vive
    solo para no propagar errores crudos de PyJWT hacia routers.
    """


def validar_password(contrasena: str) -> None:
    """Valida la contraseña con reglas fail-fast y mensajes en español (AGENTS.md).

    Orden secuencial lógico: tipo → vacía → longitudes → inspección de contenido.

    Args:
        contrasena: contraseña propuesta (texto plano en memoria, nunca persiste).

    Raises:
        TypeError: si `contrasena` no es `str` (mensaje estándar del proyecto).
        ValueError: si está vacía, si tiene menos de `MIN_LONGITUD_CONTRASENA`
            caracteres, si ocupa más de `MAX_BICITOS_CONTRASENA` bytes (límite
            del algoritmo bcrypt; se mide en **bytes**, no en caracteres), si
            contiene espacios en blanco (incluye tabulaciones y saltos) o si no
            incluye al menos un dígito numérico.
    """
    if not isinstance(contrasena, str):
        raise TypeError(MENSAJE_TIPO_INCORRECTO)
    if contrasena == "":
        raise ValueError(MENSAJE_VACIA)
    if len(contrasena) < MIN_LONGITUD_CONTRASENA:
        raise ValueError(MENSAJE_CORTA)
    if len(contrasena.encode("utf-8")) > MAX_BICITOS_CONTRASENA:
        raise ValueError(MENSAJE_LARGA)
    if any(caracter.isspace() for caracter in contrasena):
        raise ValueError(MENSAJE_ESPACIOS)
    if not any(caracter.isdigit() for caracter in contrasena):
        raise ValueError(MENSAJE_SIN_NUMERO)


def _hash_bcrypt(contrasena: str, costo: int) -> str:
    """Trabajo de bcrypt puro (solo desde `hash_password`, en otro hilo)."""
    return bcrypt.hashpw(
        contrasena.encode("utf-8"),
        bcrypt.gensalt(rounds=costo),
    ).decode("utf-8")


def _verificar_bcrypt(contrasena: str, hash_guardado: str) -> bool:
    """Verificación de bcrypt puro (solo desde `verificar_password`, en otro hilo)."""
    return bcrypt.checkpw(contrasena.encode("utf-8"), hash_guardado.encode("utf-8"))


def _validar_costo(costo: int) -> int:
    """Comprueba el costo de bcrypt dentro del rango del algoritmo.

    Args:
        costo: valor leído de `Settings.bcrypt_cost` (debe ser `int`).

    Returns:
        El mismo costo, si es válido.

    Raises:
        TypeError: si `costo` no es `int`.
        ValueError: si queda fuera de `[MIN_COSTO_BCRYPT, MAX_COSTO_BCRYPT]`.
    """
    if not isinstance(costo, int) or isinstance(costo, bool):
        raise TypeError("El costo bcrypt debe ser un número entero")
    if not (MIN_COSTO_BCRYPT <= costo <= MAX_COSTO_BCRYPT):
        raise ValueError(MENSAJE_COSTO)
    return costo


async def hash_password(contrasena: str, costo: int = COSTO_BCRYPT_PREDETERMINADO) -> str:
    """Hashea con bcrypt **fuera del bucle** (`to_thread` + semáforo, regla dura).

    Args:
        contrasena: contraseña a hashear; se valida completa antes de tocar bcrypt.
        costo: costo del algoritmo (`BCRYPT_COST` de Settings); defecto 12 (SU-02).

    Returns:
        El hash bcrypt textual (`$2b$...`), a guardar en `usuario.password_hash`.

    Raises:
        TypeError: si `contrasena` no es `str` (mensaje estándar del proyecto).
        ValueError: si la contraseña viola alguna regla de `validar_password`
            o si `costo` queda fuera del rango válido del algoritmo.
    """
    validar_password(contrasena)
    costo_validado = _validar_costo(costo)
    async with _semaforo_bcrypt:
        return await asyncio.to_thread(_hash_bcrypt, contrasena, costo_validado)


async def verificar_password(contrasena: str, hash_guardado: str) -> bool:
    """Verifica una contraseña contra un hash bcrypt (también fuera del bucle).

    Args:
        contrasena: contraseña propuesta por el usuario.
        hash_guardado: hash `$2b$...` del usuario o el **hash ficticio** (DD-06).

    Returns:
        `True` solo si `contrasena` corresponde a `hash_guardado`.

    Raises:
        TypeError: si algún parámetro no es `str` (mensaje estándar).
        ValueError: si `hash_guardado` no tiene forma de hash bcrypt (una fila
            de hash corrupta no indica un ataque, solo un hash inútil: se
            informa con el tipo correcto en lugar de devolver `False` a ciegas).
    """
    if not isinstance(contrasena, str) or not isinstance(hash_guardado, str):
        raise TypeError(MENSAJE_TIPO_INCORRECTO)
    if not hash_guardado.startswith(PREFIJO_HASH_BCRYPT):
        raise ValueError("El hash guardado no tiene el formato de bcrypt")
    async with _semaforo_bcrypt:
        return await asyncio.to_thread(_verificar_bcrypt, contrasena, hash_guardado)


async def obtener_hash_ficticio(costo: int = COSTO_BCRYPT_PREDETERMINADO) -> str:
    """Hash bcrypt inventado para verificar logins de emails inexistentes (DD-06).

    Se calcula una sola vez por proceso y se reutiliza: con costo igual al real
    el tiempo de respuesta no distingue cuentas existentes (RN-09).

    Args:
        costo: costo bcrypt (mismo de producción para igualar el tiempo).

    Returns:
        Un hash bcrypt real de una contraseña que nadie conoce.

    Raises:
        TypeError: si `costo` no es `int`.
        ValueError: si `costo` queda fuera del rango válido.
    """
    global _hash_ficticio
    if _hash_ficticio is None:
        # Contraseña descartada en memoria: nadie puede iniciar sesión con ella
        # porque nunca coincide con ningún usuario y va al hash ficticio.
        contrasena_ficticia = "taller-ficticio-" + repr(time.time())
        _hash_ficticio = await hash_password(contrasena_ficticia, costo)
    return _hash_ficticio


def crear_token_acceso(
    id_usuario: int,
    roles: list[str],
    secreto: str,
    expira_en_segundos: int,
) -> str:
    """Firma un JWT de sesión con claims mínimos e `iat` sin truncar (RN-07).

    Args:
        id_usuario: identificador de `usuario.id` (`sub` del token).
        roles: roles vigentes al emitir el token; informativos (RN-04).
        secreto: `Settings.secret_key`; sin default y jamás se loguea.
        expira_en_segundos: `jwt` devuelve un `str` firmado (cookie `access_token`).

    Returns:
        El token textual que la cookie de sesión llevará en su valor.

    Raises:
        TypeError: si `id_usuario` no es `int` (bool no cuenta), `roles` no es
            lista de `str`, `secreto` no es `str` o `expira_en_segundos` no es `int`.
        ValueError: si `secreto` está vacío o `expira_en_segundos`` es menor que
            `EXPIRACION_MINIMA_SEGUNDOS` (un token sin vencimiento no vale).
    """
    if not isinstance(id_usuario, int) or isinstance(id_usuario, bool):
        raise TypeError("El id del usuario debe ser un número entero")
    if not isinstance(roles, list) or not all(isinstance(rol, str) for rol in roles):
        raise TypeError("Los roles deben ser una lista de cadenas de texto")
    if not isinstance(secreto, str):
        raise TypeError(MENSAJE_TIPO_INCORRECTO)
    if secreto == "":
        raise ValueError("El secreto de firma no puede estar vacío")
    if not isinstance(expira_en_segundos, int) or isinstance(expira_en_segundos, bool):
        raise TypeError("La expiración debe ser un número entero de segundos")
    if expira_en_segundos < EXPIRACION_MINIMA_SEGUNDOS:
        raise ValueError(f"La expiración debe ser de al menos {EXPIRACION_MINIMA_SEGUNDOS} segundo")

    instantes = _ahora_titulo()  # instante de emisión COMPLETO (float, DD-05)
    payload: dict[str, Any] = {
        "sub": str(id_usuario),
        "iat": instantes,
        "exp": instantes + expira_en_segundos,
        "roles": list(roles),
    }
    return jwt.encode(payload, secreto, algorithm=ALGORITMO_JWT)


def _ahora_titulo() -> float:
    """Instante actual como marca de tiempo completa (no entera, DD-05)."""
    return time.time()


def decode_token(token: str, secreto: str) -> dict[str, Any]:
    """Verifica firma y vencimiento del JWT y devuelve sus claims completos.

    Args:
        token: valor de la cookie de sesión (nunca de `Authorization: Bearer`).
        secreto: `Settings.secret_key` (el mismo con el que se firmó).

    Returns:
        Los claims del token: `sub` (texto), `iat` (flotante sin truncar), `exp`
        y `roles` (los roles informativos del momento de emisión).

    Raises:
        TypeError: si algún parámetro no es `str`.
        TokenInvalido: si la firma no coincide, el algoritmo difiere, el token
            está vencido, malformado o le faltan claims de sesión (`sub`, `iat`,
            `exp`, `roles`) o `sub` no es un entero textual.
    """
    if not isinstance(token, str) or not isinstance(secreto, str):
        raise TypeError(MENSAJE_TIPO_INCORRECTO)
    claims_requeridos = ("sub", "iat", "exp", "roles")
    try:
        payload = jwt.decode(token, secreto, algorithms=[ALGORITMO_JWT])
        for claim in claims_requeridos:
            if claim not in payload:
                raise TokenInvalido(MENSAJE_TOKEN_INVALIDO)
        int(payload["sub"])  # `sub` debe representar un id de usuario
        if not isinstance(payload["iat"], float) or not isinstance(payload["roles"], list):
            raise TokenInvalido(MENSAJE_TOKEN_INVALIDO)
    except jwt.PyJWTError as excepcion:
        raise TokenInvalido(MENSAJE_TOKEN_INVALIDO) from excepcion
    except (TypeError, ValueError) as excepcion:
        # `int(sub)` inválido o los tipos de claims inesperados: también sesión inválida.
        raise TokenInvalido(MENSAJE_TOKEN_INVALIDO) from excepcion
    return payload


def instantes_token_contra_cambio(payload: dict[str, Any], usuario: Usuario) -> bool:
    """Decide si el token es **anterior** al último cambio de contraseña (RN-07).

    Args:
        payload: claims devueltos por `decode_token` (`iat` flotante).
        usuario: fila cargada de la base en esta petición.

    Returns:
        `True` si el token fue emitido **antes** del cambio de contraseña
        (comparación completa, con fracciones — el token expira/invalida y la
        dependencia debe responder 401); `False` si `usuario.password_cambiada_en`
        es `NULL` o el token es posterior o simultáneo-menos.
    """
    if usuario.password_cambiada_en is None:
        return False
    iat = float(payload["iat"])  # garantizado flotante por decode_token
    return iat < usuario.password_cambiada_en.timestamp()
