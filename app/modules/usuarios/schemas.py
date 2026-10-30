"""Contratos de entrada/salida del módulo usuarios (capa Schemas).

Reglas duras aplicadas: `extra="forbid"` en todos los contratos (nada de
confiar el input), `exclude` del hash en las salidas (RN-18: el hash nunca
viaja) y validación de la contraseña en la **entrada** (≤ 72 bytes y políticas
del AGENTS.md) para que los códigos `422` salgan antes de tocar la base.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import validar_password


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
