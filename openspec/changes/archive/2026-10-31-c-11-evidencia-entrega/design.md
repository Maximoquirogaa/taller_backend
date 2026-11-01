# Design

## Context

Ver `proposal.md` §Why y §What Changes. Estado actual relevante:

- `migrations/versions/` contiene las migraciones de desarrollo 001…006 (autogeneradas C-02…C-05 y la escrita a mano 006 de C-09); ninguna sobrevive al entregable salvo la del disparador, renumerada.
- `env.py` ya importa todos los modelos (plantilla asincrónica de C-01), por lo que `alembic revision --autogenerate` puede construir `001_esquema_inicial` sobre base vacía.
- `seed.py` ya está implementado (C-10 archivado) y es idempotente; deja credenciales ficticias documentadas (`Taller2026` + emails de cada rol).
- `test/solo_agregado.sql` ya existe (C-09) con los 6 rechazos del disparador + el rechazo de FK.
- No existe aún `test/*.http` ni el README de entrega.

## Goals / Non-Goals

**Goals:**

- `migrations/versions/` quede con exactamente dos archivos: `001_esquema_inicial` y `002_disparador_solo_agregado`.
- `alembic upgrade head` → `alembic check` (sin diferencias) → `alembic downgrade base` → `alembic upgrade head` → `python seed.py` → `test/solo_agregado.sql` → `pytest` pasen en verde.
- `test/*.http` cubra C-01…C-19 con respuestas esperadas y login vía `# @no-cookie-jar` + captura de `Set-Cookie`.
- Evidencias C-14 (sólo agregado), C-15 (detalle de orden, 2 vs 4 ítems, mismas consultas) y C-16 (`q` con inyección → lista vacía, total 0, sin 500).
- README de entrega con instalación, `env.example`, migrar, seed, arrancar (uvicorn :8000), ejecutar pruebas y credenciales ficticias.

**Non-Goals:**

- No se agregan rutas, esquemas HTTP ni contratos nuevos: C-11 no cambia el comportamiento de la API.
- No se modifican modelos ni servicios: si `alembic check` difiere, se corrige el modelo y se re-autogenera `001` (nunca `ALTER` suelto).
- No se regenera la migración del disparador: se conserva tal cual, solo se renumera y ajusta `down_revision`.

## Decisions

### D1 — `001_esquema_inicial` por autogenerate sobre base vacía

`alembic revision --autogenerate -m "esquema inicial"` con `env.py` importando todos los modelos y `target_metadata` apuntando a `SQLModel.metadata`. Se corre contra una base `taller` vacía (`alembic downgrade base` + recrear si hace falta) para que capture las 13 tablas, CHECK, índices únicos parciales, FKs indexadas, `timestamptz` y `NUMERIC`.

- **Alternativa descartada**: escribirla a mano. Es propensa a omisiones y `autogenerate` es la fuente de verdad del modelo.
- **Por qué sobre base vacía**: que la migración sea autosuficiente y que `upgrade head` desde cero funcione sin depender de revisiones intermedias.

### D2 — `002_disparador_solo_agregado` conservada tal cual, renumerada

La migración escrita a mano de C-09 (actualmente `006_disparador_solo_agregado.py`) se renombra a `002_disparador_solo_agregado.py` y su `down_revision` se ajusta a la revisión de `001_esquema_inicial`. No se regenera: usa solo `op.execute` (`CREATE OR REPLACE FUNCTION`, `DROP TRIGGER IF EXISTS`, `CREATE TRIGGER`), sin identificadores autogenerados, por lo que renumerarla es mecánico.

- **Alternativa descartada**: autogenerarla de nuevo. Los disparadores y la función no son detectables por `autogenerate`, por lo que deben escribirse a mano y conservarse.

### D3 — Orden de verificación de entrega

`alembic upgrade head` → `alembic check` → `alembic downgrade base` → `alembic upgrade head` → `python seed.py` → `test/solo_agregado.sql` → `pytest`. El seed corre después de tener el esquema final y antes de la evidencia SQL, para que el disparador se active sobre filas reales.

- **Por qué este orden**: valida reproducibilidad del esquema (upgrade/downgrade), consistencia modelos-vs-esquema (check), estado inicial conocido (seed), integridad de sólo agregado (SQL) y suite completa (pytest) en una secuencia repetible.

### D4 — Suite `.http` con `# @no-cookie-jar` para login

Los casos de login usan `# @no-cookie-jar` para evitar que el cliente HTTP reenvíe cookies automáticamente, capturan el `Set-Cookie` de la respuesta y lo inyectan en las peticiones protegidas posteriores. Así se demuestra DD-04 (token solo en cookie HttpOnly, Bearer → 401).

- **Por qué no Bearer**: la dependencia `usuario_actual` lee `request.cookies`; enviar `Authorization: Bearer` sin cookie debe dar 401.

### D5 — README con credenciales ficticias del seed

El README documenta `Taller2026` (contraseña ficticia compartida, hasheada una vez en `seed.py`) y los emails de cada rol (`admin@`, `admin2@`, `recepcion@`, `mecanico@`, `mecanico2@`, `cliente@`, `nuevo@` con cambio obligatorio), para que el corrector pueda entrar sin adivinar.

- **Por qué en seed.py y no en .env**: las contraseñas del seed son datos de demostración, nunca secretos de configuración versionada.

## Risks / Trade-offs

- [La consolidación reescribe el historial de migraciones] → si el esquema cambia tras C-11, hay que repetir la consolidación (borrar versiones, autogenerar `001`, renumerar `002`); nunca aplicar `ALTER` suelto. Mitigación: dejar documentado el orden exacto en el README.
- [Bcrypt en seed hace la carga perceptiblemente lenta] → se hashea una sola vez y se reutiliza para los 7 usuarios (D4 de C-10). Aceptable.
- [`.http` con cookie manual es más verboso] → necesario para demostrar DD-04; se deja el patrón de captura de `Set-Cookie` documentado en cada caso de login.

## Migration Plan

1. `alembic downgrade base` (o recrear base `taller` vacía) y `alembic revision --autogenerate -m "esquema inicial"` → `001_esquema_inicial`.
2. Renombrar `006_disparador_solo_agregado.py` a `002_disparador_solo_agregado.py` y ajustar `down_revision` a la revisión de `001`.
3. Borrar el resto de `migrations/versions/*`; quedar solo `001` y `002`.
4. `alembic upgrade head` → `alembic check` (sin diferencias) → `alembic downgrade base` → `alembic upgrade head`.
5. `python seed.py` → estado inicial; `test/solo_agregado.sql` → 7 rechazos esperados.
6. `pytest -q` → suite completa verde.
7. Escribir `test/*.http` (C-01…C-19) y README de entrega; tomar capturas C-14/C-15.
8. Rollback: no aplica a la consolidación (es reorganización de archivos); para deshacer, se restauran las migraciones de desarrollo desde el historial de cambios anteriores.

## Open Questions

Ninguna que cambie los specs, el enfoque o el desglose de tareas.
