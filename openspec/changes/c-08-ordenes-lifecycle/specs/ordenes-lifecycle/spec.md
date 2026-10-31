# Spec Delta

## Purpose

Define la máquina de estados de las órdenes de trabajo (iniciar, terminar, cancelar) con su transacción crítica de descuento de stock, historial de estados por transición y permisos diferenciados por rol y relación con la orden.

## ADDED Requirements

### Requirement: Iniciar reparación de una orden pendiente
La API SHALL exponer `POST /ordenes/{id}/iniciar` que transicione una orden de PENDIENTE a EN_REPARACION, asigne `mecanico_id` al usuario autenticado y agregue una línea de historial; solo accesible al rol MECANICO vigente.

#### Scenario: Mecánico inicia una orden PENDIENTE
- **WHEN** un usuario con rol MECANICO vigente invoca `POST /ordenes/{id}/iniciar` sobre una orden en estado PENDIENTE sin mecánico asignado
- **THEN** la respuesta es 200, el estado de la orden es EN_REPARACION, `mecanico_id` es el id del usuario autenticado y existe una línea de historial PENDIENTE → EN_REPARACION con ese `usuario_id`

#### Scenario: Mecánico intenta iniciar una orden ya EN_REPARACION
- **WHEN** un usuario con rol MECANICO vigente invoca `POST /ordenes/{id}/iniciar` sobre una orden cuyo estado ya es EN_REPARACION
- **THEN** la respuesta es 409, el estado permanece EN_REPARACION y no se agrega ninguna línea de historial nueva

#### Scenario: Usuario sin rol MECANICO intenta iniciar
- **WHEN** un usuario sin rol MECANICO vigente invoca `POST /ordenes/{id}/iniciar`
- **THEN** la respuesta es 403 y el estado de la orden no cambia

#### Scenario: Orden inexistente al iniciar
- **WHEN** se invoca `POST /ordenes/{id}/iniciar` con un `id` de orden que no existe
- **THEN** la respuesta es 404

### Requirement: Terminar reparación con descuento de stock atómico
La API SHALL exponer `POST /ordenes/{id}/terminar` que, en una sola transacción del UoW, verifique el permiso (mecánico asignado o ADMIN) y el estado EN_REPARACION, chequee el stock de cada ítem, descuente el stock y cree filas de `movimiento_stock` (salida), pase la orden a TERMINADA con historial y, tras el commit, lance una notificación en `BackgroundTasks`; si algún ítem no tiene stock suficiente, se revierte todo sin escrituras parciales (409).

#### Scenario: Mecánico asignado termina una orden con stock suficiente
- **WHEN** el mecánico asignado a una orden EN_REPARACION invoca `POST /ordenes/{id}/terminar` y todos los ítems tienen stock >= cantidad
- **THEN** la respuesta es 200, el estado es TERMINADA, el stock de cada repuesto se reduce por la cantidad del ítem, existe una fila de `movimiento_stock` por salida por ítem con `orden_id` y `motivo` de salida, existe una línea de historial EN_REPARACION → TERMINADA y se ejecuta la notificación de `BackgroundTasks`

#### Scenario: ADMIN termina una orden ajena con stock suficiente
- **WHEN** un usuario con rol ADMIN vigente (no asignado a la orden) invoca `POST /ordenes/{id}/terminar` sobre una orden EN_REPARACION con stock suficiente
- **THEN** la respuesta es 200 y la orden pasa a TERMINADA con descuento de stock y movimientos

#### Scenario: Terminar con stock insuficiente revierte todo (ejercicio C-11)
- **WHEN** se invoca `POST /ordenes/{id}/terminar` sobre una orden EN_REPARACION con al menos un ítem cuyo stock es menor que la cantidad pedida
- **THEN** la respuesta es 409, el stock de todos los repuestos permanece sin cambios, no existe ninguna fila nueva de `movimiento_stock`, no existe ninguna línea nueva de historial y el estado sigue siendo EN_REPARACION

#### Scenario: Usuario que no es el mecánico asignado ni ADMIN intenta terminar
- **WHEN** un usuario sin rol ADMIN y no asignado como mecánico de la orden invoca `POST /ordenes/{id}/terminar`
- **THEN** la respuesta es 403 y no se evalúa el estado ni se descuenta stock

#### Scenario: Orden inexistente al terminar
- **WHEN** se invoca `POST /ordenes/{id}/terminar` con un `id` de orden que no existe
- **THEN** la respuesta es 404

### Requirement: Cancelar una orden pendiente con permiso antes que estado
La API SHALL exponer `POST /ordenes/{id}/cancelar` (sin `requiere_rol` simple en la ruta) que evalúe primero la relación del usuario con la orden (personal del taller o dueño del vehículo) y, solo entonces, si el estado es PENDIENTE; PENDIENTE → CANCELADA con línea de historial; 403 por falta de relación antes que 409 por estado no permitido.

#### Scenario: RECEPCION cancela una orden PENDIENTE
- **WHEN** un usuario con rol RECEPCION vigente invoca `POST /ordenes/{id}/cancelar` sobre una orden PENDIENTE
- **THEN** la respuesta es 200, el estado es CANCELADA y existe una línea de historial PENDIENTE → CANCELADA

#### Scenario: Dueño del vehículo cancela su orden PENDIENTE
- **WHEN** el dueño del vehículo de una orden PENDIENTE invoca `POST /ordenes/{id}/cancelar`
- **THEN** la respuesta es 200, el estado es CANCELADA y existe una línea de historial PENDIENTE → CANCELADA

#### Scenario: Usuario ajeno intenta cancelar una orden PENDIENTE
- **WHEN** un usuario sin relación con la orden (ni personal ni dueño del vehículo) invoca `POST /ordenes/{id}/cancelar` sobre una orden PENDIENTE
- **THEN** la respuesta es 403 (no 409) y el estado permanece PENDIENTE

#### Scenario: Intentar cancelar una orden ya TERMINADA
- **WHEN** un usuario con relación válida invoca `POST /ordenes/{id}/cancelar` sobre una orden TERMINADA
- **THEN** la respuesta es 409 y el estado permanece TERMINADA

#### Scenario: Orden inexistente al cancelar
- **WHEN** se invoca `POST /ordenes/{id}/cancelar` con un `id` de orden que no existe
- **THEN** la respuesta es 404

### Requirement: Baja de vehículo bloqueada por órdenes abiertas (RN-16)
La ruta `DELETE /vehiculos/{id}` SHALL rechazar con 409 cuando el vehículo tiene órdenes en estado no final según `es_final` del catálogo `estado_orden`, y SHALL permitir la baja lógica cuando no hay órdenes abiertas.

#### Scenario: Vehículo con orden PENDIENTE no se da de baja
- **WHEN** se invoca `DELETE /vehiculos/{id}` sobre un vehículo que tiene al menos una orden en estado PENDIENTE o EN_REPARACION
- **THEN** la respuesta es 409 y el vehículo sigue vigente (`borrado_en` nulo)

#### Scenario: Vehículo sin órdenes abiertas se da de baja
- **WHEN** se invoca `DELETE /vehiculos/{id}` sobre un vehículo sin órdenes o con solo órdenes TERMINADA/CANCELADA
- **THEN** la respuesta es 204 y `borrado_en` se establece al instante actual
