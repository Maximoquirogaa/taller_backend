# Tasks: Repuestos y Stock (c-05-repuestos-stock)

## 1. Modelos y Migración

- [x] 1.1 Implementar modelos SQLModel `Repuesto`, `MovimientoStock` e `HistorialPrecioRepuesto` en `app/modules/repuestos/models.py` con restricciones CHECK (`precio > 0`, `stock >= 0`, `cantidad > 0`, `precio_nuevo > precio_anterior`), campos `NUMERIC(10,2)` e índice único parcial `(codigo) WHERE borrado_en IS NULL`. Verificar con tests en `test/repuestos/test_models.py`.
- [x] 1.2 Registrar modelos de repuestos en `migrations/env.py` y crear migración incremental de desarrollo `004_repuestos_stock`.

## 2. Repositorios y Unit of Work

- [x] 2.1 Implementar `RepositorioRepuestos` (hereda `SoftDeleteRepository`), `RepositorioMovimientosStock` y `RepositorioHistorialPrecios` (heredan `BaseRepository`) en `app/modules/repuestos/repository.py`.
- [x] 2.2 Implementar `UoWRepuestos` en `app/modules/repuestos/unit_of_work.py` e integrar los nuevos repositorios en `app/core/unit_of_work.py`. Verificar operaciones con tests en `test/repuestos/test_repository.py`.

## 3. Esquemas y Servicios de Negocio

- [x] 3.1 Definir esquemas Pydantic (`EntradaCrearRepuesto`, `EntradaActualizarRepuesto`, `EntradaReponerStock`, `SalidaRepuesto`, `SalidaMovimientoStock`, `SalidaHistorialPrecio`) en `app/modules/repuestos/schemas.py` con `extra="forbid"`.
- [x] 3.2 Implementar servicios en `app/modules/repuestos/service.py`: alta con stock inicial como movimiento atómico (RN-14), reposición de stock (RN-14), modificación con registro automático en historial de precio en la misma transacción (RN-20) con bloqueo de modificación directa de stock (422), baja lógica (RN-16) y consultas de auditoría (US-022).

## 4. Endpoints y Enrutamiento (API)

- [x] 4.1 Implementar endpoints en `app/modules/repuestos/router.py`: `GET /repuestos` con paginación y búsqueda por parámetros ligados (US-017, RN-18), `POST /repuestos` (US-018), `PATCH /repuestos/{id}` (US-019), `DELETE /repuestos/{id}` (US-020), `POST /repuestos/{id}/reponer` (US-021), `GET /repuestos/{id}/movimientos` y `GET /repuestos/{id}/precios` (US-022).
- [x] 4.2 Montar router de repuestos en `router_protegido` en `main.py` y verificar con tests de router y permisos RBAC en `test/repuestos/test_router.py`.

## 5. Integración y Suite Completa

- [x] 5.1 Ejecutar suite completa de tests de repuestos (`pytest test/repuestos/`) verificando código duplicado (409), historial de precio transaccional, stock invariable por PATCH y búsqueda inmune a SQL injection.

## Workflow follow-up

- Actualizar el estado en `CHANGES.md` a `[x]` para C-05 al completar la implementación.
- Archivar el change con `openspec archive c-05-repuestos-stock`.
