# Design: Repuestos y Stock (c-05-repuestos-stock)

## Context
Ver `proposal.md` y `specs/repuestos-stock/spec.md`. El taller mecánico requiere gestionar el inventario de repuestos con trazabilidad auditable. Tras C-04 (clientes y vehículos), C-05 construye la persistencia y servicios para piezas, movimientos e historial de precios, requisito indispensable para el posterior desarrollo de órdenes de trabajo (C-07).

## Goals / Non-Goals

**Goals:**
- Implementar modelos SQLModel `Repuesto`, `MovimientoStock` y `HistorialPrecioRepuesto` con restricciones en PostgreSQL (`NUMERIC(10,2)`, CHECKs, `timestamptz`).
- Garantizar unicidad de códigos de repuesto entre registros vigentes mediante índice único parcial `(codigo) WHERE borrado_en IS NULL` (RN-01).
- Centralizar las modificaciones de stock exclusivamente a través de la creación de `MovimientoStock` (alta inicial, reposición) en transacciones atómicas dentro de `UoWRepuestos` (RN-14).
- Registrar automáticamente cada alteración de precio en `HistorialPrecioRepuesto` en la misma transacción (RN-20).
- Exponer endpoints seguros con control RBAC por rol en base de datos (`requiere_rol`), paginación envolvente (`construir_pagina`) y búsqueda insensible a mayúsculas con parámetros ligados (RN-18).
- Proveer migración incremental de desarrollo `004_repuestos_stock` y suite completa de tests de repositorio, servicios y router.

**Non-Goals:**
- Descuento de stock por terminación de órdenes (corresponde a C-08; en C-05 se provee el soporte en el modelo para `orden_id` nulo).
- Restricciones de base de datos tipo triggers para sólo agregado (corresponde a C-09; en C-05 las tablas `movimiento_stock` e `historial_precio_repuesto` son manipuladas como append-only por convención y arquitectura).

## Decisions

### 1. Modelado de datos y unicidad parcial (RN-01, RN-14, RN-20)
- **Decisión**:
  - `Repuesto`: campos `codigo`, `descripcion`, `precio` (Decimal, `NUMERIC(10,2)`, CHECK `precio > 0`), `stock` (CHECK `stock >= 0`, default 0), `borrado_en` (`timestamptz` nullable). Índice único parcial `ix_repuesto_codigo_activo` en `(codigo) WHERE borrado_en IS NULL`.
  - `MovimientoStock`: campos `repuesto_id` (FK indexada), `orden_id` (int nullable indexado), `usuario_id` (FK indexada opcional), `cantidad` (CHECK `cantidad > 0`), `motivo` (str max 120), `cuando` (`timestamptz`).
  - `HistorialPrecioRepuesto`: campos `repuesto_id` (FK indexada), `usuario_id` (FK indexada opcional), `precio_anterior` (CHECK `> 0`), `precio_nuevo` (CHECK `> 0`), restricción CHECK `precio_nuevo > precio_anterior`, `cuando` (`timestamptz`).
- **Alternativas**: Controlar el código único solo en la capa de aplicación. Se descartó porque no previene carreras concurrentes y la consigna exige garantía a nivel esquema.

### 2. Transaccionalidad atómica y Unit of Work
- **Decisión**: Se implementa `UoWRepuestos` heredando de `UnitOfWork` base, exponiendo `repuestos`, `movimientos` e `historial_precios`.
  - En alta de repuesto: `repuestos.add(repuesto)` + `movimientos.add(MovimientoStock(..., cantidad=stock_inicial, motivo="Stock inicial"))` en el mismo context manager.
  - En reposición: `repuesto.stock += cantidad` + `movimientos.add(MovimientoStock(..., cantidad=cantidad, motivo="Reposición"))` en el mismo context manager.
  - En modificación de precio: si `precio_nuevo != repuesto.precio`, se actualiza `repuesto.precio` y se agrega `HistorialPrecioRepuesto(..., precio_anterior=anterior, precio_nuevo=nuevo)` en el mismo context manager.
- **Alternativas**: Actualizar stock y registrar movimiento en transacciones separadas. Descartado por violar la atomicidad y la regla dura del proyecto.

### 3. Búsqueda con parámetros ligados y paginación (US-017, RN-18)
- **Decisión**: La búsqueda en `GET /repuestos?q=` se implementa en `RepositorioRepuestos` usando `ilike` con parámetros ligados de SQLAlchemy sobre `codigo` y `descripcion`, filtrando `borrado_en IS NULL`. Se devuelven los resultados mediante `construir_pagina(items, total, page, size)`.
- **Mitigación**: Cualquier input malicioso en `q` no altera el árbol AST de la consulta ni produce error 500, respondiendo lista vacía y total 0.

### 4. Prohibición estricta de edición de stock en PATCH (RN-14)
- **Decisión**: El esquema `EntradaActualizarRepuesto` tiene `extra="forbid"` y no define el campo `stock`. Si un cliente envía `stock`, FastAPI responde 422 automáticamente. Adicionalmente, el servicio valida que solo se admitan cambios de `descripcion` y/o `precio`.

## Risks / Trade-offs

- **[Riesgo: Disminución de precio rechazada por CHECK `precio_nuevo > precio_anterior`]** → **Mitigación**: La especificación y modelo de datos del enunciado establecen explícitamente `CHECK precio_nuevo > precio_anterior` para el historial. En caso de que se intente registrar un precio menor o igual al anterior, la transacción se cancela y se captura limpiamente devolviendo 422/409 sin exponer errores internos de la base (RN-18).
- **[Riesgo: Consulta de repuestos dados de baja]** → **Mitigación**: `SoftDeleteRepository` filtra por defecto `borrado_en IS NULL` en listados y búsquedas de catálogo.
