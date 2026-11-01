# Tasks

## 1. Red de seguridad y RED

- [ ] 1.1 Correr la suite completa antes de tocar nada (`pytest -q`) y anotar el baseline (`329 passed` esperado) para poder comparar después
- [ ] 1.2 Crear `test/test_solo_agregado.py` con las fixtures mínimas (catálogo `estado_orden`, usuario, cliente/vehículo, repuesto y una fila en cada tabla de historial) y verificar que las fixtures insertan sin error
- [ ] 1.3 Escribir el test que espera que `UPDATE` falle en las tres tablas de historial; correrlo y verificar que **falla** (RED) porque todavía no existe ningún disparador
- [ ] 1.4 Escribir el test que espera que `DELETE` falle en las tres tablas y verificar el RED
- [ ] 1.5 Escribir el test que espera que `INSERT` siga funcionando en las tres tablas y verificar que hoy pasa (comportamiento actual correcto que hay que preservar)
- [ ] 1.6 Escribir el test de la FK del catálogo (`INSERT INTO orden_trabajo ... estado = 'INEXISTENTE'` → violación de FK) y verificar que pasa antes del cambio

## 2. Migración escrita a mano (GREEN)

- [ ] 2.1 Crear `migrations/versions/006_disparador_solo_agregado.py` con `revision = '006_disparador_solo_agregado'`, `down_revision = '005_ordenes_crud'` y docstring que declare explícitamente que es escrita a mano y que sobrevive a la consolidación de C-11
- [ ] 2.2 En `upgrade`, crear con `op.execute` la función `fn_bloquear_modificacion_historial()` (`plpgsql`, `RAISE EXCEPTION USING ERRCODE = 'P0001'` con `TG_TABLE_NAME` y `TG_OP` en el mensaje); verificar con `psql -c "\df fn_bloquear_modificacion_historial"` que existe
- [ ] 2.3 En `upgrade`, crear los tres disparadores con `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER ... BEFORE UPDATE OR DELETE ... FOR EACH ROW` sobre las tres tablas; verificar que `SELECT tgname FROM pg_trigger WHERE NOT tgisinternal` lista los tres
- [ ] 2.4 En `downgrade`, eliminar los tres disparadores y la función con `DROP ... IF EXISTS`; verificar que tras `alembic downgrade -1` no quedan en `pg_trigger` ni en `pg_proc`
- [ ] 2.5 Aplicar `alembic upgrade head` y correr `test/test_solo_agregado.py`: los casos de `UPDATE`/`DELETE` deben pasar (GREEN) y los de `INSERT`/FK seguir verdes
- [ ] 2.6 Ejecutar `alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head` sobre una base de prueba y verificar que no hay error y que la protección vuelve a estar activa (guardar la secuencia como evidencia)

## 3. Script de evidencia C-14

- [ ] 3.1 Crear `test/solo_agregado.sql` con `\set ON_ERROR_STOP off`, un `\echo` por caso y las 6 sentencias (`UPDATE` y `DELETE` × 3 tablas) apuntando a `WHERE TRUE` para no depender de ids fijos
- [ ] 3.2 Agregar al script el séptimo caso (`INSERT INTO orden_trabajo` con `estado = 'INEXISTENTE'` tomando un vehículo existente) y el `\echo` de precondición que recuerda ejecutar `seed.py` primero
- [ ] 3.3 Ejecutar el script con `psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB -f test/solo_agregado.sql` sobre `taller` con el seed cargado y verificar que aparecen exactamente 7 errores: 6 del disparador y 1 de FK
- [ ] 3.4 Documentar en `knowledge-base/11_evidencias_c14_c15.md` que el script ya existe y cómo correrlo (paso 2 de la sección C-14), verificando que las instrucciones coinciden con el archivo real

## 4. Integración y cierre

- [ ] 4.1 Correr la suite completa (`pytest -q`) y verificar que no hay regresiones frente al baseline de 1.1 (mismo número de tests + los nuevos, todos verdes)
- [ ] 4.2 Verificar que la limpieza entre tests sigue funcionando: `TRUNCATE ... CASCADE` no se ve afectado por los disparadores (la suite debe correr sin errores de disparador en la limpieza)
- [ ] 4.3 Correr `alembic check` sobre la base de desarrollo y verificar que responde "No new upgrade operations detected"
- [ ] 4.4 Correr `openspec validate c-09-append-only-triggers --strict` y verificar que el change es válido

## Workflow follow-up

- Archivar el change cuando la revisión esté aprobada y promover el delta `append-only-integrity` a `openspec/specs/append-only-integrity/spec.md`.
- Marcar C-09 como completado en `CHANGES.md`.
- Dejar anotado para C-11: renombrar la migración a `002_disparador_solo_agregado.py`, ajustar `revision`/`down_revision` y reusar `test/solo_agregado.sql` para la captura `docs/evidencias/C-14.png`.
