# Proposal

## Why

El proyecto no tiene aún ninguna base ejecutable: no hay estructura de directorios, configuración, ciclo de vida ni salud del servicio. Sin estos cimientos ningún change posterior (modelos, auth, órdenes) puede arrancar ni probarse, y la consigna evalúa desde el primer ejercicio la estructura obligatoria, el Settings sin secretos por defecto y el lifespan (8 % de la nota).

## What Changes

- Estructura de directorios obligatoria: `main.py`, `seed.py`, `alembic.ini`, `requirements.txt`, `env.example`, `app/core/`, `app/modules/{health,usuarios,clientes,repuestos,ordenes}/`, `migrations/`, `test/`.
- `requirements.txt` con el stack congelado: fastapi[standard], SQLModel ≥0.0.24, SQLAlchemy 2 asincrónico, **asyncpg** (P-01 resuelta), alembic, pydantic-settings, bcrypt, PyJWT.
- `app/core/config.py`: `Settings` con pydantic-settings — `POSTGRES_*`, `SECRET_KEY` y `POSTGRES_PASSWORD` **sin valor por defecto** (si faltan, la app no arranca), `BCRYPT_COST`, `TOKEN_EXPIRE_SEGUNDOS=1800`, `COOKIE_SECURE`, `SQL_ECHO`, y `@computed_field` que arma la URL `postgresql+asyncpg://`.
- `app/core/database.py`: motor y fábrica de sesiones creados en el **lifespan** y guardados en `app.state` (nunca al importar); sesión por petición con `expire_on_commit=False`; `dispose()` al apagar.
- `main.py`: aplicación + lifespan + los **dos grupos de rutas** (abierto / protegido) con el montaje correcto (DD-10).
- Módulo `health` (solo `router.py`): `GET /health/live` (200 sin tocar la base) y `GET /health/ready` (`SELECT 1` → 200 o 503).
- Alembic inicializado con la plantilla **asincrónica** (`env.py` adaptado con `run_sync`); `env.example` con todas las variables y ningún secreto.
- Esqueletos de `seed.py` y de los módulos `usuarios`, `clientes`, `repuestos`, `ordenes` (contenido en changes posteriores).

## Capabilities

### New Capabilities

- `service-health`: respuestas de liveness y readiness del proceso (sin DB / con `SELECT 1`), incluida la semántica 200 vs 503.
- `service-configuration`: requisitos de arranque de la configuración — variables sensibles sin defaults, URL asincrónica armada por computación, fallo temprano si falta un secreto.
- `service-lifespan`: ciclo de vida de recursos — motor/fábrica creados en el lifespan, sesión por petición sin expire post-commit, cierre con `dispose()` al apagar.

### Modified Capabilities

(ninguna — el proyecto no tiene specs previas; `openspec list --specs` vacío)

## Impact

- **Archivos nuevos**: `main.py`, `seed.py`, `alembic.ini`, `requirements.txt`, `env.example`, `app/core/{config,database}.py`, `app/modules/health/router.py`, esqueletos de los 4 módulos de dominio, `migrations/` (alembic asincrónico), `test/`.
- **API**: expone `GET /health/live` y `GET /health/ready`; aún sin endpoints de dominio.
- **Dependencias**: se fija el set de `requirements.txt` (asyncpg como driver — P-01).
- **Sistemas**: requiere PostgreSQL 16 accesible para readiness; sin cambios en DB (sin tablas todavía).
- **Bloquea**: C-02 (modelos/UoW) depende de esta base.
