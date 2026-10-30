# Spec Delta

## Purpose
Gestionar el catálogo de repuestos del taller mecánico, asegurando la trazabilidad de stock exclusivamente mediante movimientos auditables, historial de precios transaccional y protección contra colisiones de códigos con borrado lógico.

## ADDED Requirements

### Requirement: Consulta y búsqueda de repuestos en catálogo
El sistema DEBE (SHALL) permitir consultar el catálogo de repuestos activos a los roles ADMIN, RECEPCION y MECANICO (`GET /repuestos`) con soporte de paginación envolvente (`page`, `size`) y búsqueda `q` insensible a mayúsculas usando parámetros ligados seguros (RN-18).

#### Scenario: Búsqueda exitosa paginada
- **WHEN** un usuario autorizado consulta `/repuestos` con parámetros válidos
- **THEN** el sistema responde con código 200 y el envoltorio `{items, total, page, size, pages}` conteniendo los repuestos activos

#### Scenario: Búsqueda sin coincidencias o con caracteres especiales
- **WHEN** se ingresa un parámetro `q` que no coincide con ningún repuesto o con caracteres de inyección SQL
- **THEN** el sistema responde con código 200, lista de items vacía `[]`, `total: 0` y sin provocar errores 500

#### Scenario: Parámetros de paginación inválidos
- **WHEN** se envía un parámetro `page` o `size` fuera de los rangos permitidos (ej. page < 1 o size > 100)
- **THEN** el sistema rechaza la solicitud con código 422

### Requirement: Alta de repuesto con stock inicial
El sistema DEBE (SHALL) permitir a los administradores registrar un nuevo repuesto (`POST /repuestos`) con precio mayor a cero y código único entre repuestos vigentes (RN-01), registrando atómicamente el stock inicial como un movimiento de stock «Stock inicial» en el mismo UoW (RN-14).

#### Scenario: Alta exitosa con movimiento inicial
- **WHEN** un usuario ADMIN envía código, descripción, precio positivo y stock inicial mayor o igual a cero
- **THEN** el sistema persiste el repuesto, registra el movimiento de stock inicial y responde con código 201

#### Scenario: Código vigente duplicado
- **WHEN** se intenta registrar un repuesto con un código perteneciente a otro repuesto activo
- **THEN** el sistema rechaza la operación con código 409 y mensaje descriptivo de conflicto

#### Scenario: Precio o stock inicial inválidos
- **WHEN** se envía un precio menor o igual a cero o stock inicial negativo
- **THEN** el sistema rechaza la petición con código 422

### Requirement: Actualización parcial y registro de cambio de precio
El sistema DEBE (SHALL) permitir al rol ADMIN actualizar la descripción o precio de un repuesto (`PATCH /repuestos/{id}`) usando `exclude_unset`. Si el precio es modificado, DEBE crearse una fila en `historial_precio_repuesto` en la misma transacción (RN-20). El stock NO debe ser editable por esta vía (RN-14).

#### Scenario: Cambio de precio con registro en historial
- **WHEN** un ADMIN actualiza el precio de un repuesto existente
- **THEN** el sistema actualiza el precio, crea la fila en el historial con precio anterior y nuevo en el mismo UoW, y responde con código 200

#### Scenario: Modificación de descripción sin cambio de precio
- **WHEN** se actualiza únicamente la descripción manteniendo o sin enviar el precio
- **THEN** el sistema actualiza la descripción y NO genera ninguna fila en el historial de precios

#### Scenario: Intento de modificar stock vía actualización directa
- **WHEN** el payload de actualización incluye el campo `stock`
- **THEN** el sistema rechaza la petición con código 422

#### Scenario: Permiso denegado para roles no administradores
- **WHEN** un usuario sin rol ADMIN (ej. RECEPCION o MECANICO) intenta modificar un repuesto
- **THEN** el sistema responde con código 403

### Requirement: Baja lógica de repuesto
El sistema DEBE (SHALL) permitir a un ADMIN solicitar la baja lógica de un repuesto (`DELETE /repuestos/{id}`), marcando `borrado_en` con la marca temporal actual y liberando el código para futuras altas (RN-01, RN-16).

#### Scenario: Baja lógica exitosa
- **WHEN** un ADMIN envía la solicitud de baja para un repuesto existente y activo
- **THEN** el sistema marca la baja lógica en `borrado_en` y responde con código 204

#### Scenario: Re-registro de código tras baja previa
- **WHEN** se registra un nuevo repuesto con un código de un repuesto que fue dado de baja lógica
- **THEN** el sistema permite el registro exitosamente respondiendo con código 201 (índice único parcial)

#### Scenario: Repuesto inexistente o ya dado de baja
- **WHEN** se solicita la baja de un ID de repuesto inexistente o previamente borrado
- **THEN** el sistema responde con código 404

### Requirement: Reposición de stock
El sistema DEBE (SHALL) permitir exclusivamente a un ADMIN incrementar el stock de un repuesto activo (`POST /repuestos/{id}/reponer`), sumando la cantidad especificada y registrando un movimiento de stock en una sola transacción atómica (RN-14).

#### Scenario: Reposición exitosa
- **WHEN** un ADMIN envía una cantidad positiva de reposición para un repuesto activo
- **THEN** el sistema incrementa el stock, añade el registro en `movimiento_stock` y responde con código 200

#### Scenario: Cantidad de reposición inválida
- **WHEN** se intenta reponer con una cantidad menor o igual a cero
- **THEN** el sistema rechaza la solicitud con código 422

#### Scenario: Reposición sobre repuesto inexistente o dado de baja
- **WHEN** se intenta reponer un repuesto que no existe o está dado de baja
- **THEN** el sistema responde con código 404

### Requirement: Consulta de auditoría de movimientos e historial de precios
El sistema DEBE (SHALL) permitir a los roles autorizados (ADMIN, RECEPCION, MECANICO) consultar el listado de movimientos de stock (`GET /repuestos/{id}/movimientos`) y el historial de cambios de precios (`GET /repuestos/{id}/precios`) de un repuesto.

#### Scenario: Consulta de movimientos de un repuesto
- **WHEN** un usuario autorizado consulta los movimientos de un repuesto existente
- **THEN** el sistema responde con código 200 y la lista cronológica de movimientos registrados

#### Scenario: Consulta de historial de precios
- **WHEN** un usuario autorizado consulta el historial de precios de un repuesto existente
- **THEN** el sistema responde con código 200 y la lista cronológica de variaciones de precio

#### Scenario: Repuesto inexistente para auditoría
- **WHEN** se consultan movimientos o precios de un ID de repuesto inexistente
- **THEN** el sistema responde con código 404
