# seed-inicial Specification

## Purpose
Deja la base en el estado inicial conocido del taller —catálogo de estados, usuarios por rol, clientes, vehículos, repuestos con stock, órdenes e historial— para que la aplicación y las pruebas partan siempre del mismo punto.

## Requirements

### Requirement: Estado inicial conocido del taller

La carga inicial SHALL dejar el catálogo de estados, los usuarios con sus roles, los clientes con sus vehículos, los repuestos, las órdenes y sus historiales, y SHALL registrar un evento de seguridad con actor `SISTEMA` que anuncie la carga.

#### Scenario: Carga sobre una base migrada y vacía

- **WHEN** se ejecuta `python seed.py` sobre una base recién migrada con `alembic upgrade head`
- **THEN** el catálogo `estado_orden` tiene PENDIENTE, EN_REPARACION, TERMINADA y CANCELADA (las dos últimas con `es_final` verdadero), hay 7 usuarios con sus roles vigentes, 2 clientes con 3 vehículos, 4 repuestos con stock, 2 órdenes y 1 evento de seguridad de `SISTEMA` con la acción «Carga de los datos iniciales»

#### Scenario: Orden inicial en estado PENDIENTE

- **WHEN** termina la carga
- **THEN** existe una orden en estado PENDIENTE sobre un vehículo de Laura cuya única línea de historial es «nulo → PENDIENTE», sin mecánico asignado

#### Scenario: Orden inicial en estado EN_REPARACION

- **WHEN** termina la carga
- **THEN** existe una orden en estado EN_REPARACION sobre un vehículo de Jorge, asignada a `mecanico@`, con una línea de historial «nulo → PENDIENTE» y otra «PENDIENTE → EN_REPARACION»

### Requirement: Idempotencia de la carga inicial

La carga inicial SHALL poder ejecutarse repetidas veces dejando exactamente el mismo estado, sin acumular filas ni fallar por restricciones de unicidad.

#### Scenario: Segunda ejecución consecutiva

- **WHEN** se ejecuta `python seed.py` dos veces seguidas sobre la misma base
- **THEN** la segunda ejecución termina sin error y los conteos de usuarios, clientes, vehículos, repuestos, órdenes e historial son idénticos a los de la primera

#### Scenario: Ejecución sobre una base con datos de trabajo

- **WHEN** se ejecuta `python seed.py` sobre una base que ya tenía datos cargados por el uso de la API
- **THEN** los datos previos se descartan y la base queda en el estado inicial, sin filas duplicadas de la carga anterior

### Requirement: Credenciales ficticias utilizables

La carga inicial SHALL dejar contraseñas ficticias documentadas en `seed.py` que satisfagan la política de contraseñas, y `nuevo@` SHALL quedar con el cambio de contraseña pendiente.

#### Scenario: Login con una cuenta del seed

- **WHEN** se intenta iniciar sesión con el email y la contraseña ficticia documentados para `admin@`, `recepcion@`, `mecanico@` o `cliente@`
- **THEN** la autenticación es exitosa y el usuario recibe su cookie de sesión

#### Scenario: Cuenta con cambio de contraseña pendiente

- **WHEN** se consulta el usuario `nuevo@` después de la carga
- **THEN** tiene `debe_cambiar_password` en verdadero y una asignación vigente del rol MECANICO, de modo que sus rutas protegidas responden 403 hasta que cambie la contraseña

#### Scenario: Las contraseñas ficticias no son secretos del repositorio

- **WHEN** se revisa la configuración versionada del proyecto (`.env` de ejemplo, `env.example`, README)
- **THEN** no aparece ninguna de las contraseñas del seed; sólo viven en `seed.py` como datos de demostración

### Requirement: Stock inicial registrado como movimiento

Cada repuesto cargado SHALL tener su stock inicial respaldado por una fila de `movimiento_stock` con motivo de alta, de modo que el stock nunca se escriba sin su movimiento.

#### Scenario: Stock coincide con sus movimientos

- **WHEN** termina la carga
- **THEN** para cada repuesto, el valor de `stock` es igual a la suma de las cantidades de sus `movimiento_stock` y existe al menos un movimiento de alta por repuesto

### Requirement: Caso de stock insuficiente preparado

La carga inicial SHALL dejar una orden EN_REPARACION cuyo ítem pida más unidades de las que hay en stock, para poder demostrar la reversión completa al intentar terminarla.

#### Scenario: Terminar la orden EN_REPARACION falla por stock

- **WHEN** se intenta terminar la orden EN_REPARACION de la carga inicial, que pide 4 bujías y hay 2 en stock
- **THEN** la operación responde 409, el stock de las bujías no cambia, no se agrega ningún movimiento de salida y la orden sigue en EN_REPARACION

### Requirement: Historial de precios inicial

La carga inicial SHALL dejar registrado el cambio de precio del filtro de aceite de 8000 a 8500, atribuido a un usuario administrador.

#### Scenario: Historial de precio del filtro

- **WHEN** termina la carga
- **THEN** existe una fila en `historial_precio_repuesto` para el filtro de aceite con `precio_anterior` 8000, `precio_nuevo` 8500 y `usuario_id` de un ADMIN, y el precio vigente del repuesto es 8500
