# Design

## Context

Proyecto greenfield: no existe código todavía. Ver `proposal.md` — Why. La consigna (Ejercicio 1, 8 % de la nota) y la KB fijan restricciones que condicionan el diseño: estructura de directorios obligatoria, recursos de runtime en el lifespan y no al importar (DD-09, EA-08), dos grupos de rutas porque FastAPI suma dependencias y no las resta (DD-10), secretos sin defaults (RNF "Credenciales") y driver asincrónico asyncpg (P-01 resuelta). `knowledge-base/08_arquitectura_propuesta.md` es la referencia de estructura y env vars.

## Goals / Non-Goals

**Goals:**
- Servidor arranca con `uvicorn main:app`, pasa `/health/live` y `/health/ready` (con PG arriba).
- Settings fail-fast: sin `SECRET_KEY` o `POSTGRES_PASSWORD` no arranca; `env.example` completo sin secretos.
- Base de recursos compartida lista para C-02: motor + fábrica en `app.state`, `get_session` por petición.
- Esqueleto de módulos y Alembic asincrónico listos para que C-02 solo agregue modelos y la migración 001.

**Non-Goals:**
- Modelos de tablas, migraciones con contenido y `seed.py` real (C-02 / C-10).
- Endpoints de dominio, auth, UoW/repositorios (C-02 en adelante).
- Tests automatizados del dominio (los `.http` de salud sí se usan para verificación manual).
- README de entrega y evidencias (C-11).

## Decisions

### D1 — Lifespan como único dueño de recursos
Motor y fábrica se crean dentro de un `@asynccontextmanager` en `lifespan(app)` y se guardan en `app.state`; al salir, `await engine.dispose()`.
- **Alternativas**: engine a nivel de módulo (rechazada: se construye antes del bucle de eventos — EA-08; síntoma engañoso entre server y tests) y los deprecados `@app.on_event` (rechazada: FastAPI los marca obsoletos frente a lifespan).
- `get_session` toma la fábrica de `app.state` (no de un módulo), entrega una sesión con `expire_on_commit=False` y la cierra en `finally`.

### D2 — Settings con pydantic-settings y campos requeridos
`Settings(BaseSettings)` con `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`. `secret_key: str` y `postgres_password: str` **sin default** → Pydantic falla en la instanciación y la app no arranca (el `lifespan` ni siquiera se abre). La URL se expone como `@computed_field` que arma `postgresql+asyncpg://...` con `quote()` de `urllib.parse` para passwordes con caracteres especiales.
- **Alternativas**: `os.environ.get(...)` manual (rechazada: sin validación ni errores temprano) y defaults falsos tipo `dev-secret` (rechazados explícitamente por la consigna).
- `SQL_ECHO` default `false`; se prende en `.env` local (diagnóstico, no es comportamiento por defecto).

### D3 — Driver asyncpg congelado
`requirements.txt` fija `asyncpg` y la URL usa `postgresql+asyncpg://` (P-01 resuelta; psycopg 3 descartado). SQLAlchemy se instala con el extra `[asyncio]`.

### D4 — Dos grupos de rutas desde el día uno
En `main.py`: `router_abierto = APIRouter()` (salud + futuro `/auth`) y `router_protegido = APIRouter()` (futuro dominio, con el control de cambio obligatorio montado **una sola vez** cuando llegue C-03). En C-01 el grupo protegido se crea y monta **vacío** — el patrón queda probado y C-03 solo agrega endpoints.
- **Alternativa**: montar todo junto y agregar controles por endpoint (rechazada: D10/consigna — FastAPI suma dependencias, no las resta).

### D5 — health solo con router.py, sin capas
`app/modules/health/router.py` no tiene models/schemas/service (la consigna lo fija). `/health/ready` ejecuta `SELECT 1` con una sesión de `app.state` directamente — no hay UoW/repositorio todavía (llegan en C-02); introducirlos acá adelantaría scope.

### D6 — Alembic asincrónico sin migraciones aún
`alembic init migrations` + adaptación del template async (`async_engine_from_config` + `connection.run_sync(...)`). Sin versiones todavía: `alembic upgrade head` sobre base vacía es no-op y funciona; la migración 001 (autogenerate de tablas) la produce C-02. `alembic.ini` no contiene credenciales (leen del entorno).

### D7 — Esqueleto de módulos con `__init__.py`
Se crean `app/modules/{usuarios,clientes,repuestos,ordenes}/` con los 6 archivos vacíos (o con docstring de intención) + `__init__.py` en cada paquete, y `test/` con placeholder. `seed.py` arranca como stub con la cabecera y el comentario de "parte de la puesta en marcha" (contenido real en C-10).

## Risks / Trade-offs

- **[Pool creado antes del bucle]** → síntoma clásico "anda al levantar y falla en tests" → mitigación: creación exclusiva en lifespan + verificación importando los módulos sin loop (task de verificación).
- **[`/health/ready` da 503 sin base creada]** → esperado por diseño; en verificación local crear la DB primero o aceptar 503 como camino negativo.
- **[Campos de auth declarados pero sin uso hasta C-03]** (`BCRYPT_COST`, `TOKEN_EXPIRE_SEGUNDOS`, `COOKIE_SECURE`) → sin código muerto problemático: son Settings; se documentan en `env.example`.
- **[`.env` obligatorio para arrancar]** → el developer nuevo choca en el primer arranque → mitigación: `env.example` completo + instrucciones en README (C-11) y en comentarios del ejemplo.

## Migration Plan

Greenfield: no hay despliegue previo que migrar. Rollback = eliminar los archivos del change. No aplica secuencia de deploy; la verificación es `uvicorn main:app` + requests a `/health/*`.

## Open Questions

- El comando y puerto definitivos para el README de entrega (SU-04 asume 8000) se confirman en C-11 — no afecta specs ni tareas de este change.
