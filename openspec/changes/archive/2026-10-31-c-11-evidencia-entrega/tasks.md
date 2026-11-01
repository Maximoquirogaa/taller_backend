# Tasks

## 1. Consolidación de migraciones (entregable: exactamente 2 archivos)

- [ ] 1.1 Dejar `migrations/versions/` vacía (borrar `*`) y correr `alembic revision --autogenerate -m "esquema inicial"` sobre base vacía con todos los modelos importados en `env.py` → generar `001_esquema_inicial`; verificar que el archivo existe y cubre las 13 tablas, CHECK, índices parciales, FKs, `timestamptz` y `NUMERIC`
- [ ] 1.2 Renumerar `006_disparador_solo_agregado.py` a `002_disparador_solo_agregado.py`, ajustar `down_revision` a la revisión de `001` y conservar el contenido tal cual (escrita a mano, sin regenerar); borrar el resto de `migrations/versions/*` para que queden solo `001` y `002`
- [ ] 1.3 Ejecutar `alembic upgrade head` → `alembic check` → `alembic downgrade base` → `alembic upgrade head`; verificar que termina sin errores, `alembic check` reporta "No new upgrade operations detected" y la revisión final es head

## 2. Seed y evidencia SQL (C-14)

- [ ] 2.1 Ejecutar `python seed.py` sobre el esquema consolidado; verificar que imprime el resumen de conteos y deja el estado inicial (catálogo 4 estados, 7 usuarios con roles, 2 clientes, 3 vehículos, 4 repuestos con stock, 2 órdenes, 1 evento de `SISTEMA`)
- [ ] 2.2 Ejecutar `test/solo_agregado.sql` con `psql \i` sobre la base sembrada; verificar los 7 rechazos esperados (6 del disparador + 1 de FK de estado fuera del catálogo) y que ninguna fila de historial se modifica ni borra (evidencia C-14)

## 3. Suite HTTP de la consigna (C-01…C-19)

- [ ] 3.1 Crear `test/*.http` con los casos ejercicio C-01…C-19 de la consigna, cada uno con su respuesta esperada documentada (código de estado y cuerpo)
- [ ] 3.2 Implementar los casos de login con `# @no-cookie-jar` y captura del `Set-Cookie`; verificar que el JWT viaja solo en cookie HttpOnly/SameSite=Lax, nunca en el cuerpo (DD-04), y que `Authorization: Bearer` sin cookie responde 401

## 4. Verificaciones C-15, C-16 y checklist final

- [ ] 4.1 Verificación C-15: detalle de orden con 2 ítems y con 4 ítems → mismas consultas SQL (SQL_ECHO en dev), sin N+1
- [ ] 4.2 Verificación C-16: `GET /repuestos?q=` con intento de inyección → lista vacía, total 0, sin 500 (RN-18)
- [ ] 4.3 Checklist final: ninguna entrada inválida termina en 500; ningún error expone `password_hash`, texto interno de PostgreSQL ni trazas (RN-18); login Bearer sin cookie → 401 (DD-04)

## 5. README de entrega y cierre

- [ ] 5.1 Escribir README de entrega: cómo instalar, variables (`env.example`), migrar, seed, arrancar (uvicorn puerto 8000), ejecutar pruebas y las credenciales ficticias que deja `seed.py` (`Taller2026` + emails de cada rol)
- [ ] 5.2 Ejecutar `pytest -q` completo sobre el esquema consolidado y verificar que no hay regresiones; ejecutar `openspec validate c-11-evidencia-entrega --strict` y verificar que el change es válido

## Workflow follow-up

- Implementar las tareas arriba (fase apply de C-11).
- Ejecutar `openspec validate c-11-evidencia-entrega --strict` para confirmar que el change está completo y válido.
- Archivar el change y marcar C-11 como `[x]` en `CHANGES.md`.
