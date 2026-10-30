# Design: Clientes y Vehículos (c-04-clientes-vehiculos)

## Context
Tras completar la autenticación y autorización en C-03, la API cuenta con sesiones mediante cookie HttpOnly, resolución de usuario en cada petición (`usuario_actual`), dependencias de rol (`requiere_rol`) y un grupo `router_protegido` que exige cambio de contraseña no pendiente (DD-10). C-02 estableció los repositorios base (`BaseRepository`, `SoftDeleteRepository`) y el Unit of Work asincrónico (`AsyncUnitOfWork`). Este change introduce el dominio operativo de clientes y vehículos cumpliendo RN-01, RN-16 y RN-17.

## Goals / Non-Goals

**Goals:**
- Modelar `Cliente` y `Vehiculo` en SQLModel con restricciones de integridad (CHECK de año 1950–2100, `documento` único en cliente, `usuario_id` único opcional).
- Garantizar a nivel base de datos la unicidad de patente vigente mediante índice único parcial: `(patente) WHERE borrado_en IS NULL` (RN-01).
- Implementar borrado lógico en `Vehiculo` utilizando `SoftDeleteRepository`.
- Proveer endpoints protegidos para altas, baja lógica y consultas con aislamiento de cliente (`/mis-vehiculos`) y sin problema N+1 (`GET /clientes/{id}` con precarga).
- Añadir migración incremental de desarrollo `003_clientes_vehiculos`.

**Non-Goals:**
- Gestión de órdenes de trabajo (corresponde a C-07 y C-08). La validación de órdenes abiertas en la baja de vehículo queda estructurada como punto de extensión (`tiene_ordenes_abiertas`), resolviendo `False` de forma segura hasta que la tabla `orden_trabajo` y su catálogo existan.
- Modificación del flujo de autoregistro de C-03 (que ya crea usuario + rol CLIENTE + ficha de cliente en una sola transacción).

## Decisions

### 1. Índice único parcial en PostgreSQL para patentes vigentes (RN-01)
- **Decisión**: Crear el índice `ix_vehiculo_patente_activa` sobre `vehiculo (patente) WHERE borrado_en IS NULL` a nivel de modelo/migración Alembic, en lugar de validar únicamente por consulta previa en la aplicación.
- **Alternativas**: Validación en servicio `SELECT ... WHERE patente = :p AND borrado_en IS NULL`. Se descartó porque no previene condiciones de carrera en altas concurrentes (la consigna exige garantía a nivel de base de datos).
- **Manejo de errores**: Capturar `IntegrityError` en el Unit of Work / Repositorio y traducir a HTTP 409 con mensaje limpio sin filtrar texto interno de PostgreSQL (RN-18).

### 2. Precarga de vehículos sin N+1 mediante `selectinload` (US-016, RN-17)
- **Decisión**: Para `GET /clientes/{id}`, utilizar `selectinload(Cliente.vehiculos)` filtrando vehículos no borrados (`borrado_en IS NULL`).
- **Alternativas**:
  - `joinedload`: Puede duplicar datos de la fila de cliente si tiene múltiples vehículos y complica conteos o paginaciones.
  - Carga diferida (lazy loading): Viola la regla dura del proyecto (`sin_lazy_loading`) y en SQLAlchemy async genera `MissingGreenlet`.
- **Resultado**: Exactamente 2 consultas SQL fijas e independientes de si el cliente tiene 1, 5 o 20 vehículos.

### 3. Aislamiento y consulta de `/mis-vehiculos` (US-015, RN-17)
- **Decisión**: El endpoint obtiene `usuario_actual`, busca el `Cliente` donde `cliente.usuario_id == usuario_actual.id` y lista sus vehículos activos. Si el usuario no tiene ficha de cliente (por ejemplo, un mecánico o recepcionista consultando sus vehículos personales sin ficha), retorna lista vacía `[]` con código 200.

### 4. Punto de extensión para verificación de órdenes abiertas (RN-16)
- **Decisión**: Al ejecutar `DELETE /vehiculos/{id}`, el servicio consulta `verificar_ordenes_abiertas(session, vehiculo_id)`. En C-04, la función verifica si existe la tabla `orden_trabajo`; si no existe aún, retorna `False`. En C-08, esta función se conecta a la máquina de estados evaluando `es_final`.

## Risks / Trade-offs

- **[Riesgo: Choque de patentes entre mayúsculas y minúsculas]** → **Mitigación**: Normalizar la patente a mayúsculas y sin espacios antes de persistir y consultar (`patente.strip().upper()`).
- **[Riesgo: Exposición de trazas internas en violaciones de unicidad]** → **Mitigación**: Traducir toda `IntegrityError` en el repositorio/servicio a excepciones HTTP específicas con código 409 y mensaje de dominio (RN-18).
