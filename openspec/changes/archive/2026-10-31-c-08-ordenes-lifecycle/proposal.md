# Proposal: Órdenes de Trabajo — Lifecycle y Transición de Estados (c-08-ordenes-lifecycle)

## Why

C-07 dejó las tablas de órdenes, el catálogo de estados (vacío) y la apertura en PENDIENTE operativas, pero la máquina de estados de la orden no existe: no hay forma de pasar una orden a EN_REPARACION, TERMINADA o CANCELADA, y al terminar no se descuenta stock ni se registran movimientos. RN-11, RN-12, RN-13 y RN-14 no tienen implementación, y el punto de extensión de C-04 (`DELETE /vehiculos/{id}` con `es_final` del catálogo) permanece sin cerrar. Este change implementa las tres transiciones sobre `app/modules/ordenes/` y la transacción crítica de stock que C-11 ejercerá como caso de stock insuficiente.

## What Changes

- `POST /ordenes/{id}/iniciar`: MECANICO (`requiere_rol("MECANICO")`); transiciona PENDIENTE → EN_REPARACION, asigna `mecanico_id` al usuario actual y agrega una línea de historial; 409 si el estado actual no lo permite (US-026, RN-11).
- `POST /ordenes/{id}/terminar`: mecánico asignado o ADMIN (ruta **sin** `requiere_rol` simple; el servicio evalúa el permiso). Dentro de un solo UoW: (1) verifica permiso + estado actual, (2) chequea stock de cada ítem y, si alguno es insuficiente, revierte todo (409 sin escrituras parciales — ejercicio C-11), (3) descuenta stock y crea filas de `movimiento_stock` (salida), (4) pasa a TERMINADA + línea de historial. Tras el commit, notificación vía `BackgroundTasks` (`asyncio.sleep(0.5)` + log) (US-027, RN-13, RN-14).
- `POST /ordenes/{id}/cancelar`: ruta **sin** `requiere_rol`; el servicio evalúa primero la relación personal/dueño del vehículo (403) y luego el estado PENDIENTE (409); PENDIENTE → CANCELADA + historial (US-028, RN-12).
- `DELETE /vehiculos/{id}` (C-04): ahora realmente rechaza con 409 cuando hay órdenes abiertas, leyendo `es_final` del catálogo `estado_orden` cuando exista (RN-16; cierra el punto de extensión de C-04).
- Migración de desarrollo para las nuevas escrituras (estado + historial + movimiento_stock), descartable en C-11.
- Suite de tests (`test/ordenes/` extendida) contra PostgreSQL `taller_test` con Strict TDD: RED primero, GREEN después, REFACtor verde; sin `create_all` — esquema solo desde `alembic upgrade head`.

## Capabilities

### New Capabilities

- `ordenes-lifecycle`: máquina de estados de órdenes de trabajo (iniciar → EN_REPARACION, terminar → TERMINADA con descuento de stock y movimientos, cancelar → CANCELADA), cada transición con línea de historial, permisos diferenciados por rol y relación, y transacción atómica de stock con rollback total ante insuficiencia.

### Modified Capabilities

- *(ninguna)*. C-08 no modifica los requisitos observables de `ordenes-crud`, `repuestos-stock`, `clientes-vehiculos` ni ningún otro spec existente: solo agrega transiciones de estado y escrituras de stock sobre el modelo ya creado por C-07. El `DELETE /vehiculos/{id}` de C-04 ya declara la comprobación de órdenes abiertas vía `es_final`; C-08 la hace efectiva al leer el catálogo sin cambiar el contrato de esa ruta.

## Impact

- **Base de datos**: migración de desarrollo (descartable en C-11) para las nuevas escrituras de `orden_trabajo` (estado, `mecanico_id`), `historial_estado_orden` y `movimiento_stock`; `env.py` ya importa el módulo de órdenes (C-07).
- **API**: tres rutas nuevas bajo `router_protegido` (`POST /ordenes/{id}/iniciar`, `POST /ordenes/{id}/terminar`, `POST /ordenes/{id}/cancelar`); 401 sin sesión; 403 por rol (iniciar: no MECANICO; terminar/cancelar: sin permiso) o por orden ajena; 409 por transición inválida o stock insuficiente; 404 por orden inexistente; 422 por contrato.
- **Código**: `app/modules/ordenes/service.py` (nuevas funciones `iniciar_orden`, `terminar_orden`, `cancelar_orden`), `app/modules/ordenes/router.py` (tres nuevas rutas), `app/modules/ordenes/schemas.py` (schemas de salida de transición si fueran necesarios), `app/modules/ordenes/repository.py` (métodos de lectura para stock/vehículo/orden si fueran necesarios), `app/modules/repuestos/repository.py` (lectura y descuento de stock si fuera necesario), `main.py` (montaje de rutas, ya existe `router_protegido`).
- **Tests**: `test/ordenes/` extendida con casos de transición, 409 por stock insuficiente sin escrituras, 403 antes que 409 en cancelar, terminar orden ajena → 403.
- **Dependencias**: C-07 (ordenes-crud) completa ✅; C-04 (clientes-vehiculos, DELETE /vehiculos/{id} con punto de extensión `es_final`) ✅; C-05 (repuestos-stock, `movimiento_stock`) ✅; C-03 (usuario_actual, requiere_rol) ✅. Habilita C-11 (evidencia de entrega, caso de stock insuficiente).

## Alcance explícito

**Dentro:** las tres transiciones de estado con historial, la transacción crítica de stock con rollback total, la notificación post-commit en BackgroundTasks, el desbloqueo de `DELETE /vehiculos/{id}` vía `es_final`, y la suite de tests correspondiente.

**Fuera (y por qué):**
- **Disparadores de sólo agregado → C-09.** C-08 escribe filas en `historial_estado_orden` y `movimiento_stock`, pero la función y disparadores que rechazan UPDATE/DELETE son de C-09 (RN-15).
- **Seed inicial del catálogo y de las órdenes → C-10.** Los estados y los datos de prueba (incluida la orden EN_REPARACION con stock insuficiente) los carga `seed.py`.
- **Consolidación de migraciones y evidencias HTTP → C-11.** C-08 no toca `migrations/versions/` más allá de su migración de desarrollo.
- **Edición o borrado de órdenes.** La consigna no define `PATCH /ordenes/{id}` ni `DELETE /ordenes/{id}`; el ciclo de vida se cubre solo con las transiciones de C-08.
