# Preguntas Abiertas

## Inconsistencias detectadas

No hay contradicciones internas en la consigna (es una fuente única y consistente). La única "tensión" es de diseño asumida y documentada: DD-11 acepta la actualización perdida de stock porque la concurrencia (cap. 7) está explícitamente fuera de alcance.

## Dudas de interpretación resueltas como supuestos

Ver `09_decisiones_y_supuestos.md` SU-01…SU-05: duración del token (1800 s), costo bcrypt (12), Secure off en dev, puerto 8000, health solo-router.

## Preguntas resueltas

| Prioridad | Pregunta | Resolución | Fecha |
|-----------|----------|------------|-------|
| Alta | ¿asyncpg o psycopg 3 asincrónico como driver final? | **Driver asincrónico: `asyncpg`** (`postgresql+asyncpg://`) — camino async confirmado; psycopg 3 asincrónico queda descartado del alcance. | 2026-10-27 |
| Alta | ¿La evidencia de C-14/C-15 va como archivos o capturas? | **Capturas** (fragmento de consola/psql). Instrucciones paso a paso para correr los casos y tomarlas: [11_evidencias_c14_c15.md](11_evidencias_c14_c15.md). | 2026-10-27 |

## Preguntas abiertas (priorizadas)

| Prioridad | Pregunta | Bloquea | Decisor |
|-----------|----------|---------|---------|
| Media | ¿Nombre final del paquete Python (`app` está fijado por la estructura obligatoria — confirmar que no haya expectativa de otro root)? | Estructura | Docente |
| Media | ¿Seed con contraseñas "de mentira" exactas definidas o libres? La consigna solo pide que vivan en `seed.py` y no en el repo como secretos reales. | seed.py, C-04…C-09 | Equipo |
| Media | ¿Las migraciones deben poder aplicarse en CI sobre base vacía de forma automática, o basta documentado en README? | Entrega | Docente |
| Baja | ¿Conveniente agregar `pyproject.toml` además de `requirements.txt`? La consigna solo pide requirements.txt. | — | Equipo |
| Baja | ¿Exponer versión de la API (header o ruta)? No pedido; fuera de alcance estricto. | — | Equipo |

## [DISCOVERY] Campos de arquitectura inferidos del ingest

- `system_type` = `api` — inferido con confianza: la consigna es solo backend (sin frontend en alcance).
- `scale` = `team` — inferido: taller con personal (4 roles) y clientes que se registran; no es multi-tenant ni single-user. Confirmar si el corrector espera `public_multi_user` por el auto-registro.
- `needs_infra` = `true` — confianza alta: PostgreSQL 16 obligatorio (migraciones, disparador, seed).
