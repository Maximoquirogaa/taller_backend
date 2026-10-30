# Proposal: Repuestos y Stock (c-05-repuestos-stock)

## Why
El taller mecánico requiere gestionar el catálogo de piezas y repuestos, controlar el stock mediante movimientos auditables (alta inicial, reposición y salidas por órdenes de trabajo) y registrar el historial de variaciones de precio en transacciones atómicas de sólo agregado, cumpliendo con las reglas de negocio RN-01, RN-14, RN-16, RN-18 y RN-20.

## What Changes
- Crear modelos SQLModel `Repuesto`, `MovimientoStock` y `HistorialPrecioRepuesto` en `app/modules/repuestos/models.py`.
- Configurar restricciones de integridad en base de datos: `precio > 0` (NUMERIC 10,2), `stock >= 0` (CHECK), `MovimientoStock.cantidad > 0` (CHECK), `HistorialPrecioRepuesto.precio_nuevo > precio_anterior` y `precio_anterior > 0` (CHECK).
- Configurar **índice único parcial** sobre `codigo` en `repuesto` (`WHERE borrado_en IS NULL`, RN-01), permitiendo re-registrar un código tras una baja lógica.
- Implementar repositorios específicos `RepositorioRepuestos` (hereda `SoftDeleteRepository`), `RepositorioMovimientosStock` y `RepositorioHistorialPrecios` (heredan `BaseRepository`).
- Implementar Unit of Work `UoWRepuestos` para orquestar transacciones atómicas multi-tabla.
- Endpoint `GET /repuestos?q=&page=&size=`: catálogo con búsqueda por texto insensible a mayúsculas usando parámetros ligados (RN-18) y envoltorio paginado `{items,total,page,size,pages}` (roles ADMIN, RECEPCION, MECANICO) (US-017).
- Endpoint `POST /repuestos` (con `stock_inicial`): alta de repuesto y movimiento inicial «Stock inicial» en el mismo UoW (rol ADMIN, US-018, RN-14).
- Endpoint `PATCH /repuestos/{id}`: modificación parcial (`exclude_unset`); si cambia el precio genera línea en `historial_precio_repuesto` en la misma transacción; rechaza intentos de modificar stock directamente con 422 (rol ADMIN, US-019, RN-20, RN-14).
- Endpoint `DELETE /repuestos/{id}`: baja lógica (`borrado_en = now()`) (rol ADMIN, US-020, RN-16).
- Endpoint `POST /repuestos/{id}/reponer`: único punto de incremento directo de stock con registro del movimiento en un solo UoW (rol ADMIN, US-021, RN-14).
- Endpoint `GET /repuestos/{id}/movimientos`: listado cronológico de movimientos del repuesto (roles ADMIN, RECEPCION, MECANICO, US-022).
- Endpoint `GET /repuestos/{id}/precios`: listado cronológico del historial de precios (roles ADMIN, RECEPCION, MECANICO, US-022).
- Migración incremental de desarrollo `004_repuestos_stock` en Alembic registrando los modelos en `migrations/env.py`.
- Montar el router de repuestos en `router_protegido` en `main.py` (hereda la validación de cambio obligatorio de contraseña, DD-10).

## Capabilities

### New Capabilities
- `repuestos-stock`: Catálogo de repuestos con control de stock basado exclusivamente en movimientos, historial de precios auditable en transacciones atómicas, borrado lógico con unicidad parcial y consultas seguras con paginación.

### Modified Capabilities
- *(none)*

## Impact
- **Base de datos**: Nuevas tablas `repuesto`, `movimiento_stock` e `historial_precio_repuesto` en PostgreSQL; claves foráneas indexadas; índice único parcial en `codigo` activo.
- **API**: Nuevas rutas bajo `/repuestos`. Requieren autenticación vía cookie HttpOnly (`access_token`).
- **Dependencias**: Se integran los repositorios de repuestos en el UoW (`app/core/unit_of_work.py` y `app/modules/repuestos/unit_of_work.py`).
