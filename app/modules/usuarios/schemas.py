"""Contratos de entrada/salida del módulo usuarios (capa Schemas).

Reglas duras aplicadas: `extra="forbid"` en todos los contratos (nada de
confiar el input), `exclude` del hash en las salidas (RN-18: el hash nunca
viaja) y validación de la contraseña en la **entrada** (≤ 72 bytes y políticas
del AGENTS.md) para que los códigos `422` salgan antes de tocar la base.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import validar_password

ROL_ADMIN = "ADMIN"
ROLES_ASIGNABLES = ("ADMIN", "RECEPCION", "MECANICO", "CLIENTE")
MENSAJE_VENCIMIENTO_INVALIDO = (
    "El vencimiento debe ser una fecha futura y llevar zona horaria."
)


class _ContratoEstricto(BaseModel):
    """Base de contratos del módulo: rechaza campos no declarados."""

    model_config = ConfigDict(extra="forbid")


class EntradaRegistro(_ContratoEstricto):
    """Alta de cuenta propia (US-003): email único, nombre y contraseña política."""

    email: EmailStr
    nombre: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1)

    @field_validator("password", mode="after")
    @classmethod
    def _aplicar_politica(cls, valor: str) -> str:
        """Traduce la política de contraseñas a errores de validación (422).

        Args:
            valor: contraseña recibida (Pydantic garantiza `str`).

        Returns:
            La misma contraseña, si cumple la política.

        Raises:
            ValueError: con el mensaje de `validar_password` (Pydantic lo
                convierte en `422` con el texto propio).
        """
        # `validar_password` también puede negar el tipo; Pydantic ya garantizó `str`,
        # así que cualquier TypeError queda sin efecto acá (no se silencia: nunca
        # llega a ocurrir con `str` validado por el tipo del campo).
        validar_password(valor)
        return valor


class EntradaLogin(_ContratoEstricto):
    """Credenciales para la sesión (US-004): misma política de contraseña que el alta."""

    email: EmailStr
    password: str = Field(min_length=1)

    @field_validator("password", mode="after")
    @classmethod
    def _aplicar_politica(cls, valor: str) -> str:
        """Aplica la política (≤ 72 bytes): bcrypt jamás queda dentro del bucle.

        Las contraseñas imposibles (73+ bytes) no pertenecen a ninguna cuenta
        porque el registro las veda: el rechazo temprano a 422 no filtra nada.

        Args:
            valor: contraseña recibida.

        Returns:
            La misma contraseña, si cumple la política.

        Raises:
            ValueError: con el mensaje de `validar_password` (422).
        """
        validar_password(valor)
        return valor


class EntradaCambioPassword(_ContratoEstricto):
    """Cambio de contraseña con verificación de la actual (RN-07, US-007)."""

    password_actual: str = Field(min_length=1)
    password_nueva: str = Field(min_length=1)

    @field_validator("password_actual", "password_nueva", mode="after")
    @classmethod
    def _aplicar_politica(cls, valor: str) -> str:
        """La nueva contraseña respeta la misma política que el registro.

        Args:
            valor: contraseña recibida (actual o nueva).

        Returns:
            La misma contraseña, si cumple la política.

        Raises:
            ValueError: con el mensaje de `validar_password` (422).
        """
        validar_password(valor)
        return valor


class SalidaRegistro(_ContratoEstricto):
    """Respuesta del alta (sin hash, ni token, ni contraseña)."""

    email: EmailStr
    nombre: str
    rol: str


class SalidaLogin(_ContratoEstricto):
    """Respuesta del login/cambio: estado del flag y duración, NUNCA el token (DD-04)."""

    debe_cambiar_password: bool
    expira_en_segundos: int


class SalidaYo(_ContratoEstricto):
    """Identidad propia (US-006): roles vigentes (base) y del token, siempre separados."""

    email: EmailStr
    nombre: str
    debe_cambiar_password: bool
    roles_vigentes: list[str]
    roles_token: list[str]


class SalidaLogout(_ContratoEstricto):
    """Respuesta del logout: mensaje propio, sin datos de sesión (US-005)."""

    mensaje: str


# ── Contratos de administración de personal y auditoría (C-06) ───────────────


class EntradaCrearUsuario(_ContratoEstricto):
    """Alta de personal por un ADMIN (US-008): provisoria con la política vigente."""

    email: EmailStr
    nombre: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1)

    @field_validator("password", mode="after")
    @classmethod
    def _aplicar_politica(cls, valor: str) -> str:
        """Aplica la política de contraseñas antes de abrir la transacción (422).

        Args:
            valor: contraseña provisoria recibida.

        Returns:
            La misma contraseña, si cumple la política (≤ 72 bytes incluidos).

        Raises:
            ValueError: con el mensaje de `validar_password` (Pydantic lo
                convierte en `422` con el texto propio).
        """
        validar_password(valor)
        return valor


class SalidaUsuario(_ContratoEstricto):
    """Usuario creado o consultado: nunca expone hash ni contraseña (RN-18)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    email: EmailStr
    nombre: str
    activo: bool
    debe_cambiar_password: bool


class EntradaAsignarRol(_ContratoEstricto):
    """Otorgamiento de rol con vencimiento opcional (US-009, RN-03).

    `vencimiento` debe llevar zona horaria (Pydantic v2 rechaza `datetime`
    ingenuo con 422) y ser futuro; se normaliza a UTC antes de persistir.
    """

    rol: Literal["ADMIN", "RECEPCION", "MECANICO", "CLIENTE"]
    vencimiento: AwareDatetime | None = None

    @field_validator("vencimiento", mode="after")
    @classmethod
    def _exigir_futuro_con_zona(cls, valor: datetime | None) -> datetime | None:
        """Normaliza a UTC y exige que el vencimiento sea posterior al instante actual.

        Args:
            valor: vencimiento recibido (Pydantic ya exigió zona horaria).

        Returns:
            El vencimiento en UTC, o `None` si no se envió.

        Raises:
            ValueError: si el vencimiento no es futuro (`422`).
        """
        if valor is None:
            return None
        normalizado = valor.astimezone(UTC)
        if normalizado <= datetime.now(UTC):
            raise ValueError(MENSAJE_VENCIMIENTO_INVALIDO)
        return normalizado


class SalidaAsignacionRol(_ContratoEstricto):
    """Asignación de rol devuelta por el alta y por la revocación (US-009/US-010)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    usuario_id: int
    rol: str
    desde: datetime
    vence_en: datetime | None = None
    revocada_en: datetime | None = None
    otorgada_por: int | None = None


class SalidaEvento(_ContratoEstricto):
    """Evento de seguridad consultable por el ADMIN (US-011)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    cuando: datetime
    actor: str
    accion: str
