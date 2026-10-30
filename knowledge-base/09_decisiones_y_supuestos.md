# Decisiones y Supuestos

## Decisiones documentadas (impuestas o elegidas por la consigna)

### DD-01 — Catálogo `estado_orden` en vez de CHECK
**Decisión**: estados de orden como tabla de referencia con PK `codigo`, `posicion`, `es_final`.
**Contexto**: el CHECK con la lista adentro no lleva datos ni se cruza desde la API.
**Alternativas**: CHECK enum en la columna.
**Justificación**: la FK sigue rechazando valores inválidos; `es_final` decide qué es orden abierta (RN-16); la API expone el catálogo.
**Trade-offs**: un estado nuevo toca el catálogo (seed), el enum de Python (contrato) y el servicio — los tres.

### DD-02 — Roles en `asignacion_rol`, no en `usuario`
**Decisión**: roles como filas vigentes con `desde`/`vence_en`/`revocada_en`/`otorgada_por`.
**Contexto**: la autorización debe poder cambiar con la sesión abierta y auditar quién tuvo qué rol.
**Alternativas**: columna `rol` en usuario + tabla de historial aparte.
**Justificación**: RN-04 se decide en la base en cada petición; revocar no borra (historial); vigencia nativa.
**Trade-offs**: más joins; índice único parcial obligatorio (RN-03).

### DD-03 — Índices únicos parciales para unicidad entre vigentes
**Decisión**: `WHERE borrado_en IS NULL` (patente, código) y `WHERE revocada_en IS NULL` (rol abierto).
**Contexto**: borrado lógico + UNIQUE simple impediría re-registrar patentes/códigos dados de baja.
**Alternativas**: uniqueness solo en la aplicación.
**Justificación**: la base garantiza (RN-01); C-19 lo demuestra.
**Trade-offs**: más índices; la lógica "vigente" vive en el SQL.

### DD-04 — Token solo en cookie HttpOnly, no Bearer
**Decisión**: JWT en `access_token` HttpOnly/SameSite=Lax; el cuerpo del login no lo trae.
**Contexto**: mitigar acceso desde JS (XSS).
**Alternativas**: `Authorization: Bearer` leído de cabecera.
**Justificación**: la dependencia lee `request.cookies`; Bearer sin cookie → 401 (C-03).
**Trade-offs**: testing más verboso (REST Client con `# @no-cookie-jar` + `{{login...Set-Cookie}}`).

### DD-05 — `iat` sin truncar a segundos en el cambio de contraseña
**Decisión**: comparar `iat` completo contra `password_cambiada_en`.
**Contexto**: truncar haría indistinguible una sesión del mismo segundo anterior al cambio.
**Alternativas**: truncar ambos lados.
**Justificación**: RN-07; el estándar JWT permite fracciones.
**Trade-offs**: dependencia del formato de tiempo del emisor.

### DD-06 — Hash ficticio para login con email inexistente
**Decisión**: verificar siempre con bcrypt, contra hash del usuario o hash inventado.
**Contexto**: RN-09 — no revelar qué cuentas existen por timing.
**Alternativas**: 401 inmediato si el usuario no existe.
**Justificación**: mismo cuerpo y tiempo en ambos casos.
**Trade-offs**: costo de bcrypt en logins inválidos (aceptado, es el precio del no-leak).

### DD-07 — `intento_acceso` en sesión/transacción propias
**Decisión**: el registro del intento no comparte la transacción de la petición.
**Contexto**: el fallo de login que se quiere contar es el mismo que revierte la transacción principal.
**Alternativas**: escribir en la misma sesión.
**Justificación**: debe sobrevivir al rollback (RN-08); única escritura que rompe la regla, documentada con su costo.
**Trade-offs**: deja filas aunque la petición falle (por diseño).

### DD-08 — Esquema solo con Alembic; dos migraciones en el entregable
**Decisión**: el entregable tiene **exactamente dos migraciones** — `001_esquema_inicial` (autogenerate sobre base vacía, con todos los modelos) + `002_disparador_solo_agregado` (escrita a mano). Sin `create_all`. Durante el desarrollo cada change genera migraciones incrementales **descartables** que C-11 consolida en esas dos.
**Contexto**: la consigna pide "dos migraciones"; la comparación automática no ve funciones ni disparadores; los tests de cada change necesitan el esquema real en la base.
**Alternativas**: crear el esquema desde la app; disparador fuera de migración; conservar las migraciones incrementales (7 archivos) — rechazada, no coincide con la consigna.
**Justificación**: upgrade/downgrade reproducibles; RN-15 vive en la base; el historial entregado coincide con lo pedido sin frenar el desarrollo.
**Trade-offs**: la consolidación de C-11 es un paso manual que hay que repetir si el esquema cambia después de consolidado.

### DD-09 — Lifespan para motor y fábrica (no al importar)
**Decisión**: recursos en `app.state` creados en el lifespan; `get_session` toma la fábrica de ahí; `dispose()` al apagar.
**Contexto**: EA-08 — construir al importar es antes del bucle de eventos; síntoma engañoso entre server y tests.
**Alternativas**: módulo-level engine.
**Justificación**: ciclo de vida explícito; `expire_on_commit=False`.
**Trade-offs**: un poco más de plumbing en dependencias.

### DD-10 — Dos grupos de rutas para el cambio obligatorio
**Decisión**: grupo abierto (salud + auth) y grupo protegido con el control montado una sola vez.
**Contexto**: FastAPI suma dependencias y no las resta — no se puede "desmontar" un control por ruta.
**Alternativas**: control individual por endpoint.
**Justificación**: RN-06 limpio; menos repetición.
**Trade-offs**: hay que no olvidarse de montar rutas en el grupo correcto.

### DD-11 — Stock con punto único de escritura + UoW al terminar orden
**Decisión**: el stock solo cambia vía movimientos (alta, reposición, terminación); terminar orden es un bloque transaccional con 4 clases de escritura.
**Contexto**: RN-13/RN-14; sin concurrencia (cap. 7 fuera de alcance) se acepta la actualización perdida.
**Alternativas**: UPDATE directo de stock desde varios lugares.
**Justificación**: un solo camino auditable; rollback completo si falta stock.
**Trade-offs**: no resuelve concurrencia — tema de próxima clase.

### DD-12 — Driver: asyncpg (resuelto — P-01)
**Decisión**: `postgresql+asyncpg://` como driver final (confirmado por el usuario el 2026-10-27: camino asincrónico; psycopg 3 asincrónico queda descartado).
**Contexto**: la consigna aceptaba ambos.
**Justificación**: es el del capítulo 4 del curso.
**Trade-offs**: ninguno — decisión cerrada; `requirements.txt` lleva `asyncpg`.

## Supuestos inferidos

### SU-01 — Duración del token: 1800 s (30 min)
**Supuesto**: el valor del ejemplo (`expira_en_segundos: 1800`) es la duración esperada.
**Origen**: cuerpo de ejemplo del login en la consigna.
**Riesgo si es falso**: tests de vencimiento podrían fallar si se espera otro valor.
**Cómo validar**: confirmar con el docente o fijarlo en Settings documentado.

### SU-02 — Costo bcrypt inicial: 12
**Supuesto**: costo por defecto razonable (consigna pide configurable, no un valor exacto).
**Origen**: práctica estándar; la consigna solo exige que esté en Settings.
**Riesgo si es falso**: ninguno funcional; solo performance de login.
**Cómo validar**: dejar `BCRYPT_COST` en Settings y documentarlo en el README.

### SU-03 — `COOKIE_SECURE=false` por defecto en desarrollo
**Supuesto**: Secure es configurable y off en local (no hay TLS).
**Origen**: consigna dice "Secure configurable".
**Riesgo si es falso**: cookies no viajarían en http local.
**Cómo validar**: variable de entorno documentada.

### SU-04 — Puerto uvicorn: 8000
**Supuesto**: el default de uvicorn (`--port 8000`) salvo indicación.
**Origen**: no está especificado.
**Riesgo si es falso**: confusión mínima en README/.http.
**Cómo validar**: documentar el comando de arranque exacto en el README de entrega.

### SU-05 — Módulo `health` solo con `router.py`
**Supuesto**: health no lleva models/schemas/service.
**Origen**: la consigna lo dice explícitamente.
**Riesgo si es falso**: ninguno.
**Cómo validar**: —
