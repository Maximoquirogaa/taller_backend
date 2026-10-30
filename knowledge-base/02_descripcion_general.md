# Descripción General

## Stack tecnológico

| Capa | Tecnología | Versión mínima |
|------|-----------|----------------|
| Lenguaje | Python | 3.12 |
| Framework web | FastAPI (handlers con `async def`) | 0.111 |
| Modelos de tabla | SQLModel | 0.0.24 |
| ORM / motor | SQLAlchemy asincrónico | 2.0 |
| Driver PG | asyncpg (o psycopg 3 asincrónico) | 0.30 |
| Base de datos | PostgreSQL | 16 |
| Migraciones | Alembic (plantilla asincrónica) | 1.13 |
| Configuración | pydantic-settings (entorno o `.env`) | 2.0 |
| Password hash | bcrypt (costo configurable) | 4.0 |
| Token | PyJWT (JWT firmado) | 2.8 |
| Servidor ASGI | uvicorn (vía `fastapi[standard]`) | el que instale |

## Arquitectura general

API en capas, organizada por módulo funcional; las mismas seis capas en todos los módulos:

```
HTTP → router.py → service.py → unit_of_work.py → repository.py → models.py (SQLModel)
                         ↑
              core/dependencies.py (usuario actual, roles vigentes, requiere_rol)
              core/security.py (bcrypt + JWT)
              core/database.py (motor + sesión; lifespan)
```

- **Router**: construye el Unit of Work con una dependencia, lo pasa al servicio sin abrirlo; traduce errores a códigos HTTP.
- **Service**: recibe el UoW, lo abre con `async with`, contiene las reglas de negocio; nunca construye el UoW.
- **UnitOfWork**: gestor de contexto asincrónico; confirma al salir, revierte con excepción; no cierra la sesión (no la creó).
- **Repository**: `BaseRepository[T]` y `SoftDeleteRepository[T]`; `add`/`update` hacen `flush()`, nunca `commit()`; la precarga se declara en el método que la necesita (sin N+1, sin lazy loading).
- **Modelos**: SQLModel con restricciones (CHECK, UNIQUE, índices únicos parciales, FKs); esquema solo con Alembic (nunca `create_all`).
- Motor y fábrica de sesiones se crean en el **lifespan** y viven en `app.state` (no al importar módulos).

## Integraciones externas

| Servicio | Propósito | Tipo |
|----------|-----------|------|
| PostgreSQL 16 | Persistencia relacional | driver asincrónico (asyncpg/psycopg) |
| (ninguna otra) | — | — |

No hay APIs de terceros, colas ni storage. El "aviso al cliente" es simulado con `BackgroundTasks` + `asyncio.sleep(0.5)` + log.

## API REST (resumen por recurso)

Dos grupos montados en `main.py`: **abierto** (salud + auth) y **protegido** (todo el dominio; monta el control de cambio obligatorio de contraseña una sola vez).

| Grupo | Recursos | Endpoints principales |
|-------|----------|----------------------|
| Abierto | Salud | `GET /health/live`, `GET /health/ready` |
| Abierto | Auth | `POST /auth/registro`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/yo`, `POST /auth/cambiar-password` |
| Protegido | Usuarios/roles | `POST /usuarios`, `GET/POST /usuarios/{id}/roles`, `DELETE /usuarios/{id}/roles/{rol}`, `GET /eventos` |
| Protegido | Clientes/vehículos | `POST /clientes`, `GET /clientes/{id}`, `POST /clientes/{id}/vehiculos`, `DELETE /vehiculos/{id}`, `GET /mis-vehiculos` |
| Protegido | Repuestos | CRUD `/repuestos`, `POST /repuestos/{id}/reponer`, `GET .../movimientos`, `GET .../precios` |
| Protegido | Órdenes | `POST/GET /ordenes`, `GET /ordenes/{id}`, `POST .../iniciar|terminar|cancelar`, `GET /estados-orden`, `GET /mis-ordenes` |

Convenciones: 201 crear, 204 baja, 200 ok, 404 inexistente en la ruta, 409 choque con lo guardado, 422 contrato inválido, 401 sin sesión/válido, 403 sin permiso, 429 límite de intentos. Listados con envoltorio `{items, total, page, size, pages}` (page desde 1; size 1–100, default 20; página fuera de rango → 422). Dinero como string decimal en respuestas (`"68000.00"`). El login responde mensaje + `debe_cambiar_password` + `expira_en_segundos`; el token viaja solo en `Set-Cookie`.
