# Tasks

## 1. Red de seguridad y RED

- [ ] 1.1 Correr la suite completa (`pytest -q`) y anotar el baseline (`339 passed` esperado) para comparar después
- [ ] 1.2 Crear `test/test_seed.py` con la fixture que usa `fabrica_pruebas` y un test que importa `cargar_datos_iniciales` desde `seed`; correrlo y verificar que **falla** (RED) porque la función no existe (el módulo sólo tiene el stub)
- [ ] 1.3 Escribir el test del estado inicial (catálogo con `es_final`, 7 usuarios con roles vigentes, 2 clientes, 3 vehículos, 4 repuestos, 2 órdenes, evento de seguridad) y verificar el RED
- [ ] 1.4 Escribir el test de idempotencia (dos ejecuciones seguidas dejan los mismos conteos) y verificar el RED
- [ ] 1.5 Escribir el test de credenciales (`verificar_password` con la contraseña ficticia para cada usuario, `nuevo@` con `debe_cambiar_password` y rol MECANICO) y verificar el RED
- [ ] 1.6 Escribir el test de stock inicial (`stock == SUM(movimiento_stock.cantidad)` por repuesto) y de la orden EN_REPARACION con `cantidad > stock`; verificar el RED
- [ ] 1.7 Escribir el test del historial de precios (filtro 8000 → 8500 atribuido a un ADMIN y precio vigente 8500) y verificar el RED

## 2. Implementación de `seed.py` (GREEN)

- [ ] 2.1 Definir en `seed.py` las constantes de datos (catálogo, usuarios con roles, clientes/vehículos, repuestos, órdenes) y la lista de tablas a truncar; verificar que el módulo importa sin ejecutar nada
- [ ] 2.2 Implementar `cargar_datos_iniciales(fabrica)` con `TRUNCATE ... RESTART IDENTITY CASCADE` de las 13 tablas dentro de una única transacción; verificar que al importar la función y correr el test 1.2 deja de fallar por import
- [ ] 2.3 Cargar el catálogo `estado_orden` primero (PENDIENTE, EN_REPARACION, TERMINADA final, CANCELADA final) y verificar que el test 1.3 ve los 4 estados con sus `es_final`
- [ ] 2.4 Cargar los 7 usuarios con `hash_password` (una sola vez) y sus `asignacion_rol` vigentes con `otorgada_por` del admin; verificar que el test 1.5 pasa
- [ ] 2.5 Cargar Laura (vinculada a `cliente@`) con 2 vehículos y Jorge (sin usuario) con 1 vehículo; verificar el conteo de clientes y vehículos del test 1.3
- [ ] 2.6 Cargar los 4 repuestos y una fila de `movimiento_stock` de alta por cada uno; verificar que el test 1.6 pasa (stock igual a la suma de movimientos)
- [ ] 2.7 Cargar las 2 órdenes con sus ítems, totales y líneas de historial (nulo → PENDIENTE; PENDIENTE → EN_REPARACION con `mecanico@`); verificar que el test 1.3 ve 2 órdenes y el 1.6 confirma las 4 bujías contra stock 2
- [ ] 2.8 Cargar el historial de precios del filtro (8000 → 8500, `usuario_id` del admin) y el `evento_seguridad` de `SISTEMA` «Carga de los datos iniciales»; verificar que el test 1.7 pasa
- [ ] 2.9 Implementar `main()` (Settings + motor + fábrica + `asyncio.run`) con resumen de conteos por consola y docstring que documente las credenciales ficticias; verificar `python -c "import seed"` sin efectos
- [ ] 2.10 Correr `test/test_seed.py` completo sin ningún RED pendiente y verificar que todos los tests pasan, incluida la segunda ejecución consecutiva

## 3. Verificación en la base de desarrollo

- [ ] 3.1 Ejecutar `python seed.py` sobre `taller` (previa `alembic upgrade head`) y verificar que imprime el resumen y termina sin error
- [ ] 3.2 Ejecutar `python seed.py` por segunda vez sobre `taller` y verificar que el resumen es idéntico (idempotencia real, no sólo en tests)
- [ ] 3.3 Consultar la base sembrada y verificar que la orden EN_REPARACION pide 4 bujías con stock 2 y que el filtro tiene precio 8500 con historial 8000 → 8500
- [ ] 3.4 Correr `test/solo_agregado.sql` sobre `taller` ya sembrada (psql) y verificar los 7 errores esperados: deja de ser una verificación con filas de prueba, pasa a ser la evidencia C-14 sobre datos reales

## 4. Integración y cierre

- [ ] 4.1 Correr la suite completa (`pytest -q`) y verificar que no hay regresiones frente al baseline de 1.1 (mismo número + los nuevos tests, todos verdes)
- [ ] 4.2 Verificar que el seed no rompe los disparadores de C-09: la suite completa corre sin errores de sólo agregado y el seed sólo hace `INSERT` en las tres tablas de historial
- [ ] 4.3 Correr `alembic check` sobre la base de desarrollo y verificar que sigue respondiendo "No new upgrade operations detected" (C-10 no agrega migraciones)
- [ ] 4.4 Correr `openspec validate c-10-seed-inicial --strict` y verificar que el change es válido

## Workflow follow-up

- Archivar el change y promover el delta `seed-inicial` a `openspec/specs/seed-inicial/spec.md`.
- Marcar C-10 como completado en `CHANGES.md`.
- Dejar anotado para C-11: el orden de entrega pasa a ser `alembic upgrade head` → `python seed.py` → `test/solo_agregado.sql` → capturas, y las credenciales ficticias del seed van al README.
