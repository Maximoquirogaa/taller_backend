# Tasks

## 1. Modelos de acceso (spec `access-data-model`)

- [x] 1.1 Implementar `Usuario`, `AsignacionRol`, `IntentoAcceso` y `EventoSeguridad` en `app/modules/usuarios/models.py` (SQLModel `table=True`, snake_case y type hints, `email` UNIQUE, fechas con `timezone=True` → `timestamptz`, `intento_acceso` sin FK con índice `(email, ip, cuando)`, `evento_seguridad.actor` como texto) — verificar: `python -c "from sqlmodel import SQLModel; import app.modules.usuarios.models; print(sorted(SQLModel.metadata.tables))"` lista las 4 tablas y `usuario.email` figura como única
- [x] 1.2 Agregar en `__table_args__` de `AsignacionRol` el `CheckConstraint` de rol ∈ {ADMIN, RECEPCION, MECANICO, CLIENTE} (D2) y el índice único parcial `(usuario_id, rol) WHERE revocada_en IS NULL` (D3) — verificar: el `Index` de metadata tiene `unique=True` y `postgresql_where` con `revocada_en IS NULL`, y el `CheckConstraint` nombra los cuatro roles

## 2. Base de pruebas y migración 001 (specs `access-data-model`, `data-persistence`)

- [x] 2.1 Agregar `pytest` y `pytest-asyncio` a `requirements.txt` (dependencias de desarrollo, marcadas como tales) y crear `test/conftest.py` con el fixture que garantiza la base de pruebas `taller_test` creada con `alembic upgrade head` y la deja limpia entre tests (TRUNCATE de las tablas de acceso) — verificar: `pytest --collect-only` termina sin errores y con PG caído la suite se **salta** con mensaje claro (no falla en rojo)
- [x] 2.2 Registrar `app.modules.usuarios.models` en `migrations/env.py` como origen de `target_metadata` (D6) y generar la migración `001` con `alembic revision --autogenerate` (migración **de desarrollo**: C-11 la reemplaza por `001_esquema_inicial`, ver D6b) — verificar: `alembic upgrade head` crea las 4 tablas con sus índices, `alembic downgrade -1` las elimina y `alembic check` no reporta diferencias
- [x] 2.3 Escribir `test/test_acceso_modelos.py`: email duplicado → error de integridad; segundo rol abierto del mismo usuario → error; con `revocada_en` seteado se acepta la re-asignación y la fila revocada sigue existiendo; rol fuera de catálogo → error de restricción — verificar: `pytest test/test_acceso_modelos.py` en verde contra `taller_test`

## 3. Repositorios y Unit of Work (spec `data-persistence`)

- [x] 3.1 Implementar `app/core/repository.py`: `BaseRepository[T]` con `get_by_id`/`get_all`/`count`/`add`/`update`/`delete` (nombres fijados por la consigna) siempre con `flush()` y **nunca** `commit()`, más `SoftDeleteRepository[T]` que hereda, filtra los dados de baja y agrega `get_by_id_including_deleted` y `soft_delete` (D5) — verificar: test de repositorio que agrega con `flush()` y comprueba desde una segunda sesión que la fila **no** está confirmada hasta el commit del UoW
- [x] 3.2 Implementar `app/core/unit_of_work.py`: `UnitOfWork` como async context manager que confirma al salir sin excepción, revierte con excepción y **no** cierra la sesión (D4) — verificar: tests de UoW: commit deja las filas, rollback las borra y la sesión sigue usable tras el bloque (atributos legibles)
- [x] 3.3 Escribir `test/test_uow.py` cubriendo commit, rollback con propagación de la excepción, sesión no cerrada y atomicidad multi-tabla (escritura en dos tablas con fallo en la segunda → ninguna queda) — verificar: `pytest test/test_uow.py` en verde

## 4. Paginación (spec `pagination`)

- [x] 4.1 Implementar `app/core/paginacion.py`: schema de parámetros `page` (ge=1) y `size` (ge=1, le=100, default 20) con mensajes propios, y función que arma `{items,total,page,size,pages}` con `pages = ceil(total/size)` y la regla de borde (total=0 → pages=1; `page > pages` → 422 «La página N no existe: hay M») (D8) — verificar: instanciar el schema con `page=0` y con `size=500` lanza error de validación (422 desde FastAPI), sin `page`/`size` asume 1 y 20, y el constructor rechaza `page=2` con `pages=1`
- [x] 4.2 Escribir `test/test_paginacion.py`: cálculo de `pages`, `page` inicial en 1, default de `size`, 422 fuera de rango (page<1, size>100, no numérico), **página más allá de la última → 422 con mensaje propio**, colección vacía → 200 con `items` vacío y `pages`=1, y `total` respeta los filtros de la página — verificar: `pytest test/test_paginacion.py` en verde

## 5. Verificación integral

- [x] 5.1 Recorrido completo sobre PostgreSQL: `alembic upgrade head` → arrancar `uvicorn main:app` (el esquema **no** se crea al arrancar) → `GET /health/ready`=200 → suite `pytest` completa en verde — verificar: los cuatro resultados observados en una sola corrida
- [x] 5.2 Revisión de las reglas duras de `AGENTS.md` aplicables (esquema solo Alembic, sin `create_all`, `flush()` y nunca `commit()` en repositorios, sin lazy loading — precarga en el repositorio que la necesita, snake_case/type hints, contratos estrictos) y de los "Leer antes" de `CHANGES.md` para C-02 — verificar: checklist revisado sin hallazgos; el change queda listo para `/opsx:archive`

## Workflow follow-up

- Archivar el change con `/opsx:archive c-02-core-models` y marcar `[x]` en `CHANGES.md` (C-02) para liberar el gate de C-03.
