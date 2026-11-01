# Proposal

## Why

El entregable del TP pide exactamente dos migraciones en el esquema (`001_esquema_inicial` + `002_disparador_solo_agregado`, DD-08), una suite HTTP con los casos C-01…C-19 de la consigna cada uno con su respuesta esperada, las evidencias C-14 (disparador de sólo agregado), C-15 (detalle de orden sin N+1) y C-16 (búsqueda `q` segura ante inyección), y un README de entrega con credenciales y pasos. Hoy esas piezas no existen de forma consolidada: las migraciones de desarrollo (001…006) aún viven en `migrations/versions/`, no hay archivo `.http` con respuestas esperadas, y no hay README que documente cómo instalar, migrar, sembrar y arrancar la API. C-11 cierra Gate 6 (C-08, C-09, C-10 archivados) y deja el proyecto listo para entregar.

## What Changes

- **Consolidar migraciones**: borrar `migrations/versions/*`, autogenerar `001_esquema_inicial` sobre base vacía con todos los modelos importados en `env.py`, renumerar la migración del disparador de C-09 a `002_disparador_solo_agregado` (ajustar `down_revision`, conservarla tal cual), y verificar `upgrade head` → `alembic check` sin diferencias → `downgrade base` → `upgrade head` → `python seed.py` → `test/solo_agregado.sql` → `pytest`. Ninguna migración de desarrollo sobrevive.
- **Suite HTTP `test/*.http`**: casos ejercicio C-01…C-19 de la consigna, cada uno con respuesta esperada; login con `# @no-cookie-jar` y captura del `Set-Cookie` (DD-04: solo cookie HttpOnly, Bearer → 401).
- **Verificación C-15**: detalle de orden con 2 y 4 ítems → mismas consultas (SQL_ECHO en dev).
- **Verificación C-16**: `q` con intento de injection → lista vacía, total 0, sin 500 (RN-18).
- **Evidencia C-14**: `test/solo_agregado.sql` ejecutado en consola / fragmento de captura.
- **README de entrega**: instalar, variables (`env.example`), migrar, seed, arrancar (uvicorn puerto 8000), ejecutar pruebas, credenciales ficticias (`Taller2026` + emails de cada rol).
- **Checklist final**: ninguna entrada inválida → 500; ningún error expone texto de la base (RN-18); login Bearer sin cookie → 401 (DD-04).

## Capabilities

### New Capabilities

- `evidencia-entrega`: estado de entrega del TP — esquema consolidado en dos migraciones, suite HTTP de los casos C-01…C-19 con respuestas esperadas, evidencias C-14 (sólo agregado), C-15 (detalle de orden sin N+1) y C-16 (búsqueda segura), y README de entrega con credenciales ficticias.

### Modified Capabilities

_(ninguna: no cambian requisitos de capacidades existentes; C-11 consolida y documenta, no altera contratos de la API)_

## Impact

- **Esquema/DB**: `migrations/versions/` queda con exactamente dos archivos (`001_esquema_inicial`, `002_disparador_solo_agregado`); `alembic check` debe reportar sin diferencias.
- **Archivos nuevos**: `test/*.http` (suite de consigna), README de entrega, capturas de evidencia C-14/C-15.
- **Aplicación**: sin cambios de rutas ni contratos HTTP; solo reorganización del historial de migraciones y agregado de pruebas, evidencias y documentación.
- **Pruebas**: `pytest` completo verde tras la consolidación; `test/solo_agregado.sql` con los 7 rechazos esperados en verde.
- **Entrega (C-11)**: orden de verificación `alembic upgrade head` → `python seed.py` → `test/solo_agregado.sql` → capturas → `pytest`.
- **Riesgo**: la consolidación reescribe el historial de migraciones; si el esquema cambia después, hay que repetir la consolidación (nunca `ALTER` suelto).
