# Proposal

## Why

Las tres tablas de historial del taller (`historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto`) sostienen la auditoría del negocio: si una fila se pudiera editar o borrar, el stock, el estado de las órdenes y el historial de precios dejarían de ser confiables. Hoy la inmutabilidad es solo una convención del código de aplicación (RN-15); la base la aceptaría si algo —un script, un bug, una conexión manual— hace `UPDATE` o `DELETE`.

Además, la consigna exige una evidencia verificable en psql de que la base rechaza esas operaciones y de que un estado fuera del catálogo `estado_orden` lo rechaza la clave foránea (US-031, C-14). Esa garantía tiene que vivir en el esquema, no en la aplicación, y sobrevivir a la consolidación de migraciones de C-11.

## What Changes

- Nueva migración **escrita a mano** `006_disparador_solo_agregado` (no autogenerate): crea una función de disparador y tres disparadores `BEFORE UPDATE OR DELETE` que rechazan cualquier intento sobre las tres tablas de sólo agregado, con un mensaje propio que identifica la tabla y la operación (sin filtrar el mapa del esquema al cliente HTTP; el error solo se ve en la base).
- El `downgrade` elimina los tres disparadores y la función, dejando el esquema exactamente como estaba (upgrade/downgrade reproducibles).
- La migración se escribe **sin depender de identificadores autogenerados**: solo `op.execute` con `CREATE OR REPLACE FUNCTION`, `DROP TRIGGER IF EXISTS` y `CREATE TRIGGER`, para que C-11 pueda renumerarla a `002_disparador_solo_agregado` de forma mecánica.
- Nuevo script `test/solo_agregado.sql` ejecutable con `psql \i`: los 6 rechazos del disparador (`UPDATE` y `DELETE` sobre cada una de las 3 tablas) más el rechazo de la FK al insertar una orden con `estado` fuera del catálogo, con `\echo` para que la captura C-14 muestre cada caso.
- Tests automatizados en pytest que, contra la base de pruebas migrada, verifican: `UPDATE` y `DELETE` fallan con el error del disparador en las 3 tablas, `INSERT` sigue funcionando en las 3, y la migración sube y baja sin dejar residuos.
- Sin cambios en la API ni en los contratos HTTP: ninguna ruta intenta modificar ni borrar esas tablas, así que el comportamiento observable de la aplicación no cambia.

## Capabilities

### New Capabilities

- `append-only-integrity`: garantía a nivel de base de que las tablas de historial son de sólo agregado (ni `UPDATE` ni `DELETE`, solo `INSERT`) y de que el catálogo de estados es cerrado por clave foránea; incluye la preservación de la garantía a través de la migración que la instala.

### Modified Capabilities

_(ninguna: no cambian requisitos de capacidades existentes)_

## Impact

- **Esquema/DB**: nueva migración `migrations/versions/006_disparador_solo_agregado.py` (revision `006_disparador_solo_agregado`, `down_revision` `005_ordenes_crud`); función `fn_bloquear_modificacion_historial` y disparadores `trg_solo_agregado_historial_estado_orden`, `trg_solo_agregado_movimiento_stock`, `trg_solo_agregado_historial_precio_repuesto`.
- **Archivos nuevos**: `test/solo_agregado.sql`; tests de integridad en `test/` (p. ej. `test/test_solo_agregado.py`).
- **Aplicación**: sin cambios de código; RN-15 se cumple ahora en la base además de en el código.
- **Pruebas**: la suite deriva el esquema de `alembic upgrade head`, así que la migración se aplica sola en `taller_test`; el `TRUNCATE` de limpieza entre tests no dispara los disparadores (son de fila, `TRUNCATE` no los activa) y debe seguir funcionando.
- **Entrega (C-11/C-14)**: esta migración es la que se renumera a `002_disparador_solo_agregado` y el script es el insumo de la captura `docs/evidencias/C-14.png`.
- **Riesgo**: si en el futuro se necesita corregir una fila de historial, habrá que hacerlo por migración explícita (deshabilitando el disparador de forma controlada), nunca desde la aplicación.
