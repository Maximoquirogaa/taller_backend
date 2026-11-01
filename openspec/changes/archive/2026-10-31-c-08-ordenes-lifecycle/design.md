# Design: Órdenes de Trabajo — Lifecycle y Transición de Estados

## Context

C-07 ya creó `app/modules/ordenes/` con `models.py` (`EstadoOrden`, `OrdenTrabajo`, `ItemOrden`, `HistorialEstadoOrden`), `repository.py` (repositorios de solo lectura para el catálogo y de `flush` para orden/ítems/historial), `service.py` (`crear_orden`, `obtener_detalle`, `listar_estados`, `listar_mis_ordenes`), `router.py` (cinco rutas bajo `router_protegido`), `schemas.py` y `unit_of_work.py` (`UoWOrdenes` que expone `ordenes`, `items`, `historial`, `estados`, `vehiculos`, `repuestos`, `clientes`). El UoW base (`app/core/unit_of_work.py`) hace `commit` al salir sin excepción y `rollback` al salir con excepción, propagándola. `app/core/dependencies.py` provee `usuario_actual` (cookie HttpOnly, roles vigentes de la base por petición) y `requiere_rol(...)` (403 si el rol no está vigente). El catálogo `estado_orden` se crea vacío por la migración 005 (DD-01); C-10 lo puebla. No hay `create_all`: el esquema solo viene de `alembic upgrade head`. Véase proposal.md - Why para la motivación.

## Goals / Non-Goals

**Goals:**
- Tres nuevas rutas `POST /ordenes/{id}/iniciar`, `POST /ordenes/{id}/terminar`, `POST /ordenes/{id}/cancelar` sobre `router_protegido`.
- `iniciar`: solo MECANICO (`requiere_rol("MECANICO")`), PENDIENTE → EN_REPARACION, `mecanico_id` = usuario actual, línea de historial, 409 si el estado no lo permite.
- `terminar`: sin `requiere_rol`; servicio evalúa permiso (mecánico asignado o ADMIN → 403) y estado (EN_REPARACION → 409); un solo UoW con chequeo de stock de todos los ítems antes de escribir; stock insuficiente → 409 con rollback total (sin escrituras parciales); descuento de stock + `movimiento_stock` (salida) + estado TERMINADA + historial; notificación post-commit en `BackgroundTasks` (`asyncio.sleep(0.5)` + log).
- `cancelar`: sin `requiere_rol`; servicio evalúa relación personal/dueño del vehículo (403) antes que estado PENDIENTE (409); PENDIENTE → CANCELADA + historial.
- `DELETE /vehiculos/{id}` (C-04) realmente rechaza con 409 si hay órdenes abiertas, leyendo `es_final` del catálogo `estado_orden` (RN-16).
- Excepciones de dominio traducidas a 409/403/404 en el router con `from exc`, sin exponer nombres de tablas, columnas, restricciones ni trazas de PostgreSQL (RN-18).
- Strict TDD: test primero (RED), código mínimo para pasar (GREEN), ≥2 casos de triangulación por comportamiento, REFACtor verde. Sin `create_all`; esquema desde `alembic upgrade head`.

**Non-Goals:**
- Disparadores de solo agregado sobre `historial_estado_orden`/`movimiento_stock` (C-09, RN-15).
- Seed inicial de estados y órdenes (C-10).
- Consolidación de migraciones a `001`/`002` (C-11).
- Edición o borrado de órdenes (`PATCH`/`DELETE /ordenes/{id}`); el ciclo de vida se cubre solo con las tres transiciones.
- Control de concurrencia para el descuento de stock (DD-11 lo acepta como tema de próxima clase).

## Decisions

### D1 — Tres funciones de servicio, cada una con su propio `async with UoWOrdenes(session)`
- **Decisión**: `iniciar_orden`, `terminar_orden` y `cancelar_orden` viven en `app/modules/ordenes/service.py`; cada una abre su propio `async with UoWOrdenes(session)` que confirma al salir o revierte ante excepción.
- **Alternativas**: una sola función de servicio con un parámetro de acción; lógica de transición en el router.
- **Rationale**: sigue el patrón de `crear_orden` (C-07) — una operación de negocio = una transacción (D10 del UoW); separa la lógica de negocio del transporte HTTP y permite probar el servicio sin el router.

### D2 — Ruta `terminar` sin `requiere_rol`; el servicio evalúa el permiso
- **Decisión**: `POST /ordenes/{id}/terminar` no lleva `Depends(requiere_rol(...))`; recibe `usuario: UsuarioAutenticado` vía `usuario_actual` y el servicio comprueba `usuario.roles_vigentes` (ADMIN) o `orden.mecanico_id == usuario.id`; si ninguno, lanza `OrdenAjena` → 403.
- **Alternativas**: `requiere_rol("MECANICO", "ADMIN")` en la ruta.
- **Rationale**: RN-12/RN-13 exigen que el mecánico asignado O el ADMIN puedan terminar, y el dueño del vehículo no tiene rol de personal; `requiere_rol` rechazaría al dueño y no distingue "mecánico asignado de esta orden". La evaluación en el servicio permite 403 antes que 409.

### D3 — Ruta `cancelar` sin `requiere_rol`; relación primero, estado después
- **Decisión**: `POST /ordenes/{id}/cancelar` no lleva `requiere_rol`; el servicio comprueba primero si el usuario es staff (ADMIN/RECEPCION/MECANICO) o dueño del vehículo (403 si no) y recién después si el estado es PENDIENTE (409 si no).
- **Alternativas**: `requiere_rol` en la ruta y estado primero.
- **Rationale**: RN-12 exige "403 antes que 409" en cancelar; el dueño del vehículo no tiene rol de personal, así que `requiere_rol` lo bloquearía indebidamente con 403 antes de verificar la relación de propiedad.

### D4 — Ruta `iniciar` con `requiere_rol("MECANICO")` simple
- **Decisión**: `POST /ordenes/{id}/iniciar` lleva `Depends(requiere_rol("MECANICO"))`; el servicio solo verifica el estado (PENDIENTE → EN_REPARACION) y asigna `mecanico_id`.
- **Alternativas**: permiso evaluado en el servicio como en terminar/cancelar.
- **Rationale**: US-026 especifica rol MECANICO y `requiere_rol` es suficiente; no hay necesidad de evaluar relación con la orden porque cualquier mecánico puede tomar cualquier orden pendiente.

### D5 — Transacción de terminar: chequeo de stock de todos los ítems antes de cualquier escritura
- **Decisión**: dentro del `async with uow`, el servicio (1) verifica permiso y estado, (2) itera todos los ítems chequeando `repuesto.stock >= item.cantidad`; si alguno falla, lanza `StockInsuficiente` → el UoW revierte TODO → 409 sin escrituras parciales; si todos pasan, (3) descuenta stock (`stock -= cantidad`) + crea `movimiento_stock` (salida) por ítem, (4) cambia estado a TERMINADA + línea de historial, (5) commit implícito al salir del bloque.
- **Alternativas**: descontar ítem por ítem y revertir solo los ya hechos; verificar stock y descontar en un solo paso por ítem.
- **Rationale**: RN-13 exige "si un repuesto no alcanza, no queda ninguna de esas escrituras" (ejercicio C-11); chequear todo antes de escribir garantiza atomicidad sin escrituras parciales. DD-11 define el punto único de escritura del stock vía movimientos.

### D6 — Notificación post-commit vía `BackgroundTasks` (`asyncio.sleep(0.5)` + log)
- **Decisión**: tras el commit exitoso del UoW, el endpoint `terminar` registra una tarea en `BackgroundTasks` que hace `await asyncio.sleep(0.5)` y escribe un log; solo se ejecuta si la transacción confirmó.
- **Alternativas**: notificación dentro del UoW (antes del commit); notificación con colas externas (Redis, RabbitMQ).
- **Rationale**: la notificación no debe bloquear la respuesta ni formar parte de la transacción crítica; si el commit falla, la tarea no se programa. Colas externas son fuera de alcance (no hay dependencia de infraestructura extra).

### D7 — Traducción de excepciones de dominio a HTTPException en el router
- **Decisión**: el router captura `OrdenNoEncontrada` (404), `OrdenAjena` (403), `StockInsuficiente`/`TransicionInvalida` (409), `CatalogoEstadosVacio` (409) e `IntegrityError` (409 con mensaje genérico), todas con `from exc`; nunca se expone texto interno de PostgreSQL (RN-18).
- **Alternativas**: dejar que las excepciones de dominio suban a un manejador global.
- **Rationale**: sigue el patrón de `crear_orden_endpoint` en C-07; el router es la capa que traduce dominio a contrato HTTP.

### D8 — Lectura y descuento de stock vía repositorios existentes
- **Decisión**: `terminar_orden` lee el stock actual de cada repuesto con `uow.repuestos.get_por_id(repuesto_id)` (o método equivalente) y escribe el descuento mediante `movimiento_stock` (alta con `flush`) más la actualización de `repuesto.stock`; todo dentro del mismo UoW.
- **Alternativas**: `UPDATE repuesto SET stock = stock - cantidad WHERE id = ?` en una sola sentencia.
- **Rationale**: reutiliza los repositorios del módulo repuestos (C-05) y mantiene el stock como único punto de escritura (RN-14); el UPDATE directo es una optimización que se deja para C-11 si el docente lo pide.

## Risks / Trade-offs

- [Race condition en stock entre chequeo y descuento] → DD-11 acepta la actualización perdida sin control de concurrencia; es tema de próxima clase. Mitigación parcial: chequear todos los ítems antes de escribir reduce la ventana pero no la elimina.
- [Notificación perdida si el servidor cae entre commit y BackgroundTasks] → aceptado; la notificación es informativa (aviso), no crítica para la consistencia de la orden.
- [Stock insuficiente detectado en aplicación, no en DB] → si dos peticiones terminan la misma orden concurrentemente, ambas podrían pasar el chequeo y una fallaría en el descuento o generaría stock negativo; sin control de concurrencia (DD-11).
- [Migración de desarrollo descartable] → C-11 la elimina en la consolidación `001`/`002`; no debe tocarse `001`, `002` ni otras migraciones existentes.

## Migration Plan

1. Escribir los tests de cada transición en RED (faltan las funciones de servicio y las rutas).
2. Implementar `iniciar_orden`, `terminar_orden`, `cancelar_orden` en `service.py` y las tres rutas en `router.py` hasta el verde (GREEN).
3. Triangular con ≥2 casos por comportamiento (stock suficiente vs insuficiente, mecánico asignado vs ADMIN vs ajeno, PENDIENTE vs ya EN_REPARACION/TERMINADA/CANCELADA, orden inexistente).
4. Generar la migración de desarrollo con `alembic revision --autogenerate -m "ordenes lifecycle"` (head sobre la última de desarrollo) y verificar `alembic upgrade head` + `alembic downgrade` reproducibles.
5. Correr `python -m pytest test/ordenes -q` y la suite completa sin regresiones.
6. Auditar reglas duras: sin `commit()` en repositorios, sin `create_all`, sin `password_hash` ni datos internos en respuestas, ningún error interno en 500.
7. Rollback: revertir `service.py`, `router.py`, `schemas.py` y `unit_of_work.py` a su estado de C-07 y borrar la migración de desarrollo; C-07 sigue funcionando.

## Open Questions

- Ninguna bloqueante. El formato exacto del mensaje de error de stock insuficiente y el texto del log de la notificación se dejan para la implementación (no cambian los specs ni los tasks).
