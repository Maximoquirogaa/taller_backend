-- test/solo_agregado.sql — evidencia C-14 (US-031, RN-15, RN-19)
--
-- Demuestra, en psql, que la base rechaza:
--   * 3 UPDATE y 3 DELETE sobre las tablas de sólo agregado (6 errores del disparador)
--   * 1 INSERT de una orden con un estado fuera del catálogo (error de clave foránea)
--
-- PRECONDICIÓN: la base debe tener datos, es decir `alembic upgrade head` y
-- `python seed.py` (el seed llega en C-10). Con las tablas vacías el disparador
-- de fila no se activa y no habría nada que capturar.
--
-- USO (desde la raíz del repo):
--   psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB -f test/solo_agregado.sql
--
-- El script NO detiene la ejecución en el primer error: `ON_ERROR_STOP off`
-- garantiza que los 7 rechazos se vean seguidos en la misma ventana.

\set ON_ERROR_STOP off
\echo '== C-14: sólo agregado (6 errores esperados) + FK del catálogo (1 error esperado) =='
\echo '== Precondición: alembic upgrade head + python seed.py =='

\echo '-- 1/7 UPDATE historial_estado_orden (se espera error del disparador)'
UPDATE historial_estado_orden SET cuando = cuando WHERE TRUE;

\echo '-- 2/7 DELETE historial_estado_orden (se espera error del disparador)'
DELETE FROM historial_estado_orden WHERE TRUE;

\echo '-- 3/7 UPDATE movimiento_stock (se espera error del disparador)'
UPDATE movimiento_stock SET cuando = cuando WHERE TRUE;

\echo '-- 4/7 DELETE movimiento_stock (se espera error del disparador)'
DELETE FROM movimiento_stock WHERE TRUE;

\echo '-- 5/7 UPDATE historial_precio_repuesto (se espera error del disparador)'
UPDATE historial_precio_repuesto SET cuando = cuando WHERE TRUE;

\echo '-- 6/7 DELETE historial_precio_repuesto (se espera error del disparador)'
DELETE FROM historial_precio_repuesto WHERE TRUE;

\echo '-- 7/7 INSERT orden_trabajo con estado fuera del catálogo (se espera error de FK)'
INSERT INTO orden_trabajo (vehiculo_id, mecanico_id, estado, falla, creada_en, total)
SELECT id, NULL, 'INEXISTENTE', 'prueba C-14 (FK del catálogo)', now(), 0
FROM vehiculo
LIMIT 1;

\echo '== Fin de la evidencia: se esperan exactamente 7 ERROR =='
