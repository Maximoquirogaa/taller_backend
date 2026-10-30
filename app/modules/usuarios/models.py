"""Modelos de tabla del módulo usuarios (SQLModel) — capa Model.

Las cuatro tablas de acceso viven acá (D1): `usuario`, `asignacion_rol`,
`intento_acceso` y `evento_seguridad`. La unicidad y el catálogo de roles los
garantiza PostgreSQL (D2/D3); el esquema lo crea **solo** Alembic (DD-08).

Fechas: todas las columnas temporales son `timestamptz` (`timezone=True`, D7) y
las que marcan el instante del hecho usan `server_default=func.now()` para que
el reloj sea el de la base.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, func, text
from sqlmodel import Field, SQLModel

ROLES_VALIDOS = ("ADMIN", "RECEPCION", "MECANICO", "CLIENTE")


class Usuario(SQLModel, table=True):
    """Cuenta de acceso: email único, hash de contraseña y banderas de vigencia."""

    __tablename__ = "usuario"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(
        max_length=254,
        unique=True,
        description="Correo de login; único en toda la tabla (spec access-data-model).",
    )
    nombre: str = Field(max_length=120)
    password_hash: str = Field(max_length=255, repr=False)
    activo: bool = Field(default=True)
    debe_cambiar_password: bool = Field(default=False)
    password_cambiada_en: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        description="Instante del último cambio de contraseña (lo setea la app, D7).",
    )


class AsignacionRol(SQLModel, table=True):
    """Rol otorgado a un usuario con vigencia; se revoca marcando, nunca borrando.

    `rol` es texto con CHECK al catálogo de la consigna (D2) y la unicidad se
    limita a las asignaciones abiertas con un índice único parcial (D3, RN-03).
    """

    __tablename__ = "asignacion_rol"
    __table_args__ = (
        CheckConstraint(
            "rol IN (" + ", ".join(f"'{rol}'" for rol in ROLES_VALIDOS) + ")",
            name="ck_asignacion_rol_rol_valido",
        ),
        Index(
            "uq_asignacion_rol_abierta",
            "usuario_id",
            "rol",
            unique=True,
            postgresql_where=text("revocada_en IS NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id", index=True)
    rol: str = Field(max_length=20)
    desde: datetime = Field(
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )
    vence_en: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    revocada_en: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        description="Marca de revocación: NULL = asignación vigente.",
    )
    otorgada_por: int | None = Field(default=None, foreign_key="usuario.id", index=True)


class IntentoAcceso(SQLModel, table=True):
    """Intento de login (éxito o fallo): auditoría sin FK, sobrevive al rollback.

    Sin relación con `usuario` a propósito (DD-07): el intento fallido sobre un
    email inexistente también se registra. El índice `(email, ip, cuando)` es la
    base del límite de intentos de RN-08.
    """

    __tablename__ = "intento_acceso"
    __table_args__ = (
        Index("ix_intento_acceso_email_ip_cuando", "email", "ip", "cuando"),
    )

    id: int | None = Field(default=None, primary_key=True)
    cuando: datetime = Field(
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )
    email: str = Field(max_length=254)
    ip: str = Field(max_length=45, description="IPv4 o IPv6 en texto (45 caracteres alcanzan).")
    exito: bool = Field(default=False)


class EventoSeguridad(SQLModel, table=True):
    """Evento de auditoría de seguridad: `actor` es texto libre, sin FK (DD-07)."""

    __tablename__ = "evento_seguridad"

    id: int | None = Field(default=None, primary_key=True)
    cuando: datetime = Field(
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )
    actor: str = Field(max_length=120, description="`SISTEMA` o el email del usuario que actuó.")
    accion: str = Field(max_length=255)
