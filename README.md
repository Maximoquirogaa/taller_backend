# TP Taller Mecánico — API asincrónica (entrega C-11)

**Grupo:** Barone, Quiroga, Rios, Simón  
**Integrantes:** Barone, Quiroga, Rios, Simón  
**Unidades:** 1 a 6 — Comisiones 3 y 4

API REST asincrónica para la gestión diaria de un taller mecánico: órdenes de trabajo, stock de repuestos, clientes y vehículos, con acceso por roles. Stack: Python 3.12+, FastAPI, SQLModel, SQLAlchemy 2 async (asyncpg), PostgreSQL 16, Alembic, bcrypt + PyJWT (cookie HttpOnly).

> Proyecto solo backend (sin frontend). La entrega consolida el esquema en **exactamente dos migraciones**, añade la suite HTTP de los casos C-01…C-19, las evidencias C-14/C-15/C-16 y este README.

---

## 1. Requisitos previos

- Python 3.12+
- PostgreSQL 16 (servidor levantado y accesible)
- `psql` (para la evidencia C-14)

## 2. Instalación

```powershell
# 1. Entorno virtual (recomendado)
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Dependencias
pip install -r requirements.txt

# 3. Variables de entorno
# Copiar la plantilla (sin secretos) y completar los valores:
copy env.example .env
#   - POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB / POSTGRES_HOST / POSTGRES_PORT
#   - SECRET_KEY: generar con  python -c "import secrets; print(secrets.token_urlsafe(64))"
#   - BCRYPT_COST=12, TOKEN_EXPIRE_SEGUNDOS=1800, COOKIE_SECURE=false (dev)
#   - SQL_ECHO=false (poner true en dev para ver las consultas, necesario en C-15)
# ⚠️  SECRET_KEY y POSTGRES_PASSWORD no tienen valor por defecto: si faltan, la app no arranca.
# .env no se versiona (ya incluido en .gitignore).
```

## 3. Base de datos y esquema (solo Alembic)

El esquema se crea y versióna únicamente con Alembic (nunca `create_all` ni `ALTER` suelto). El entregable tiene exactamente dos migraciones:

- `migrations/versions/001_esquema_inicial.py` — autogenerada (13 tablas, CHECK, índices parciales, FKs, `timestamptz`, `NUMERIC`)
- `migrations/versions/002_disparador_solo_agregado.py` — escrita a mano, garantía de sólo agregado (RN-15)

```powershell
# 4. Crear la base (una sola vez)
#   createdb taller   (o usar el POSTGRES_DB de .env)

# 5. Aplicar migraciones hasta head
alembic upgrade head

# 6. Verificar que el esquema coincide con los modelos (no hay operaciones pendientes)
alembic check   # debe reportar: "No new upgrade operations detected"

# 7. (Opcional) Probar ciclo completo desde cero
alembic downgrade base
alembic upgrade head
```

## 4. Datos iniciales (seed)

```powershell
python seed.py
```

Deja la base en un estado conocido y reproducible (idempotente: re-ejecutar deja el mismo estado). Resumen de conteos:

| Tabla | Conteo |
|---|---|
| `estado_orden` | 4 (PENDIENTE, EN_REPARACION, TERMINADA, CANCELADA) |
| `usuario` | 7 |
| `asignacion_rol` | 7 |
| `cliente` | 2 |
| `vehiculo` | 3 |
| `repuesto` | 4 (con stock) |
| `movimiento_stock` | 4 (alta inicial de cada repuesto) |
| `orden_trabajo` | 2 |
| `item_orden` | 2 |
| `historial_estado_orden` | 3 |
| `historial_precio_repuesto` | 1 (filtro 8000 → 8500) |
| `evento_seguridad` | 1 (actor `SISTEMA`) |
| `intento_acceso` | 0 |

## 5. Arrancar el servidor

```powershell
uvicorn main:app --port 8000
```

La API queda disponible en `http://localhost:8000`.
- `GET /health/live` — 200 sin tocar la base
- `GET /health/ready` — 200 si PostgreSQL responde, 503 si no

OpenAPI: `http://localhost:8000/openapi.json` (seguridad declarada como cookie `access_token` HttpOnly, sin esquema Bearer).

## 6. Ejecutar las pruebas

```powershell
pytest -q
```

La suite crea y migra una base aparte `taller_test` (solo Alembic) y salta si PostgreSQL no responde. Debe terminar en verde sin regresiones.

Evidencia SQL (C-14, en psql sobre la base sembrada):

```powershell
psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB -f test/solo_agregado.sql
```

Espera exactamente 7 rechazos: 6 del disparador de sólo agregado (UPDATE/DELETE × 3 tablas) + 1 de clave foránea (orden con estado fuera del catálogo). Ninguna fila de historial se modifica ni borra.

## 7. Suite HTTP de la consigna (C-01…C-19)

Los archivos `test/c-01-a-c-08-salud-auth.http`, `test/c-09-a-c-14-usuarios-clientes.http` y `test/c-15-a-c-19-repuestos-ordenes.http` contienen los 19 casos de la consigna, cada uno con su respuesta esperada (código de estado y cuerpo). Se abren con el REST Client de VS Code (o similar); cada bloque `###` se envía por separado.

Flujo de sesión (DD-04): el login se ejecuta con `# @no-cookie-jar` y se captura la cabecera `Set-Cookie`; el JWT viaja **solo** en la cookie `access_token` (HttpOnly, SameSite=Lax, Max-Age), nunca en el cuerpo. `Authorization: Bearer` sin cookie responde 401.

Precondición para cada caso: servidor levantado en el puerto 8000 y base sembrada (`alembic upgrade head` + `python seed.py`).

## 8. Credenciales ficticias (deja `seed.py`)

Todas las cuentas usan la misma contraseña de demostración: **`Taller2026`**

| Email | Rol | Nota |
|---|---|---|
| admin@example.com | ADMIN | |
| admin2@example.com | ADMIN | |
| recepcion@example.com | RECEPCION | |
| mecanico@example.com | MECANICO | |
| mecanico2@example.com | MECANICO | |
| cliente@example.com | CLIENTE | ficha de Laura Gómez (2 vehículos) |
| nuevo@example.com | MECANICO | **cambio de contraseña obligatorio** (solo `/auth` y salud hasta cambiarla) |

⚠️ Contraseñas de demostración solo en `seed.py`, nunca como secretos reales en el repositorio.

## 9. Reglas duras del proyecto (contrato)

- Esquema solo Alembic: exactamente dos migraciones, nunca `create_all` ni `ALTER` suelto.
- UoW manda las transacciones: nunca `commit()` en repositorios; el servicio abre el UoW con `async with`.
- bcrypt asincrónico fuera del bucle de eventos (`to_thread` + semáforo); hash antes de abrir el UoW.
- Token solo en cookie HttpOnly; nunca JWT en el cuerpo ni `Authorization: Bearer`.
- Stock solo con `movimiento_stock` (nunca UPDATE directo de stock).
- Tablas append-only: `historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto` solo `INSERT`.
- Errores sin filtrar la base: nunca se expone `password_hash`, texto interno de PostgreSQL ni trazas; `IntegrityError` → 409; ninguna entrada inválida termina en 500.
- Roles en la base: se consulta `asignacion_rol` vigente en cada petición; se distingue 401 de 403.
- Sin lazy loading: las relaciones se precargan en el repositorio (detalle de orden con consultas fijas, sin N+1 — caso C-15).
- Secretos solo en entorno: sin defaults para `SECRET_KEY` ni `POSTGRES_PASSWORD`.
- Contratos estrictos: schemas `extra="forbid"`, `snake_case`, type hints.

## 10. Evidencias de entrega

- **C-14**: salida de `psql -f test/solo_agregado.sql` (7 rechazos) — capturar en `docs/evidencias/C-14.png` o `.txt`.
- **C-15**: detalle de orden con 2 y 4 ítems emite el mismo número de consultas SQL (`SQL_ECHO=true`) — capturar en `docs/evidencias/C-15.png` o `.txt`.

Pasos de levantamiento completos: venv → deps → `.env` → `alembic upgrade head` → `python seed.py` → servidor (`uvicorn main:app --port 8000`) → pruebas.
