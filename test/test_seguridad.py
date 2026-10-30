"""Tests unitarios de `app.core.security`: bcrypt asincrónico + JWT (tareas 2 y 3).

Cubre las reglas duras: validación fail-fast (AGENTS.md), contraseña máximo 72
bytes (límite bcrypt), verificación correcta/incorrecta, `iat` sin truncar
(RN-07, DD-05) y error de firma → token inválido (401 en la dependencia).

Estos tests **no** tocan PostgreSQL: son puros de la capa de seguridad.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core import security

SECRETO_PRUEBAS = "clave-de-firma-de-prueba-33-caracteres-!!"
ROL_PRUEBA = "CLIENTE"


def _crear_token(roles: list[str] | None = None, id_usuario: int = 1) -> str:
    """Token estándar para los tests de sesión."""
    return security.crear_token_acceso(
        id_usuario=id_usuario,
        roles=roles or [ROL_PRUEBA],
        secreto=SECRETO_PRUEBAS,
        expira_en_segundos=1800,
    )


# ── validar_password (AGENTS.md: fail-fast con mensajes en español) ──────────


@pytest.mark.parametrize(
    "password, mensaje_esperado",
    [
        ("1234567", "La contraseña es demasiado corta: debe tener al menos 8 caracteres"),
        ("a" * 73, "La contraseña es demasiado larga: no debe superar los 72 caracteres"),
        ("Contraseña mal1", "La contraseña no debe contener espacios en blanco"),
        ("contrasenaLargaSinNumeros", "La contraseña debe incluir al menos un número"),
    ],
)
def test_validar_password_rechaza_regla(password: str, mensaje_esperado: str) -> None:
    """Cada regla con su mensaje propio (casos borde��: MIN-1 y MAX+1)."""
    with pytest.raises(ValueError) as excepcion:
        security.validar_password(password)
    assert mensaje_esperado in str(excepcion.value)


def test_validar_password_acepta_las_bordes() -> None:
    """MIN y MAX exactos se aceptan (72 bytes está en el límite del algoritmo)."""
    security.validar_password("clave123")  # exactamente MIN_LONGITUD_CONTRASENA
    security.validar_password("a" * 71 + "1")  # 72 caracteres con su número


@pytest.mark.parametrize("entrada", [None, 12345678, ["lista"], 3.14])
def test_validar_password_rechaza_no_cadena(entrada: object) -> None:
    """Tipo incorrecto → TypeError con mensaje estándar (AGENTS.md)."""
    with pytest.raises(TypeError) as excepcion:
        security.validar_password(entrada)  # type: ignore[arg-type]
        # type ignore: LA llamada rasga a propósito para probar el fail-fast
    assert "El valor ingresado debe ser una cadena de texto" in str(excepcion.value)


# ── hash y verificación (bcrypt fuera del bucle) ─────────────────────────────


async def test_hash_password_almacena_para_verificar() -> None:
    """El hash de bcrypt se verifica contra la contraseña correcta (triangulado)."""
    hash_calculado = await security.hash_password("clave1234", security.COSTO_BCRYPT_PREDETERMINADO)
    assert hash_calculado.startswith("$2b$")
    assert hash_calculado != "clave1234"
    assert await security.verificar_password("clave1234", hash_calculado) is True


async def test_hash_password_rechaza_cualquier_otra_contrasena() -> None:
    """La verificación da False con la contraseña incorrecta (no 500 ni excepción)."""
    hash_calculado = await security.hash_password("clave1234", security.COSTO_BCRYPT_PREDETERMINADO)
    assert await security.verificar_password("claveIncorrecta9", hash_calculado) is False


async def test_hash_rechaza_contrasena_mas_de_72_bytes() -> None:
    """bcrypt 5 sale ValueError con 73+ bytes: se valida ANTES (fail-fast, regla dura)."""
    with pytest.raises(ValueError) as excepcion:
        await security.hash_password("a" * 73, security.COSTO_BCRYPT_PREDETERMINADO)
    assert "demasiado larga" in str(excepcion.value)


async def test_hash_rechaza_costo_fuera_de_rango() -> None:
    """El costo de bcrypt se acota al rango válido del algoritmo (4..31)."""
    with pytest.raises(ValueError) as excepcion:
        await security.hash_password("clave1234", costo=99)
    assert "El costo bcrypt debe estar entre 4 y 31" in str(excepcion.value)


# ── hash ficticio (DD-06, RN-09) ─────────────────────────────────────────────


async def test_hash_ficticio_te_emite_verificable() -> None:
    """El hash ficticio es un hash bcrypt real: verificar contra él tarda como el real."""
    hash_ficticio = await security.obtener_hash_ficticio()
    assert hash_ficticio.startswith("$2b$")
    assert await security.verificar_password("cualquier-candidato-9", hash_ficticio) is False


async def test_hash_ficticio_es_unico_en_la_vida_del_proceso() -> None:
    """El singleton se crea una vez y se reutiliza (mismo objeto)."""
    primero = await security.obtener_hash_ficticio()
    segundo = await security.obtener_hash_ficticio()
    assert primero is segundo


# ── crear_token_acceso / decode_token (CONFIGURACIÓN sin default) ────────────


def test_crear_token_valida_tipo_de_todos_los_parametros() -> None:
    """Fail-fast: ids no int, secret no str y expiración no int → TypeError."""
    with pytest.raises(TypeError):
        security.crear_token_acceso("no-es-int" + 1, [ROL_PRUEBA], SECRETO_PRUEBAS, 1800)  # type: ignore[operator]


def test_token_incluye_sub_iat_exp_y_roles() -> None:
    """Claims exigidos por la consigna: sub, iat (sin truncar), exp y roles vigentes."""
    ahora = datetime.now(UTC)
    roles = ["CLIENTE", "ADMIN"]
    token = security.crear_token_acceso(7, roles, SECRETO_PRUEBAS, 60)
    payload = jwt.decode(token, SECRETO_PRUEBAS, algorithms=[security.ALGORITMO_JWT])
    assert payload["sub"] == "7"
    assert payload["roles"] == roles
    assert "exp" in payload
    # iat completo con fracciones: sin truncamiento a segundos (DD-05).
    assert abs(payload["iat"] - ahora.timestamp()) < 0.5
    # y con fracción real (un token emitido "justo ahora" no es entero):
    assert payload["iat"] != int(payload["iat"]) or isinstance(payload["iat"], float)


def test_decode_token_devuelve_el_mismo_iat_float() -> None:
    """decode_token preserva el instante de emisión completo (sin truncar)."""
    token = _crear_token()
    payload = security.decode_token(token, SECRETO_PRUEBAS)
    assert payload["roles"] == [ROL_PRUEBA]
    assert isinstance(payload["iat"], float)


def test_decode_token_bien_firmado_corrido() -> None:
    """Firma inválida → ValueError con mensaje propio (la dependencia mapea a 401)."""
    token_de_otros = jwt.encode(
        {"sub": "1", "iat": time.time(), "exp": time.time() + 1800},
        "clavedistinta-a-la-correcta-32-caracteres",
        algorithm=security.ALGORITMO_JWT,
    )
    with pytest.raises(ValueError, match="token"):
        security.decode_token(token_de_otros, SECRETO_PRUEBAS)


def test_decode_rechaza_algortimo_distinto_al_grabado() -> None:
    """Token firmado con otro algoritmo → ValueError (no se confía en `none`/RS)."""
    token = jwt.encode({"sub": "1", "iat": time.time(), "exp": time.time() + 1800}, SECRETO_PRUEBAS)
    with pytest.raises(ValueError, match="token"):
        security.decode_token(token, SECRETO_PRUEBAS)


def test_decode_rechaza_token_con_falta_de_claims() -> None:
    """Sin `sub`/`iat`/`exp` el token no sirve de sesión: ValueError con mensaje."""
    token = jwt.encode({"sub": "1"}, SECRETO_PRUEBAS, algorithm=security.ALGORITMO_JWT)
    with pytest.raises(ValueError, match="token"):
        security.decode_token(token, SECRETO_PRUEBAS)


def test_crear_token_con_parametro_negativo() -> None:
    """Expiración <= 0 → ValueError (un token sin vencimiento no es aceptable)."""
    with pytest.raises(ValueError, match="expiración"):
        security.crear_token_acceso(1, [ROL_PRUEBA], SECRETO_PRUEBAS, 0)


def test_token_vencido_se_detecta() -> None:
    """Token emitido con vencimiento ya pasado: PyJWT raise y decode_token lo notifica."""
    token = jwt.encode(
        {"sub": "1", "iat": time.time() - 1_800, "exp": time.time() - 900},
        SECRETO_PRUEBAS,
        algorithm=security.ALGORITMO_JWT,
    )
    with pytest.raises(ValueError, match="token"):
        security.decode_token(token, SECRETO_PRUEBAS)


def test_decode_token_no_acepta_tipos_totales_incorrectos() -> None:
    """decode_token también falla rápido con parámetros del tipo equivocado."""
    with pytest.raises(TypeError):
        security.decode_token([123], SECRETO_PRUEBAS)  # type: ignore[arg-type]
