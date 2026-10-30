# Tasks: Clientes y Vehículos (c-04-clientes-vehiculos)

## 1. Modelos y Migración

- [x] 1.1 Implementar modelos SQLModel `Cliente` y `Vehiculo` en `app/modules/clientes/models.py` con `anio` CHECK (1950..2100), índice único parcial `(patente) WHERE borrado_en IS NULL` y relación 1:1 con `Usuario`. Verificar con tests unitarios en `test/clientes/test_models.py`.
- [x] 1.2 Crear migración incremental de desarrollo `003_clientes_vehiculos` registrando los modelos en `migrations/env.py` y verificar con `alembic upgrade head` y `alembic check`.

## 2. Repositorios y Unit of Work

- [x] 2.1 Implementar `RepositorioClientes` y `RepositorioVehiculos` (heredando de `SoftDeleteRepository`) en `app/modules/clientes/repository.py` e integrarlos en `AsyncUnitOfWork`. Verificar operaciones con tests en `test/clientes/test_repository.py`.

## 3. Endpoints y Lógica de Negocio (TDD)

- [x] 3.1 Implementar `POST /clientes` (alta sin usuario para RECEPCION/ADMIN) y `GET /clientes/{id}` (detalle con precarga de vehículos sin N+1). Verificar tests de contrato y código 409 por documento duplicado en `test/clientes/test_router.py`.
- [x] 3.2 Implementar `POST /clientes/{id}/vehiculos` (alta con validación de año y patente única vigente) y `DELETE /vehiculos/{id}` (baja lógica con punto de extensión para órdenes abiertas). Verificar tests de 404 cliente, 422 año y 409 patente repetida en `test/clientes/test_router.py`.
- [x] 3.3 Implementar `GET /mis-vehiculos` (consulta de vehículos propios del cliente autenticado). Verificar aislamiento estricto (RN-17) con tests en `test/clientes/test_router.py`.

## 4. Integración y Validación del Change

- [x] 4.1 Montar el router de clientes en `router_protegido` en `main.py` y verificar que hereda el control de cambio obligatorio de contraseña (DD-10).
- [x] 4.2 Ejecutar suite completa de tests de clientes (`pytest test/clientes/`) verificando el re-registro de patentes dadas de baja (RN-01) y captura limpia de errores de integridad (RN-18).

## Workflow follow-up

- Actualizar el estado en `CHANGES.md` a `[x]` para C-04 al completar la implementación.
- Archivar el change con `openspec archive c-04-clientes-vehiculos`.
