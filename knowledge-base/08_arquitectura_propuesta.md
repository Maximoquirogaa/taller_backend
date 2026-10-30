# Arquitectura Propuesta

## Patrones aplicados

| Patrón | Dónde | Por qué |
|--------|-------|---------|
| Arquitectura en capas (Router/Service/UoW/Repository/Model) | todos los módulos | Cada capa sabe lo suyo y nada más; criterio de evaluación central |
| Unit of Work | `app/core/unit_of_work.py` + UoW por módulo | Una operación de negocio = una transacción (RN-02, RN-13, RN-20) |
| Repository genérico | `BaseRepository[T]`, `SoftDeleteRepository[T]` | Reutilización; `flush()` nunca `commit()`; precarga en el método que la necesita |
| Soft delete + índice único parcial | `vehiculo`, `repuesto`, `asignacion_rol` | Unicidad solo entre vigentes (RN-01, RN-16, C-19) |
| Catálogo (tabla de referencia) | `estado_orden` | FK en vez de CHECK; datos propios (`es_final`); seed aparte de la migración |
| Append-only + disparador | 3 tablas de historial/movimientos | Garantía impuesta por la base, no por la app (RN-15) |
| Contratos separados de modelos | `schemas.py` | `extra="forbid"`, sin `password_hash` en respuestas, PATCH parcial |
| Hash ficticio + transacción propia del intento | `security.py`, módulo usuarios | RN-09 (timing) y RN-08 (el fallo sobrevive al rollback) |
| Dos grupos de rutas | `main.py` | Cambio obligatorio de contraseña con control montado una vez (FastAPI suma dependencias, no las resta) |
| Lifespan para recursos | motor, fábrica de sesiones, hash ficticio | Nada construido al importar (antes del bucle de eventos) |

## Estructura de directorios (obligatoria)

```
TP_taller/
├── main.py                  # app, lifespan, los dos grupos de rutas
├── seed.py                  # deja la base en el estado inicial conocido
├── alembic.ini
├── requirements.txt
├── env.example              # todas las variables, ningún secreto
├── app/
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── database.py      # motor + fábrica + get_session
│   │   ├── security.py      # bcrypt + JWT
│   │   ├── dependencies.py  # usuario actual, roles vigentes, cambio obligatorio, requiere_rol
│   │   ├── repository.py    # BaseRepository / SoftDeleteRepository
│   │   ├── paginacion.py    # envoltorio {items,total,page,size,pages}
│   │   └── unit_of_work.py  # UoW base (async context manager)
│   └── modules/
│       ├── health/          # solo router.py
│       ├── usuarios/        # + AsignacionRol, IntentoAcceso, EventoSeguridad
│       ├── clientes/        # + Vehiculo
│       ├── repuestos/       # + MovimientoStock, HistorialPrecio
│       └── ordenes/         # + EstadoOrden, ItemOrden, HistorialEstadoOrden
│           # en cada módulo: models.py, schemas.py, repository.py,
│           #                 unit_of_work.py, service.py, router.py
├── migrations/              # Alembic (plantilla asincrónica)
│   # 1) autogenerate: todas las tablas
│   # 2) a mano: disparador de sólo agregado (comentario que lo diga)
├── test/
│   ├── *.http               # casos C-01…C-19 (con respuesta esperada)
│   └── solo_agregado.sql    # C-14
└── knowledge-base/          # esta KB
```

## Seguridad

- **Autenticación**: bcrypt (costo en Settings, no fijo en código) siempre fuera del bucle (`to_thread` + semáforo); hash **antes** de abrir la transacción; campos bcrypt máx. 72 **bytes**. JWT firmado con `SECRET_KEY` (sin default) en cookie HttpOnly + SameSite=Lax (+ Secure configurable). El cuerpo del login nunca trae el token; la dependencia lo lee de `request.cookies`. `Authorization: Bearer` → 401.
- **Autorización**: `requiere_rol` consulta `asignacion_rol` vigente en cada petición (RN-04). 401 = sin sesión/token inválido/vencido/usuario inactivo/token anterior al cambio; 403 = sin permiso o cambio pendiente. Cancelación y rutas `/mis-*` deciden en el servicio.
- **Validación de input**: contratos con `extra="forbid"`; paginación acotada; parámetros ligados en SQL; ningún error expone texto de la base (RN-18); ninguna entrada inválida → 500.
- **Secrets**: `SECRET_KEY` y credenciales de la base **solo** en entorno; sin valor por defecto (si faltan, la app no arranca). `.env` no se versiona; `env.example` sin secretos.

## Variables de entorno

| Variable | Descripción | Ejemplo | Sensible |
|----------|-------------|---------|----------|
| POSTGRES_USER | usuario de la base | `taller` | N |
| POSTGRES_PASSWORD | contraseña de la base | (sin default) | **Y** |
| POSTGRES_DB | nombre de la base | `taller` | N |
| POSTGRES_HOST | host | `localhost` | N |
| POSTGRES_PORT | puerto | `5432` | N |
| SECRET_KEY | clave de firma JWT | (sin default) | **Y** |
| BCRYPT_COST | costo bcrypt | `12` | N |
| TOKEN_EXPIRE_SEGUNDOS | duración del token | `1800` | N |
| COOKIE_SECURE | marcar cookie Secure | `false` en dev | N |
| SQL_ECHO | log de consultas | `true` en dev | N |

La dirección de la base se arma con un `@computed_field` (`postgresql+asyncpg://...`). El pool declara su tamaño en Settings.
