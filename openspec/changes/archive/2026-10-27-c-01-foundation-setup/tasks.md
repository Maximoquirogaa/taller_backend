# Tasks

## 1. Estructura y dependencias

- [x] 1.1 Crear la estructura de directorios obligatoria (`main.py`, `seed.py` stub, `app/core/`, `app/modules/{health,usuarios,clientes,repuestos,ordenes}/` con sus 6 archivos por módulo, `migrations/`, `test/`) — verificar: `tree`/exploración muestra todas las rutas de `knowledge-base/08_arquitectura_propuesta.md` §Estructura
- [x] 1.2 Escribir `requirements.txt` con el stack congelado (fastapi[standard], SQLModel≥0.0.24, SQLAlchemy[asyncio] 2.0, **asyncpg**, alembic, pydantic-settings, bcrypt, PyJWT) — verificar: `pip install -r requirements.txt` en un venv limpio termina sin errores
- [x] 1.3 Escribir `env.example` con todas las variables de `app/core/config.py` y ningún valor sensible (passwords/secretos vacíos o con placeholder) — verificar: `Select-String -Path env.example -Pattern 'valor real|password.*='` no muestra secretos y las claves coinciden 1:1 con Settings

## 2. Configuración (spec `service-configuration`)

- [x] 2.1 Implementar `app/core/config.py` (`Settings` con pydantic-settings, `SECRET_KEY` y `POSTGRES_PASSWORD` sin default, `@computed_field` de la URL `postgresql+asyncpg://` con `quote`, `BCRYPT_COST`, `TOKEN_EXPIRE_SEGUNDOS=1800`, `COOKIE_SECURE`, `SQL_ECHO` default false, `env_file=".env"`) — verificar: `python -c "from app.core.config import Settings; Settings(_env_file=None)"` **falla** sin env; con las 5 `POSTGRES_*` + `SECRET_KEY` seteadas devuelve una URL `postgresql+asyncpg://...` correcta
- [x] 2.2 Crear `.env` local de desarrollo a partir de `env.example` (con `SQL_ECHO=true`) y confirmar que está excluido del versionado (`.gitignore` con `.env`) — verificar: el repo no trackea `.env` y `python -c "from app.core.config import Settings; print(Settings().database_url)"` lo lee sin exponer la contraseña en el print de configuración

## 3. Ciclo de vida (spec `service-lifespan`)

- [x] 3.1 Implementar `app/core/database.py`: creador de motor + fábrica (`expire_on_commit=False`) y `get_session` que toma la fábrica de `app.state` y cierra la sesión al final — verificar: `python -c "import app.core.database"` corre **sin bucle de eventos** y no construye ningún motor (no hay error de loop)
- [x] 3.2 Implementar `main.py` con `lifespan` asincrónico (crea motor/fábrica → `app.state`; al salir `await engine.dispose()`) y monta `router_abierto` + `router_protegido` (este último vacío, patrón de D4) — verificar: `uvicorn main:app` arranca y apaga sin traceback (se ve el dispose en el log)

## 4. Salud (spec `service-health`)

- [x] 4.1 Implementar `app/modules/health/router.py`: `GET /health/live` (200 sin tocar la base) y `GET /health/ready` (`SELECT 1` vía sesión de `app.state` → 200/503) montados en el grupo abierto — verificar: con el server arriba y PG caído, live=200 y ready=503; con PG arriba, ambas 200
- [x] 4.2 Crear `test/salud.http` con los dos GET y la respuesta esperada en comentario (incluido el caso 503) — verificar: correr el archivo con la extensión REST Client reproduce lo documentado en el comentario

## 5. Alembic asincrónico (spec `service-configuration` / D6)

- [x] 5.1 `alembic init migrations` + adaptar `env.py` al template asincrónico (`async_engine_from_config` + `run_sync`) leyendo la URL de Settings, y dejar `alembic.ini` sin credenciales — verificar: con `.env` cargado, `alembic upgrade head` sobre base vacía corre (no-op) y `alembic current` responde sin error; `grep -i password alembic.ini` no encuentra nada

## 6. Verificación integral

- [x] 6.1 Escenario de arranque completo: sin `SECRET_KEY` → la app **no arranca** (fallo temprano, mensaje propio); con `.env` completo y PG arriba → `GET /health/live`=200 y `GET /health/ready`=200 — verificar: ambos resultados observados en una corrida manual
- [x] 6.2 Revisión de reglas duras aplicables de `AGENTS.md` (secretos solo en entorno, esquema solo Alembic, sin create_all, snake_case/type hints) y de "Leer antes" de `CHANGES.md` para C-01 — verificar: checklist revisado sin hallazgos; el change queda listo para `/opsx:archive`
