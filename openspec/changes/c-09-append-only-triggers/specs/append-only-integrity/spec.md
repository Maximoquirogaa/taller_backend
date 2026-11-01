# Spec Delta

## Purpose

Garantiza en la propia base que las tablas de historial del taller son de sólo agregado —se pueden insertar filas pero nunca modificarlas ni borrarlas— y que el catálogo de estados de la orden es cerrado por clave foránea.

## ADDED Requirements

### Requirement: UPDATE rechazado en las tablas de sólo agregado

La base SHALL rechazar toda sentencia `UPDATE` sobre `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`, sin importar el rol ni la vía de acceso, dejando la fila intacta y devolviendo un error propio que identifica la tabla protegida.

#### Scenario: UPDATE sobre historial_estado_orden

- **WHEN** se ejecuta `UPDATE historial_estado_orden SET usuario_id = NULL` sobre una fila existente
- **THEN** la base responde con el error del disparador, la transacción se aborta y la fila conserva exactamente sus valores previos

#### Scenario: UPDATE sobre movimiento_stock

- **WHEN** se ejecuta `UPDATE movimiento_stock SET cantidad = cantidad + 1` sobre una fila existente
- **THEN** la base responde con el error del disparador, la transacción se aborta y la fila conserva exactamente sus valores previos

#### Scenario: UPDATE sobre historial_precio_repuesto

- **WHEN** se ejecuta `UPDATE historial_precio_repuesto SET precio_nuevo = precio_nuevo + 100` sobre una fila existente
- **THEN** la base responde con el error del disparador, la transacción se aborta y la fila conserva exactamente sus valores previos

### Requirement: DELETE rechazado en las tablas de sólo agregado

La base SHALL rechazar toda sentencia `DELETE` sobre `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`, sin importar el rol ni la vía de acceso, conservando las filas y devolviendo un error propio que identifica la tabla protegida.

#### Scenario: DELETE sobre historial_estado_orden

- **WHEN** se ejecuta `DELETE FROM historial_estado_orden` sobre una tabla con filas
- **THEN** la base responde con el error del disparador, la transacción se aborta y la cantidad de filas no cambia

#### Scenario: DELETE sobre movimiento_stock

- **WHEN** se ejecuta `DELETE FROM movimiento_stock WHERE id = <id existente>`
- **THEN** la base responde con el error del disparador, la transacción se aborta y la fila sigue existiendo

#### Scenario: DELETE sobre historial_precio_repuesto

- **WHEN** se ejecuta `DELETE FROM historial_precio_repuesto` sobre una tabla con filas
- **THEN** la base responde con el error del disparador, la transacción se aborta y la cantidad de filas no cambia

### Requirement: Inserción permitida en las tablas de sólo agregado

Las tres tablas de historial SHALL seguir aceptando `INSERT` de filas válidas: la prohibición alcanza únicamente a modificar y borrar filas existentes.

#### Scenario: Se agrega una línea de historial de estado

- **WHEN** se inserta una fila válida en `historial_estado_orden` con estados del catálogo y los demás campos obligatorios
- **THEN** la base acepta la inserción y la fila queda disponible para consulta

#### Scenario: Se agrega un movimiento de stock

- **WHEN** se inserta una fila válida en `movimiento_stock` con cantidad positiva y repuesto existente
- **THEN** la base acepta la inserción y la fila queda disponible para consulta

### Requirement: Catálogo de estados cerrado por clave foránea

Toda orden SHALL referenciar un `estado_orden` existente: la base MUST rechazar una orden cuyo estado no esté en el catálogo, y MUST aceptar los estados cargados.

#### Scenario: Orden con estado fuera del catálogo

- **WHEN** se intenta insertar una orden de trabajo con `estado = 'INEXISTENTE'` y el resto de los campos válidos
- **THEN** la base rechaza la operación por la clave foránea hacia `estado_orden` y no queda ninguna orden creada

#### Scenario: Orden con estado del catálogo

- **WHEN** se inserta una orden de trabajo con un `estado` presente en `estado_orden`
- **THEN** la base acepta la inserción

### Requirement: La protección se instala y se retira con la migración

La garantía SHALL ser parte del esquema versionado: al aplicar la migración quedan activos los tres disparadores, y al revertirla el esquema queda como antes, sin disparadores ni función residuales.

#### Scenario: Esquema migrado bloquea la modificación

- **WHEN** la base se encuentra en la revisión que instala la protección
- **THEN** un `UPDATE` o un `DELETE` sobre cualquiera de las tres tablas falla con el error del disparador

#### Scenario: Reversión de la migración libera las tablas

- **WHEN** se revierte la migración de la protección y se repite el `UPDATE` o `DELETE`
- **THEN** la operación se ejecuta sin el error del disparador y el esquema no conserva función ni disparadores de sólo agregado

#### Scenario: Volver a aplicar la migración restaura la protección

- **WHEN** se vuelve a aplicar la migración después de haberla revertido
- **THEN** los tres disparadores vuelven a estar activos y el `UPDATE`/`DELETE` vuelve a fallar con el error del disparador
