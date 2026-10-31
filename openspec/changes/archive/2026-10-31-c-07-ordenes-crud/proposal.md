# Proposal: Órdenes de Trabajo — CRUD de Apertura, Listado y Detalle (c-07-ordenes-crud)

## Why

C-04 y C-05 dejaron clientes, vehículos y repuestos con stock auditable, pero el taller todavía no puede registrar el ingreso de un vehículo: no existen las tablas de órdenes ni el catálogo de estados, y la API no tiene forma de abrir una orden, listar el tablero ni consultar su detalle. Sin esta capa, RN-10 (orden nace PENDIENTE con ítems y precios copiados) y RN-19 (estados como catálogo consultable) no tienen implementación, y C-08 (máquina de estados y descuento de stock) no tiene sobre qué operar.

## What Changes

- Nuevos modelos SQLModel en `app/modules/ordenes/models.py`: `EstadoOrden` (PK `codigo`, `posicion` UNIQUE, `es_final`), `OrdenTrabajo`, `ItemOrden` (UNIQUE `(orden_id, repuesto_id)` y `precio_unitario` copiado del repuesto, RN-10) e `HistorialEstadoOrden`.
- Repositorio de `estado_orden` de **sólo lectura**, que no hereda de `BaseRepository` y no expone `add`/`update`/`delete` (RN-19).
- `POST /ordenes` (solo RECEPCION/ADMIN): contrato `vehiculo_id`, `falla`, `items[{repuesto_id, cantidad}]` —sin precio, total ni estado—; catálogo vacío → 409; precios unitarios y total calculados por el servidor; historial nulo → PENDIENTE en el mismo UoW (US-023, RN-10, RN-19).
- `GET /ordenes?estado=&page=&size=`: tablero paginado con el envoltorio estándar; un estado fuera del contrato responde 422 (US-024).
- `GET /ordenes/{id}`: detalle con vehículo, cliente, ítems (con repuesto) e historial, con un **número fijo de consultas** independiente de la cantidad de ítems (ejercicio C-15: 2 vs 4 ítems); orden inexistente → 404; dueño ajeno → 403 (US-025, RN-17).
- `GET /estados-orden`: catálogo ordenado por `posicion`, con los estados finales marcados (US-029, RN-19).
- `GET /mis-ordenes`: órdenes de los vehículos del cliente vinculado al usuario autenticado, paginadas (US-030, RN-17).
- Migración de **desarrollo** `005_ordenes_crud` (autogenerate, head sobre `004_repuestos_stock`) con las cuatro tablas y el catálogo **vacío** (DD-01). C-11 la consolida en `001`/`002`; no sobrevive a la entrega.
- Suite `test/ordenes/` (`conftest.py`, `test_models.py`, `test_repository.py`, `test_router.py`) contra PostgreSQL `taller_test`, con catálogo insertado por fixture (la migración no lo carga).

## Alcance explícito

**Dentro:** modelos y esquema de las cuatro tablas; apertura, listado, detalle, catálogo de estados y órdenes propias; migración 005 de desarrollo; tests de contrato, persistencia y consultas fijas.

**Fuera (y por qué):**

- **Máquina de estados y transacción de stock → C-08.** `iniciar`, `terminar` y `cancelar` cambian el estado de la orden y, al terminar, descuentan stock con movimientos en un único UoW (RN-11, RN-12, RN-13). C-07 sólo crea la orden en PENDIENTE y su primera línea de historial; no implementa transiciones.
- **Disparadores de sólo agregado → C-09.** La migración `005` crea las tablas, pero la función y los disparadores que rechazan UPDATE/DELETE sobre `historial_estado_orden` (y las otras dos tablas append-only) son la migración escrita a mano de C-09 (RN-15).
- **Seed inicial del catálogo → C-10.** Por DD-01 la migración deja `estado_orden` vacía; los cuatro estados (PENDIENTE, EN_REPARACION, TERMINADA, CANCELADA) los carga `seed.py`. En C-07 los tests insertan el catálogo en una fixture y el 409 por catálogo vacío es precisamente el comportamiento observable de esa decisión.
- **Edición o borrado de órdenes.** La consigna no define `PATCH /ordenes/{id}` ni `DELETE /ordenes/{id}`; el ciclo de vida se cubre con las transiciones de C-08.
- **Consolidación de migraciones y evidencias HTTP → C-11.** C-07 no toca `migrations/versions/` más allá de agregar `005`.

## Capabilities

### New Capabilities

- `ordenes-crud`: apertura de órdenes de trabajo con composición de repuestos y precios copiados por el servidor, listado filtrado por estado, detalle enriquecido con consultas fijas, catálogo de estados de sólo lectura y consulta de las órdenes propias del cliente.

### Modified Capabilities

- *(ninguna)*. C-07 no cambia el comportamiento observable de `clientes-vehiculos`, `repuestos-stock`, `pagination` ni `user-auth`: reutiliza sus contratos y sólo agrega una lectura masiva de repuestos activos por id (detalle de implementación, sin cambio de garantías).

## Impact

- **Base de datos**: migración de desarrollo `005_ordenes_crud` con `estado_orden` (vacía), `orden_trabajo`, `item_orden` e `historial_estado_orden`; FKs indexadas, CHECK de `cantidad`/`precio`/`total`, UNIQUE `(orden_id, repuesto_id)` y `posicion` UNIQUE. `env.py` suma el import del módulo.
- **API**: cinco rutas nuevas bajo `router_protegido` (`POST /ordenes`, `GET /ordenes`, `GET /ordenes/{id}`, `GET /estados-orden`, `GET /mis-ordenes`); 401 sin sesión; 403 por rol o por detalle ajeno; 404 por orden o vehículo inexistente; 409 por catálogo vacío o repuesto no disponible; 422 por contrato.
- **Código**: `app/modules/ordenes/{models,schemas,repository,service,unit_of_work,router}.py`, `app/modules/repuestos/repository.py` (método aditivo `get_activos_por_ids`), `migrations/versions/005_ordenes_crud.py` y `migrations/env.py`.
- **Tests**: `test/ordenes/` nuevo; `test/conftest.py` y los `conftest.py` de módulos suman las tablas de órdenes al truncado (los de órdenes con `estado_orden` incluido).
- **Dependencias**: C-04 (clientes/vehículos), C-05 (repuestos y stock), C-03 (`usuario_actual`, `requiere_rol`). Habilita C-08, C-09 y C-10.
