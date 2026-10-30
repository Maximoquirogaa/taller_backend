# Proposal: Clientes y Vehículos (c-04-clientes-vehiculos)

## Why
El taller mecánico requiere gestionar las fichas de clientes y sus vehículos asociados como base para la posterior apertura de órdenes de trabajo. Se necesita permitir altas de clientes con o sin usuario web, registrar vehículos con validación de patentes vigentes mediante borrado lógico, y permitir a los clientes autenticados consultar únicamente sus propios vehículos cumpliendo con las reglas de negocio RN-01, RN-16 y RN-17.

## What Changes
- Crear modelos SQLModel `Cliente` y `Vehiculo` en `app/modules/clientes/models.py`.
- Configurar relación 1:1 opcional entre `Usuario` y `Cliente` (`usuario_id UNIQUE` nulo en cliente).
- Configurar validaciones de dominio: `anio` de vehículo entre 1950 y 2100 (CHECK), y documento de cliente único.
- Crear **índice único parcial** sobre `patente` en `vehiculo` (`WHERE borrado_en IS NULL`, RN-01), permitiendo re-registrar una patente tras una baja lógica.
- Implementar repositorios específicos `RepositorioClientes` y `RepositorioVehiculos` heredando de la infraestructura base (`BaseRepository`, `SoftDeleteRepository`).
- Endpoint `POST /clientes`: alta de cliente sin usuario asociado (roles RECEPCION o ADMIN), validando documento no duplicado (409) (US-012).
- Endpoint `POST /clientes/{id}/vehiculos`: asociar vehículo a un cliente existente (404 si cliente no existe, 409 si la patente vigente ya existe) (US-013).
- Endpoint `DELETE /vehiculos/{id}`: baja lógica (`borrado_en = now()`), validando que no tenga órdenes abiertas (409; punto de extensión documentado hasta C-07/C-08) (US-014, RN-16).
- Endpoint `GET /mis-vehiculos`: listado exclusivo de vehículos pertenecientes al cliente asociado al usuario autenticado (US-015, RN-17).
- Endpoint `GET /clientes/{id}`: detalle de cliente con sus vehículos precargados en consulta fija sin N+1 (US-016).
- Migración de desarrollo 003 de Alembic para las tablas `cliente` y `vehiculo`.
- Montar el router de clientes en `router_protegido` en `main.py` (heredando el chequeo de cambio de contraseña obligatorio, DD-10).

## Capabilities

### New Capabilities
- `clientes-vehiculos`: Fichas de clientes (con o sin usuario web) y administración del ciclo de vida de vehículos con borrado lógico, unicidad parcial de patentes vigentes, aislamiento de acceso por titularidad (`/mis-vehiculos`) y consulta eficiente con precarga sin N+1.

### Modified Capabilities
- *(none)*

## Impact
- **Base de datos**: Nuevas tablas `cliente` y `vehiculo` en PostgreSQL; clave foránea indexada de `vehiculo.cliente_id` a `cliente.id`; índice único parcial en `patente` donde `borrado_en IS NULL`.
- **API**: Nuevas rutas protegidas bajo `/clientes`, `/vehiculos` y `/mis-vehiculos`. Requieren autenticación vía cookie HttpOnly (`access_token`).
- **Dependencias**: Se integran `RepositorioClientes` y `RepositorioVehiculos` en el UoW (`app/core/unit_of_work.py`).
