# Design

## Context

Ver `proposal.md` §Why. Lo relevante para el diseño:

- El esquema ya está completo (13 tablas, migraciones 001 → 005 y la 006 de C-09); C-10 **no** agrega migraciones.
- `estado_orden` nace vacío por DD-01, así que el seed es el único lugar que puebla el catálogo.
- `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto` tienen disparadores de sólo agregado (C-09): el seed sólo puede hacer `INSERT` allí.
- `app/core/database.py` ya expone `crear_motor` y `crear_fabrica_sesiones`; `app/core/security.py` expone `hash_password` (bcrypt en `to_thread` con semáforo) y `validar_password`.
- La suite limpia con `TRUNCATE ... RESTART IDENTITY CASCADE` sobre las 13 tablas (lista en `test/conftest.py`), patrón que el seed puede reutilizar.
- `seed.py` es hoy un stub que aborta.

## Goals / Non-Goals

**Goals:**

- Un `python seed.py` reproducible que deje el estado inicial completo y coherente.
- Idempotencia real: ejecutar dos veces deja lo mismo.
- Datos que permitan demostrar, sin preparación extra, el caso de stock insuficiente (C-08/C-11), el disparador de sólo agregado (C-14) y el detalle de orden con distinto número de ítems (C-15).
- Lógica de carga invocable desde tests sin pasar por `Settings` ni por `sys.argv`.

**Non-Goals:**

- No se cargan `intento_acceso` (la tabla debe quedar vacía: es auditoría de logins reales).
- No se generan datos aleatorios ni volúmenes grandes: el seed es un estado mínimo y determinista.
- No se agrega confirmación interactiva ni bandera `--force`: el script es para automatización (C-11 lo corre en la secuencia de entrega).
- No se toca la API, los servicios ni los repositorios.

## Decisions

### D1 — Lógica separada del entrypoint: `cargar_datos_iniciales()` + `main()`

`seed.py` expone:

```python
async def cargar_datos_iniciales(fabrica: async_sessionmaker[AsyncSession]) -> None: ...
def main() -> None: ...  # carga Settings, crea motor/fábrica, asyncio.run, imprime resumen
```

`main()` reutiliza `cargar_settings`, `crear_motor` y `crear_fabrica_sesiones` de `app/core` (una sola forma de configurar la base), y usa `asyncio.run`. Los tests llaman a `cargar_datos_iniciales(fabrica_pruebas)` directamente, sin leer `.env` ni abrir un segundo motor.

- **Alternativa descartada**: lógica en `main()` con `asyncpg` crudo. Duplicaría la configuración de conexión y perdería el tipado de los modelos.

### D2 — Una sola transacción para toda la carga

Todo va dentro de `async with fabrica() as sesion, sesion.begin():` — `TRUNCATE` + los `INSERT` en orden de dependencias. Si algo falla, no queda una carga parcial; PostgreSQL hace `TRUNCATE` transaccional.

- **Alternativa descartada**: commit por bloque (catálogo, usuarios, …). Un fallo a mitad dejaría una base inconsistente y rompería la promesa de idempotencia.

### D3 — Idempotencia por `TRUNCATE ... RESTART IDENTITY CASCADE`

Antes de insertar se vacían las 13 tablas con la misma sentencia que usa `test/conftest.py`. El resultado es siempre el mismo estado, con ids predecibles (`admin` = 1, etc.), y no hace falta lógica de upsert.

- **Por qué no `DELETE` + upsert**: `DELETE` está bloqueado por los disparadores de C-09 en las tres tablas de historial, y los `ON CONFLICT` por tabla serían mucho más código y más frágil ante cambios de esquema.
- **Trade-off aceptado**: el seed borra datos de trabajo. Es intencional y el docstring lo advierte.

### D4 — Una contraseña ficticia compartida, hasheada una sola vez

`CONTRASENA_FICTICIA = "Taller2026"` (11 caracteres, con dígito, sin espacios → cumple `validar_password`). Se hashea **una vez** con `hash_password` (bcrypt en `to_thread`) y ese hash se asigna a los 7 usuarios.

- **Por qué una sola**: el seed es de demostración; una contraseña documentada es más fácil de usar en la corrección y evita 7 hashes de costo 12 en cada carga.
- **Por qué `hash_password` y no bcrypt directo**: respeta la regla dura de no ejecutar bcrypt en el bucle de eventos y usa el costo configurado (`BCRYPT_COST`).
- **Alternativa descartada**: contraseñas distintas por usuario → más superficie de error y ninguna ventaja.

### D5 — Datos fijos declarados como constantes del módulo

Tablas de constantes para usuarios, clientes/vehículos, repuestos y órdenes, de modo que el estado inicial se lea de un vistazo y los tests puedan importar los mismos valores (emails, patentes, códigos) en vez de duplicarlos.

| Usuario | Rol(es) | `debe_cambiar_password` |
|---|---|---|
| `admin@example.com` | ADMIN | no |
| `admin2@example.com` | ADMIN | no |
| `recepcion@example.com` | RECEPCION | no |
| `mecanico@example.com` | MECANICO | no |
| `mecanico2@example.com` | MECANICO | no |
| `cliente@example.com` | CLIENTE | no |
| `nuevo@example.com` | MECANICO | **sí** |

- **Clientes**: Laura (`cliente@`, 2 vehículos) y Jorge (sin usuario, 1 vehículo).
- **Repuestos**: filtro de aceite (precio 8500, stock 10), pastillas de freno (12000, 4), bujía (3500, 2), aceite por litro (2500, 20).
- **Órdenes**: orden PENDIENTE con 1 filtro (total 8500); orden EN_REPARACION con 4 bujías (total 14000), asignada a `mecanico@`.
- **Historial de precios**: filtro 8000 → 8500, `usuario_id` = `admin@`.

`otorgada_por` de cada `asignacion_rol` apunta al `admin@` cargado.

### D6 — Historiales escritos a mano, coherentes con cada transición

Por cada orden se inserta su línea inicial «nulo → PENDIENTE»; la orden EN_REPARACION suma «PENDIENTE → EN_REPARACION» con el `usuario_id` de `mecanico@`. El seed escribe esas filas directamente porque no pasa por los servicios (que exigirían sesión HTTP y UoW).

- **Por qué importa**: si el historial no refleja la transición, el estado inicial sería incoherente y C-15 (detalle de orden) mostraría datos raros.
- **Restricción**: sólo `INSERT`; los disparadores de C-09 rechazan cualquier otra cosa y el seed no debe desactivarlos.

### D7 — Orden EN_REPARACION como caso de stock insuficiente

El ítem pide 4 bujías y el stock es 2. Así, sin preparar nada, `POST /ordenes/{id}/terminar` responde 409 y la evidencia de la reversión completa (C-08, consigna C-11) se puede capturar sobre el estado recién sembrado.

- **Verificación en tests**: el test compara `item.cantidad > repuesto.stock` directamente, sin ejecutar la API.
- **No se descuenta stock al sembrar**: la orden sigue EN_REPARACION; el stock refleja sólo el alta inicial (movimientos).

### D8 — Timestamps deterministas dentro de una ejecución

Un único `ahora = datetime.now(timezone.utc)` para todas las filas de la carga (`creada_en`, `cuando`, `desde`). Entre ejecuciones cambia el instante, pero la forma del estado es idéntica; los tests no comparan fechas absolutas.

### D9 — Tests contra `taller_test` reutilizando la fábrica de la suite

`test/test_seed.py` pide el fixture `fabrica_pruebas` (o `motor_pruebas`) del `conftest.py` raíz y llama `cargar_datos_iniciales` dos veces. Verifica: catálogo y `es_final`; conteo de usuarios/roles/clientes/vehículos/repuestos/órdenes; que `stock == SUM(movimiento_stock.cantidad)` por repuesto; que `verificar_password(CONTRASENA_FICTICIA, hash)` da verdadero para cada usuario y que `nuevo@` tiene `debe_cambiar_password`; que la orden EN_REPARACION cumple `cantidad > stock`; y que el historial de precio del filtro es 8000→8500.

- **Por qué no usar el fixture `sesion`**: el seed necesita su propia transacción completa (incluido `TRUNCATE`) y no debe compartir la sesión del test. Al terminar, el test limpia con el mismo `TRUNCATE` que usa la suite.
- **Cuidado**: no marcar los tests como paramétricos con la misma base en paralelo; la suite corre en serie (sin `xdist`).

## Risks / Trade-offs

- [El seed borra datos de trabajo] → Es explícito en el docstring y en el `--help` conceptual del README de C-11; no hay confirmación interactiva porque se usa en automatización.
- [Un `TRUNCATE` bloqueado por otra sesión abierta] → Se documenta "detené el servidor antes de sembrar"; en tests no hay concurrencia.
- [Bcrypt con costo 12 hace la carga perceptiblemente lenta (~1 hash)] → Aceptable; se hashea una sola vez.
- [Los ids dependen de `RESTART IDENTITY`] → Es deseable (estado predecible) y queda garantizado por la sentencia usada.
- [El seed puede quedar desactualizado si cambia el esquema] → Los tests de `test/test_seed.py` fallan en cuanto un modelo nuevo exija datos; C-11 corre el seed como parte de la verificación final.

## Migration Plan

1. `alembic upgrade head` (esquema completo, incluida la protección de C-09).
2. `python seed.py` → estado inicial; imprime el resumen de conteos.
3. Re-ejecutable en cualquier momento; en C-11 se corre después de consolidar migraciones y antes de `test/solo_agregado.sql`.
4. Rollback: no aplica (el seed no cambia esquema); para volver a un estado limpio se vuelve a ejecutar el seed o se recrea la base.
