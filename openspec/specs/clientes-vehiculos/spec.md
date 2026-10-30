# clientes-vehiculos Specification

## Purpose
Gestionar las fichas de clientes y los vehículos registrados en el taller mecánico, garantizando borrado lógico con índices únicos parciales sobre patentes vigentes, consultas precargadas eficientes y aislamiento por usuario autenticado.

## Requirements

### Requirement: Alta de cliente sin usuario
El sistema DEBE (SHALL) permitir a los roles RECEPCION y ADMIN registrar un cliente sin usuario web (`POST /clientes`). El documento debe ser único en el sistema.

#### Scenario: Alta exitosa de cliente
- **WHEN** un usuario con rol RECEPCION o ADMIN envía nombre, documento y teléfono válidos
- **THEN** el sistema registra el cliente y responde con código 201 y los datos creados

#### Scenario: Conflicto por documento duplicado
- **WHEN** se intenta registrar un cliente con un documento que ya existe en la base
- **THEN** el sistema rechaza la solicitud con código 409 y un mensaje de error descriptivo

### Requirement: Registro de vehículo asociado a cliente
El sistema DEBE (SHALL) permitir registrar un vehículo asignado a un cliente existente (`POST /clientes/{id}/vehiculos`). El año debe estar entre 1950 y 2100. La patente debe ser única entre los vehículos vigentes.

#### Scenario: Registro exitoso de vehículo
- **WHEN** se envía una patente válida y año en rango para un cliente existente
- **THEN** el sistema crea el vehículo y responde con código 201 y la información registrada

#### Scenario: Cliente no encontrado
- **WHEN** se intenta registrar un vehículo para un `cliente_id` inexistente
- **THEN** el sistema responde con código 404

#### Scenario: Patente vigente duplicada
- **WHEN** se intenta registrar un vehículo con una patente que ya pertenece a otro vehículo activo (sin borrado lógico)
- **THEN** el sistema responde con código 409 por conflicto de unicidad

#### Scenario: Año de fabricación fuera de rango
- **WHEN** se envía un año menor a 1950 o mayor a 2100
- **THEN** el sistema rechaza la petición con código 422

### Requirement: Baja lógica de vehículo
El sistema DEBE (SHALL) permitir realizar la baja lógica (`borrado_en = now()`) de un vehículo (`DELETE /vehiculos/{id}`). Se debe rechazar si el vehículo tiene órdenes de trabajo abiertas.

#### Scenario: Baja lógica exitosa
- **WHEN** RECEPCION o ADMIN solicita la baja de un vehículo sin órdenes abiertas
- **THEN** el sistema marca `borrado_en` con la fecha y hora actual y responde con código 204

#### Scenario: Re-registro de patente tras baja lógica
- **WHEN** se registra un nuevo vehículo con la patente de un vehículo dado de baja anteriormente
- **THEN** el sistema permite el registro exitosamente (índice único parcial) respondiendo 201

#### Scenario: Conflicto por órdenes de trabajo abiertas
- **WHEN** se intenta dar de baja un vehículo con órdenes no finales
- **THEN** el sistema rechaza la baja con código 409

### Requirement: Consulta de mis vehículos
El sistema DEBE (SHALL) permitir a los usuarios autenticados consultar exclusivamente los vehículos asociados a su ficha de cliente (`GET /mis-vehiculos`).

#### Scenario: Listado exclusivo de vehículos propios
- **WHEN** un cliente autenticado consulta sus vehículos
- **THEN** el sistema retorna código 200 con la lista de vehículos vigentes pertenecientes a su ficha

#### Scenario: Usuario sin ficha de cliente
- **WHEN** un usuario autenticado sin ficha de cliente asociada consulta el endpoint
- **THEN** el sistema responde con código 200 y una lista vacía o 404 según la política de ficha

### Requirement: Detalle de cliente con vehículos precargados
El sistema DEBE (SHALL) permitir a RECEPCION y ADMIN consultar la ficha de un cliente con sus vehículos asociados mediante una consulta fija sin problema N+1 (`GET /clientes/{id}`).

#### Scenario: Consulta de cliente con vehículos
- **WHEN** se solicita el detalle de un cliente existente
- **THEN** el sistema responde con código 200 incluyendo la información del cliente y la lista de sus vehículos precargados

#### Scenario: Cliente no encontrado en detalle
- **WHEN** se consulta un id de cliente que no existe
- **THEN** el sistema responde con código 404
