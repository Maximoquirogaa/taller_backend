# ordenes-crud Specification

## Purpose
Permitir al taller registrar el ingreso de un vehículo como orden de trabajo, consultar el tablero y el detalle de cada orden, conocer el catálogo de estados y que cada cliente vea únicamente las órdenes de sus propios vehículos.

## Requirements

### Requirement: Apertura de orden con precios copiados y total del servidor

La API SHALL exponer `POST /ordenes` (sólo RECEPCION o ADMIN vigente) que cree una orden en estado PENDIENTE para un vehículo vigente, con al menos un ítem. El servidor SHALL copiar el precio unitario vigente de cada repuesto activo y calcular el total; el cuerpo del pedido MUST NOT aceptar precio, total ni estado. La orden, sus ítems y la línea de historial «nulo → PENDIENTE» SHALL persistirse en una sola transacción.

#### Scenario: Apertura exitosa

- **WHEN** un RECEPCION o ADMIN envía `vehiculo_id`, `falla` e `items` con repuestos activos y cantidades positivas
- **THEN** responde 201 con la orden creada en estado PENDIENTE, cada ítem con el `precio_unitario` copiado del repuesto, el `total` igual a la suma de `precio_unitario × cantidad`, y una línea de historial «nulo → PENDIENTE» del usuario que abrió la orden

#### Scenario: Precio y total no viajan en el cuerpo

- **WHEN** el cuerpo incluye `precio_unitario`, `total`, `estado` o cualquier campo no declarado
- **THEN** responde 422 sin crear la orden, aunque los valores enviados coincidan con los calculados por el servidor

#### Scenario: Catálogo de estados vacío

- **WHEN** un RECEPCION o ADMIN intenta abrir una orden y la tabla de estados no tiene filas
- **THEN** responde 409 con mensaje propio y no queda ninguna orden, ítem ni línea de historial

#### Scenario: Repuesto inexistente o dado de baja

- **WHEN** uno de los `repuesto_id` enviados no existe o tiene baja lógica
- **THEN** responde 409 con mensaje propio y no queda ninguna escritura parcial

#### Scenario: Vehículo inexistente o dado de baja

- **WHEN** el `vehiculo_id` enviado no existe o tiene baja lógica
- **THEN** responde 404 con mensaje propio y no queda ninguna escritura

#### Scenario: Orden sin ítems o cantidad inválida

- **WHEN** `items` viene vacío, falta el campo o alguna `cantidad` no es un entero mayor a cero
- **THEN** responde 422 sin crear la orden

#### Scenario: Repuesto repetido en la misma orden

- **WHEN** el cuerpo repite el mismo `repuesto_id` en dos ítems
- **THEN** responde 409 con mensaje propio, sin crear la orden ni sus ítems

#### Scenario: Apertura por un rol no autorizado

- **WHEN** un usuario con rol MECANICO o CLIENTE intenta abrir una orden
- **THEN** responde 403 sin crear la orden, y sin sesión válida responde 401

### Requirement: Catálogo de estados de sólo lectura

La API SHALL exponer `GET /estados-orden` para cualquier usuario autenticado, devolviendo el catálogo ordenado por `posicion` con su `codigo`, `descripcion`, `posicion` y `es_final`. El catálogo MUST NOT editarse desde la API y un catálogo vacío SHALL devolver una lista vacía con 200.

#### Scenario: Catálogo ordenado y finales marcados

- **WHEN** un usuario autenticado consulta `/estados-orden` con el catálogo cargado
- **THEN** responde 200 con los estados en orden ascendente de `posicion` y el campo `es_final` en cada uno

#### Scenario: Catálogo vacío

- **WHEN** un usuario autenticado consulta `/estados-orden` y no hay filas
- **THEN** responde 200 con `[]`

#### Scenario: Sin sesión

- **WHEN** se consulta `/estados-orden` sin cookie válida
- **THEN** responde 401

### Requirement: Listado de órdenes con filtro por estado

La API SHALL exponer `GET /ordenes` (sólo ADMIN, RECEPCION o MECANICO) con el envoltorio `{items, total, page, size, pages}`, ordenado de la orden más reciente a la más antigua y con filtro opcional por `estado`. Un `estado` fuera del contrato o parámetros de paginación inválidos SHALL responder 422.

#### Scenario: Tablero paginado

- **WHEN** un usuario con rol habilitado consulta `/ordenes` con parámetros válidos
- **THEN** responde 200 con el envoltorio estándar, las órdenes de la página y el total contado con el mismo filtro

#### Scenario: Filtro por estado válido

- **WHEN** se consulta `/ordenes?estado=PENDIENTE`
- **THEN** responde 200 sólo con las órdenes en ese estado y un `total` coherente con el filtro

#### Scenario: Estado fuera del contrato

- **WHEN** se consulta `/ordenes?estado=INVENTADO`
- **THEN** responde 422 sin consultar la tabla de órdenes

#### Scenario: Paginación inválida

- **WHEN** se consulta `/ordenes?page=0` o `/ordenes?size=500`
- **THEN** responde 422 con el mensaje propio de paginación

#### Scenario: Cliente sin permiso de tablero

- **WHEN** un usuario con rol CLIENTE consulta `/ordenes`
- **THEN** responde 403

### Requirement: Detalle de orden con consultas fijas

La API SHALL exponer `GET /ordenes/{id}` para personal del taller y para el dueño del vehículo, devolviendo la orden con vehículo, cliente, ítems con su repuesto e historial de estados. La cantidad de consultas SHALL ser independiente de la cantidad de ítems. Una orden ajena al cliente SHALL responder 403 y una orden inexistente 404.

#### Scenario: Detalle completo para personal del taller

- **WHEN** un ADMIN, RECEPCION o MECANICO consulta una orden existente
- **THEN** responde 200 con vehículo, cliente, estado, falla, total, ítems con repuesto y subtotal, e historial ordenado cronológicamente

#### Scenario: Detalle del dueño

- **WHEN** un usuario CLIENTE consulta una orden de un vehículo de su propia ficha de cliente
- **THEN** responde 200 con el mismo detalle

#### Scenario: Consultas fijas sin N+1

- **WHEN** se consultan dos órdenes equivalentes, una con 2 ítems y otra con 4 ítems
- **THEN** la cantidad de sentencias SELECT ejecutadas para armar el detalle es la misma en ambos casos

#### Scenario: Orden de otro dueño

- **WHEN** un usuario CLIENTE consulta una orden de un vehículo que pertenece a otra ficha de cliente
- **THEN** responde 403 con mensaje propio y no expone datos de la orden

#### Scenario: Orden inexistente

- **WHEN** se consulta un `id` de orden que no existe
- **THEN** responde 404 con mensaje propio

### Requirement: Consulta de órdenes propias

La API SHALL exponer `GET /mis-ordenes` para cualquier usuario autenticado, devolviendo paginadas únicamente las órdenes de los vehículos del cliente vinculado a ese usuario. Un usuario sin ficha de cliente SHALL recibir una página vacía con 200.

#### Scenario: Cliente con vehículos y órdenes

- **WHEN** un usuario CLIENTE vinculado a una ficha consulta `/mis-ordenes`
- **THEN** responde 200 con el envoltorio estándar y sólo las órdenes de sus vehículos

#### Scenario: Aislamiento entre clientes

- **WHEN** dos clientes tienen órdenes y uno consulta `/mis-ordenes`
- **THEN** no aparece ninguna orden del otro cliente y el `total` refleja sólo las propias

#### Scenario: Usuario sin ficha de cliente

- **WHEN** un usuario autenticado sin ficha de cliente consulta `/mis-ordenes`
- **THEN** responde 200 con `items` vacío, `total` 0 y `pages` 1

#### Scenario: Sin sesión

- **WHEN** se consulta `/mis-ordenes` sin cookie válida
- **THEN** responde 401

### Requirement: Errores controlados sin filtrar la base

Ninguna entrada inválida de las rutas de órdenes SHALL terminar en 500. Los conflictos de unicidad o de referencia SHALL traducirse a 409 y los mensajes de error MUST NOT incluir nombres de tablas, columnas, restricciones ni trazas de PostgreSQL.

#### Scenario: Carrera de repuesto repetido

- **WHEN** dos pedidos simultáneos intentan crear órdenes con el mismo repuesto y la restricción única de composición rechaza uno
- **THEN** el rechazado responde 409 con mensaje propio, sin texto de la base

#### Scenario: Entrada inválida no produce 500

- **WHEN** cualquier ruta de órdenes recibe un tipo de dato incorrecto o un identificador no numérico
- **THEN** responde 422 o 404 según corresponda, nunca 500

#### Scenario: Mensaje de error sin detalles internos

- **WHEN** una operación de órdenes falla por una restricción de la base
- **THEN** el cuerpo del error contiene un mensaje propio del dominio y ningún nombre de tabla, columna o restricción
