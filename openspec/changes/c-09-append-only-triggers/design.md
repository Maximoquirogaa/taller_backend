# Design

## Context

Ver `proposal.md` §Why. Lo relevante para el diseño:

- Las tres tablas existen desde las migraciones 004 y 005, y la aplicación nunca las actualiza ni borra (sólo inserta).
- El esquema de pruebas se construye **únicamente** con `alembic upgrade head` (`test/conftest.py`), por lo que la protección entra en la suite sin tocar fixtures.
- La limpieza entre tests usa `TRUNCATE ... RESTART IDENTITY CASCADE` sobre las 13 tablas.
- El entregable exige exactamente dos migraciones: ésta es de desarrollo y **C-11 la renumera** a `002_disparador_solo_agregado` conservándola tal cual (DD-08).
- El driver es `asyncpg`; PostgreSQL 16.

## Goals / Non-Goals

**Goals:**

- Que la base rechace `UPDATE` y `DELETE` en `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`.
- Que la garantía sea versionada: `upgrade` la instala, `downgrade` la retira sin residuos, y ambas son repetibles.
- Dejar un script `test/solo_agregado.sql` listo para la captura C-14 (6 rechazos del disparador + 1 rechazo de FK) y tests automatizados equivalentes.
- Mantener la migración renombrable a mano por C-11 (sin depender de hashes ni identificadores autogenerados).

**Non-Goals:**

- No se protege contra `TRUNCATE`, `DROP TABLE` ni `ALTER`: son operaciones de mantenimiento del dueño del esquema, no vías de la aplicación.
- No se agregan reglas de negocio nuevas ni endpoints: la API no cambia.
- No se toca `seed.py` (C-10) ni la consolidación de migraciones (C-11).

## Decisions

### D1 — Disparador `BEFORE UPDATE OR DELETE` por fila, una función compartida

Una única función `fn_bloquear_modificacion_historial()` (`LANGUAGE plpgsql`, `RETURNS trigger`) que hace `RAISE EXCEPTION USING ERRCODE = 'P0001'` con un mensaje que incluye `TG_TABLE_NAME` y `TG_OP`, y tres disparadores `BEFORE UPDATE OR DELETE ... FOR EACH ROW`.

- **Por qué una función y no tres**: el mensaje y la lógica son idénticos; `TG_TABLE_NAME`/`TG_OP` ya identifican el caso. Menos código que renumerar en C-11 y un solo lugar donde cambiar el mensaje.
- **Por qué `BEFORE` y no `AFTER`**: la sentencia falla antes de tocar la fila; con `AFTER` el daño ya estaría escrito y sólo se revertiría por el aborto de la transacción. `BEFORE` expresa mejor la intención.
- **Por qué `FOR EACH ROW`**: `RAISE EXCEPTION` aborta la sentencia completa; el disparador de fila garantiza que alcance tanto a `WHERE id = 1` como a `WHERE TRUE`.
- **Alternativas descartadas**: `CREATE RULE ... DO INSTEAD NOTHING` (descarta la operación en silencio: el `UPDATE`/`DELETE` parecería exitoso, justo lo que RN-15 no quiere) y `REVOKE UPDATE, DELETE` (depende de roles y `GRANT`; la app podría caer en un rol con permisos amplios y no es tan explícito).

### D2 — Migración escrita a mano, sólo `op.execute` con SQL literal

`006_disparador_solo_agregado.py`, `revision = '006_disparador_solo_agregado'`, `down_revision = '005_ordenes_crud'`. No usa `sa.Column` ni generación de identificadores: únicamente `op.execute` con cadenas SQL constantes.

`upgrade`:
1. `CREATE OR REPLACE FUNCTION fn_bloquear_modificacion_historial() ...`
2. Por cada tabla: `DROP TRIGGER IF EXISTS <trigger> ON <tabla>` y `CREATE TRIGGER <trigger> BEFORE UPDATE OR DELETE ON <tabla> FOR EACH ROW EXECUTE FUNCTION fn_bloquear_modificacion_historial()`.

`downgrade`: `DROP TRIGGER IF EXISTS` de los tres y `DROP FUNCTION IF EXISTS fn_bloquear_modificacion_historial()`.

- **Por qué `DROP TRIGGER IF EXISTS` antes de crear**: hace la migración re-ejecutable a mano sobre una base donde los disparadores ya existen (por ejemplo al probar el ciclo upgrade/downgrade/upgrade).
- **Por qué SQL literal**: C-11 renombra el archivo y la revisión; con literales el contenido sobrevive idéntico y el renombrado es mecánico (DD-08). También evita que `alembic check` vea "nuevas operaciones" por funciones que no están en `SQLModel.metadata`.
- **Nombres**: `trg_solo_agregado_historial_estado_orden`, `trg_solo_agregado_movimiento_stock`, `trg_solo_agregado_historial_precio_repuesto`; mismo prefijo para que un `DROP TRIGGER IF EXISTS` y la auditoría en `pg_trigger` sean legibles.
- **Comentario explícito en el docstring de la migración** de que es escrita a mano y que sobrevive a la consolidación (requisito de C-09 en CHANGES.md).

### D3 — `TRUNCATE` queda permitido (y la suite depende de eso)

Los disparadores de fila no se activan con `TRUNCATE`; el `TRUNCATE ... CASCADE` de `test/conftest.py` sigue limpiando entre tests, y el script SQL puede preparar filas sin fricción.

- **Trade-off aceptado**: alguien con permisos de dueño podría vaciar el historial con `TRUNCATE`. No es una vía de la aplicación y la consigna pide explícitamente los 6 rechazos de `UPDATE`/`DELETE`; agregar un disparador de `TRUNCATE` rompería la limpieza de la suite y obligaría a desactivarlo en tests. Se documenta como límite conocido en `docs/` al entregar C-11.

### D4 — `test/solo_agregado.sql` como script de `psql` autónomo, con precondición de seed

Estructura:

```sql
\set ON_ERROR_STOP off
\echo '== C-14: sólo agregado (se esperan 6 errores) + FK del catálogo =='
\echo '-- 1/7 UPDATE historial_estado_orden'
UPDATE historial_estado_orden SET usuario_id = usuario_id WHERE TRUE;
... (x6: UPDATE y DELETE sobre cada tabla)
\echo '-- 7/7 INSERT orden con estado fuera del catálogo'
INSERT INTO orden_trabajo (vehiculo_id, mecanico_id, estado, falla, creada_en, total)
SELECT id, NULL, 'INEXISTENTE', 'prueba C-14', now(), 0 FROM vehiculo LIMIT 1;
```

- **Precondición**: `python seed.py` ya ejecutado (es lo que indica `knowledge-base/11_evidencias_c14_c15.md` para C-14); el script lo recuerda en un `\echo` inicial. Si no hay filas, el disparador no se dispara y la captura quedaría vacía, por eso el script apunta a `WHERE TRUE` (todas las filas) en lugar de a un `id` fijo, que se rompería en cada reseed.
- **Por qué `ON_ERROR_STOP off`**: es el comportamiento por defecto de `psql` fuera de transacción, pero dejarlo explícito garantiza que los 7 errores se muestren seguidos en la misma ventana (lo que pide la evidencia).
- **Por qué la FK y no otro `UPDATE`**: US-031/C-14 pide que un estado fuera del catálogo lo rechace la clave foránea; el `INSERT` referencia un `vehiculo` existente del seed para que el único error posible sea la FK.

### D5 — Tests automatizados con SQL crudo sobre la base migrada

Nuevo `test/test_solo_agregado.py` (junto a `test_uow.py` y `test_repositorio.py`, porque es una garantía de esquema, no de un módulo). Usa el fixture `sesion` existente y `text()` de SQLAlchemy:

- Fixture local que inserta un juego mínimo de filas (catálogo `estado_orden`, usuario, vehículo/cliente, repuesto y una fila en cada tabla de historial) reutilizando los modelos ya existentes.
- Cada caso ejecuta el `UPDATE`/`DELETE`, espera `sqlalchemy.exc.DBAPIError` con el mensaje del disparador, hace `rollback()` y verifica con `SELECT` que las filas siguen intactas.
- Un caso de `INSERT` por tabla para demostrar que la vía legítima sigue abierta.
- Un caso de FK con `estado = 'INEXISTENTE'` que espera `IntegrityError`/`ForeignKeyViolationError`.
- El ciclo upgrade/downgrade/upgrade se prueba con un test marcado para base de pruebas (ejecutando `alembic downgrade -1` y `upgrade head` sobre `taller_test`), o se verifica a mano si interferir con el esquema durante la sesión resulta frágil; en ese caso queda como verificación documentada en tasks.

- **Por qué SQL crudo y no el ORM**: la garantía es de PostgreSQL; un test con ORM podría pasar por casualidad si el ORM no emite el `UPDATE` esperado. Además, el mensaje del disparador es parte de lo observable.
- **Cuidado con el rollback**: al abortarse la transacción, la sesión queda inutilizable hasta `rollback()`; los tests capturan los ids antes de provocar el error (misma lección que en C-08).

## Risks / Trade-offs

- [`alembic check` podría reportar diferencias si C-11 autogenera desde cero] → La función y los disparadores no están en `SQLModel.metadata`; la migración consolidada de C-11 debe incluir el bloque a mano *después* del autogenerate, y `alembic check` compara tablas/columnas/índices, no triggers.
- [El script SQL depende del seed y falla silenciosamente si la base está vacía] → El script imprime la precondición y `WHERE TRUE` evita ids fijos; C-11 documenta el orden `alembic upgrade head` → `python seed.py` → `\i test/solo_agregado.sql`.
- [Un error de disparador dentro de un UoW podría convertirse en 500 si algún día la app intentara modificar historial] → Hoy ningún servicio lo hace; si ocurriera, es un defecto de la aplicación que debe traducirse en el router. Se acepta: la base es la última línea de defensa.
- [Los triggers agregan una verificación por fila en INSERT] → Los `BEFORE UPDATE OR DELETE` no se ejecutan en `INSERT`; el costo en la vía caliente es cero.
- [Renumerar en C-11 puede dejar referencias a `006`] → Sólo `down_revision` en el archivo y el comentario del docstring mencionan el número; el `revision` nuevo es el único cambio necesario además del nombre del archivo.

## Migration Plan

1. `alembic upgrade head` sobre `taller` y `taller_test` (la suite lo hace sola).
2. Verificación manual: `\i test/solo_agregado.sql` desde psql con el seed cargado → 7 errores.
3. Rollback: `alembic downgrade -1` deja el esquema sin la función ni los disparadores; volver a `upgrade head` restaura la protección.
4. En C-11: la migración se renombra a `002_disparador_solo_agregado.py` con `revision = '002_disparador_solo_agregado'` y `down_revision = '001_esquema_inicial'`, conservando el SQL tal cual.
