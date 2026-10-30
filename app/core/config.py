"""Settings de la aplicación (spec `service-configuration`).

Todos los valores salen del entorno o de `.env` (no versionado). `SECRET_KEY` y
`POSTGRES_PASSWORD` no tienen valor por defecto en el código: si faltan, Pydantic
falla al instanciar y la aplicación no arranca (fallo temprano, sin claves
inventadas).
"""

from urllib.parse import quote

from pydantic import Field, ValidationError, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración leída de variables de entorno o del archivo `.env`.

    Campos sensibles (`postgres_password`, `secret_key`) sin valor por defecto y
    no vacíos: la app no arranca si faltan (RNF "Credenciales", DD-09).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Base de datos ────────────────────────────────────────────────────
    postgres_user: str
    postgres_password: str = Field(min_length=1, repr=False)
    postgres_db: str
    postgres_host: str
    postgres_port: int = 5432
    pool_size: int = 5

    # ── Seguridad ────────────────────────────────────────────────────────
    secret_key: str = Field(min_length=1, repr=False)
    bcrypt_cost: int = 12
    token_expire_segundos: int = 1800
    cookie_secure: bool = False

    # ── Diagnóstico ──────────────────────────────────────────────────────
    sql_echo: bool = False

    @computed_field(repr=False)
    @property
    def database_url(self) -> str:
        """URL asincrónica `postgresql+asyncpg://` (user y password con `quote`).

        `quote(..., safe="")` protege contra caracteres especiales en la
        contraseña; la URL no se registra en logs.
        """
        return (
            f"postgresql+asyncpg://{quote(self.postgres_user, safe='')}:"
            f"{quote(self.postgres_password, safe='')}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def cargar_settings() -> Settings:
    """Instancia `Settings` con mensaje propio si falta configuración.

    Si faltan `SECRET_KEY`, `POSTGRES_PASSWORD` u otra variable requerida, la
    app no arranca: el error nombra lo que falta en lugar de inventar valores.
    """
    try:
        return Settings()
    except ValidationError as exc:
        faltantes = sorted({str(error["loc"][0]).upper() for error in exc.errors()})
        raise SystemExit(
            "Configuración incompleta: faltan "
            + ", ".join(faltantes)
            + ". Completá el archivo .env (hay una plantilla en env.example): "
            "la aplicación no arranca sin estos valores."
        ) from exc
