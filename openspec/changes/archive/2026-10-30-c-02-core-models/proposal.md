# Proposal

## Why

El proyecto ya arranca y expone salud (C-01), pero no tiene ninguna capa de persistencia: no hay modelos de tablas, ni transacciones, ni repositorios, ni paginación, ni migración con contenido. Sin el núcleo de datos y de transacción, ningún change de dominio (auth, clientes, repuestos, órdenes) puede escribir en la base de forma atómica ni garantizar las reglas de unicidad que la consigna evalúa (RN-01, RN-03, C-19).

## What Changes

- Modelos SQLModel de acceso en `app/modules/usuarios/models.py`: `Usuario` (`email` UNIQUE, `activo`, `debe_cambiar_password`, `password_cambiada_en`), `AsignacionRol` (CHECK `rol ∈ {ADMIN, RECEPCION, MECANICO, CLIENTE}`, vigencia con `desde`/`vence_en`/`revocada_en`/`otorgada_por`), `IntentoAcceso` (índice `(email, ip, cuando)`) y `EventoSeguridad` (actor es texto, sin FK).
- `AsignacionRol` con **índice único parcial** `(usuario_id, rol) WHERE revocada_en IS NULL` → un usuario tiene a lo sumo una asignación abierta por rol (RN-03, DD-02, DD-03).
- `app/core/repository.py`: `BaseRepository[T]` y `SoftDeleteRepository[T]` con `add`/`update` que hacen **`flush()` y nunca `commit()`**.
- `app/core/unit_of_work.py`: UoW base como context manager asíncrono — commit al salir sin excepción, rollback si la excepción se propaga, y **no cierra la sesión** (la sesión sigue siendo de la petición).
- `app/core/paginacion.py`: envoltorio `{items, total, page, size, pages}` — `page` desde 1, `size` 1–100 con default 20, valores fuera de rango → 422.
- Migración `001` de Alembic (**autogenerate**, **de desarrollo** — C-11 consolida el entregable en dos migraciones, ver `CHANGES.md` §Estrategia de migraciones) con las 4 tablas de acceso: `timestamptz` en todas las fechas, cada FK con su índice; esquema **solo** por `alembic upgrade head` (sin `create_all`, DD-08).
- Tests automatizados del núcleo: unicidad parcial de rol abierto (segunda asignación abierta → error de integridad; revocada permite re-asignar) y semántica transaccional del UoW (commit / rollback / sesión abierta).

## Capabilities

### New Capabilities

- `data-persistence`: semántica transaccional del núcleo — repositorios que solo hacen `flush()`, UoW que confirma o revierte una operación sin cerrar la sesión, y atomicidad de las escrituras múltiples.
- `access-data-model`: restricciones de la base para las tablas de acceso — `email` único, CHECK de roles, unicidad de la asignación **abierta** por rol (parcial), índices de FK y esquema creado únicamente por migraciones.
- `pagination`: envoltorio de listados `{items, total, page, size, pages}` con `page` ≥ 1, `size` acotado 1–100 (default 20) y 422 ante valores fuera de rango.

### Modified Capabilities

(ninguna — `service-configuration`, `service-health` y `service-lifespan` no cambian de requisito; `openspec list --specs` solo muestra esas tres.)

## Impact

- **Archivos nuevos**: `app/core/repository.py`, `app/core/unit_of_work.py`, `app/core/paginacion.py`, primera versión de `app/modules/usuarios/models.py`, `migrations/versions/001_*.py` (autogenerate) + `test/` con tests de núcleo.
- **Archivos modificados**: `app/modules/usuarios/__init__.py` (exporta modelos), `migrations/env.py` si hace falta registrar los modelos para autogenerate, `requirements.txt` (agrega el tooling de tests: pytest / pytest-asyncio, solo desarrollo).
- **API**: sin endpoints nuevos — este change es la base que C-03 (auth) y C-04…C-11 usan.
- **Base de datos**: crea 4 tablas nuevas (`usuario`, `asignacion_rol`, `intento_acceso`, `evento_seguridad`); ninguna tabla existente se modifica (todavía no hay datos en producción).
- **Dependencias**: desbloquea C-03 (auth), que a su vez abre la Fase 2.
- **Bloquea**: C-03 depende de estos modelos y del UoW (RN-02 exige un solo Unit of Work).
