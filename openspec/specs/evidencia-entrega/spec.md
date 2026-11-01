# evidencia-entrega Specification

## Purpose
Define los criterios de aceptación y comportamientos verificables de la entrega C-11: esquema consolidado en dos migraciones, suite HTTP de los casos C-01…C-19, evidencias C-14/C-15/C-16 y checklist final de calidad.

## Requirements

### Requirement: Esquema del entregable en dos migraciones
El entregable SHALL conservar exactamente dos migraciones en `migrations/versions/`: `001_esquema_inicial` (autogenerada con todos los modelos) y `002_disparador_solo_agregado` (escrita a mano, conserva los disparadores de C-09).

#### Scenario: Solo dos archivos de migración
- **WHEN** se lista `migrations/versions/`
- **THEN** contiene exactamente `001_esquema_inicial.py` y `002_disparador_solo_agregado.py`

### Requirement: Alembic check sin diferencias
Tras `alembic upgrade head`, `alembic check` SHALL reportar que no hay operaciones de upgrade pendientes, es decir, los modelos coinciden con el esquema.

#### Scenario: check limpio en head
- **WHEN** se ejecuta `alembic upgrade head` y luego `alembic check`
- **THEN** la salida indica "No new upgrade operations detected"

### Requirement: Upgrade y downgrade reproducibles
`alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head` SHALL completar sin errores y dejar la base en la revisión head.

#### Scenario: ciclo upgrade/downgrade/upgrade
- **WHEN** se aplica `alembic downgrade base` y luego `alembic upgrade head` sobre el esquema consolidado
- **THEN** ambas operaciones terminan sin error y la revisión actual es head

### Requirement: Seed sobre esquema consolidado
`python seed.py` sobre una base migrada con `alembic upgrade head` SHALL dejar el estado inicial conocido de forma idempotente.

#### Scenario: seed deja estado inicial
- **WHEN** se ejecuta `python seed.py` tras `alembic upgrade head`
- **THEN** el catálogo tiene 4 estados, hay 7 usuarios con roles vigentes, 2 clientes, 3 vehículos, 4 repuestos con stock, 2 órdenes y 1 evento de seguridad de `SISTEMA`

#### Scenario: seed es idempotente
- **WHEN** se ejecuta `python seed.py` dos veces seguidas sobre la misma base
- **THEN** los conteos de usuarios, clientes, vehículos, repuestos y órdenes son idénticos

### Requirement: Solo agregado en tablas de historial
`test/solo_agregado.sql` SHALL rechazar UPDATE y DELETE en `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto` (6 rechazos), rechazar una orden con estado fuera del catálogo por la FK (1 rechazo), y permitir INSERT en las tres tablas.

#### Scenario: rechazos de solo agregado en psql
- **WHEN** se ejecuta `test/solo_agregado.sql` con `psql \i` sobre la base sembrada
- **THEN** se observan los 7 errores esperados (6 del disparador + 1 de FK) y ninguna fila de historial se modifica ni borra

### Requirement: Suite HTTP de casos de consigna
`test/*.http` SHALL cubrir los casos ejercicio C-01…C-19 de la consigna, cada uno con su respuesta esperada documentada.

#### Scenario: cada caso tiene respuesta esperada
- **WHEN** se revisa cada archivo `.http` de la suite
- **THEN** cada caso C-01…C-19 indica el código de estado y el cuerpo esperados

### Requirement: Login solo por cookie HttpOnly; Bearer sin cookie → 401
`POST /auth/login` SHALL emitir el JWT únicamente en `Set-Cookie` (HttpOnly/SameSite=Lax), nunca en el cuerpo, y una petición autenticada con `Authorization: Bearer` sin cookie válida SHALL responder 401.

#### Scenario: login emite Set-Cookie y no trae token en el cuerpo
- **WHEN** se inicia sesión con `# @no-cookie-jar` y se captura el `Set-Cookie`
- **THEN** el cuerpo de la respuesta no contiene el JWT y la cookie viaja con HttpOnly

#### Scenario: Bearer sin cookie es rechazado
- **WHEN** se consulta una ruta protegida con `Authorization: Bearer` y sin cookie de sesión
- **THEN** la respuesta es 401

### Requirement: C-15 detalle de orden sin N+1
El detalle de una orden SHALL devolverse con la misma cantidad y tipo de consultas SQL tenga 2 o 4 ítems, verificable con SQL_ECHO en dev.

#### Scenario: 2 y 4 ítems generan mismas consultas
- **WHEN** se consulta `GET /ordenes/{id}` para una orden con 2 ítems y otra con 4 ítems, con SQL_ECHO activado
- **THEN** ambas trazas ejecutan el mismo número y tipo de consultas (sin N+1)

### Requirement: C-16 búsqueda q segura ante inyección
`GET /repuestos?q=` con un intento de inyección SQL SHALL responder lista vacía, total 0, y nunca 500 (RN-18).

#### Scenario: q con inyección no falla ni expone la base
- **WHEN** se consulta `GET /repuestos?q='; DROP TABLE repuestos--` o similar
- **THEN** la respuesta es 200 con `items` vacío y `total` 0, sin error 500 ni texto de PostgreSQL

### Requirement: Checklist final de calidad
Ninguna entrada inválida SHALL terminar en 500, ningún error SHALL exponer `password_hash`, texto interno de PostgreSQL ni trazas al cliente (RN-18), y el login con Bearer sin cookie SHALL ser 401 (DD-04).

#### Scenario: errores no exponen la base ni terminan en 500
- **WHEN** se envían entradas inválidas a los endpoints de la API
- **THEN** ninguna respuesta es 500 y ninguna expone `password_hash`, SQL interno ni trazas
