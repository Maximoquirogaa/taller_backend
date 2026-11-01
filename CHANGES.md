# CHANGES — Secuencia de Implementación

> Índice canónico de todos los changes del proyecto **TP_taller** (API asincrónica de taller mecánico).
> Cada change es atómico: un agente puede implementarlo en una sesión (~4-6 horas).
> **Leer este archivo antes de ejecutar cualquier `/opsx:propose`.**

---

## Cómo usar este documento

1. Identificar el change a implementar (verificar que sus dependencias están en `openspec/changes/archive/`).
2. Leer los docs de la knowledge-base indicados en "Leer antes".
3. Ejecutar `/opsx:propose <nombre-del-change>`.
4. Al terminar el change, archivarlo con `/opsx:archive <nombre-del-change>`.
5. Marcar el checkbox `[x]` en este archivo.

> Nota: los códigos `C-NN` de este índice son IDs de changes. Cuando un scope menciona un
> "ejercicio C-NN de la consigna", se refiere a la numeración de casos de la consigna original.

---

## Estrategia de migraciones (consolidación final)

El entregable tiene **exactamente dos migraciones**, como pide la consigna:

| # | Migración | Origen |
|---|-----------|--------|
| `001` | `esquema_inicial` | `alembic revision --autogenerate` sobre base vacía con **todos** los modelos registrados en `env.py`: 13 tablas, CHECK, índices únicos parciales, FKs indexadas, `timestamptz`, `NUMERIC` |
| `002` | `disparador_solo_agregado` | **escrita a mano**: función + los 3 disparadores de RN-15 |

Durante el desarrollo (C-02…C-09) cada change genera su migración **incremental y descartable** para poder correr los tests contra el esquema real (el esquema solo se crea con Alembic, nunca con `create_all`). Esas migraciones **no** son parte del entregable.

**C-11 consolida**, en este orden:

1. Base nueva vacía → borrar `migrations/versions/*` → `alembic revision --autogenerate -m "esquema inicial"` con todos los modelos importados en `env.py`.
2. Renumerar a `002` la migración del disparador creada en C-09 (ajustar `down_revision`); **no** se regenera: se conserva tal cual.
3. Verificar desde cero: `alembic upgrade head` → `alembic check` sin diferencias → `alembic downgrade base` → `upgrade head` otra vez → `python seed.py` → `test/solo_agregado.sql` en verde → suite `pytest` completa.

> **Regla**: ninguna migración de desarrollo sobrevive a C-11. Si apareciera una diferencia entre modelos y esquema, se corrige el **modelo** y se repite la consolidación — nunca un `ALTER` suelto a mano (salvo el disparador, que por definición va a mano).

---

## Árbol de dependencias

```
C-01 foundation-setup
  └── C-02 core-models                    ← modelos de acceso + repos/UoW base
        └── C-03 auth                     ← desbloquea TODO lo demás
              │
              ├── C-04 clientes-vehiculos ──┐
              │                             ├── C-07 ordenes-crud
              ├── C-05 repuestos-stock ─────┘         │
              │                             (C-08, C-09, C-10 en paralelo tras C-07)
              └── C-06 usuarios-roles-auditoria       │
                        │                             ▼
                        │               C-08 ordenes-lifecycle ──┐
                        │               C-09 append-only-triggers├── C-11 evidencia-entrega
                        └──────────────▶ C-10 seed-inicial ──────┘
```

### Paralelismo por fase

> Cada "gate" es un punto de sincronización. Los changes dentro de un grupo pueden ejecutarse en paralelo.

```
GATE 0: ninguna
  → C-01 foundation-setup               [Agente A]

GATE 1: C-01 ✓
  → C-02 core-models                    [Agente A]

GATE 2: C-02 ✓
  → C-03 auth                           [Agente A]

GATE 3: C-03 ✓                         ← PRIMER FORK (3 paralelos)
  → C-04 clientes-vehiculos             [Agente A]
  → C-05 repuestos-stock                [Agente B]
  → C-06 usuarios-roles-auditoria       [Agente C]

GATE 4: C-04 ✓ + C-05 ✓
  → C-07 ordenes-crud                   [Agente A]

GATE 5: C-07 ✓                         ← FORK (3 paralelos)
  → C-08 ordenes-lifecycle              [Agente A]
  → C-09 append-only-triggers           [Agente B]
  → C-10 seed-inicial                   [Agente C — si C-06 ✓]

GATE 6: C-08 ✓ + C-09 ✓ + C-10 ✓
  → C-11 evidencia-entrega              [Agente C]
```

### Camino crítico (8 changes — mínimo irreducible)

```
C-01 → C-02 → C-03 → C-05 → C-07 → C-08 → C-11*
```

\* C-09 y C-10 no están en la cadena lineal más corta pero son **indispensables para la entrega**
(disparador de sólo agregado y seed son requisitos de la consigna); se ejecutan en paralelo con C-08.

### Plan óptimo con 3 agentes

```
Paso │ Agente A (Backend Core)      │ Agente B (Backend Aux)     │ Agente C (Aux / QA-SQL)
─────┼──────────────────────────────┼────────────────────────────┼──────────────────────────
  1  │ C-01 foundation-setup        │           —                │           —
  2  │ C-02 core-models             │           —                │           —
  3  │ C-03 auth                    │           —                │           —
  4  │ C-04 clientes-vehiculos      │ C-05 repuestos-stock       │ C-06 usuarios-roles-auditoria
  5  │ C-07 ordenes-crud            │           —                │           —
  6  │ C-08 ordenes-lifecycle       │ C-09 append-only-triggers  │ C-10 seed-inicial
  7  │           —                  │           —                │ C-11 evidencia-entrega
```

---

## FASE 0 — Cimientos

### [C-01] `foundation-setup`
- **Estado**: `[x]` completado (archivado 2026-10-27)
- **Scope**: Scaffolding del proyecto + infraestructura base del backend
  - Estructura de directorios obligatoria: `main.py`, `seed.py`, `alembic.ini`, `requirements.txt`, `env.example`, `app/core/`, `app/modules/{health,usuarios,clientes,repuestos,ordenes}/`, `migrations/`, `test/`
  - `requirements.txt`: fastapi[standard], SQLModel ≥0.0.24, SQLAlchemy 2 async, asyncpg, alembic, pydantic-settings, bcrypt, PyJWT
  - `app/core/config.py`: Settings con todas las variables (POSTGRES_*, SECRET_KEY sin default, BCRYPT_COST, TOKEN_EXPIRE_SEGUNDOS=1800, COOKIE_SECURE, SQL_ECHO) y `@computed_field` para la URL `postgresql+asyncpg://`
  - `app/core/database.py`: motor + fábrica de sesiones creados en **lifespan**, en `app.state`; `expire_on_commit=False`; `dispose()` al apagar
  - `main.py`: app + lifespan + dos grupos de rutas (abierto / protegido) con montaje correcto
  - Módulo `health` solo con `router.py`: `GET /health/live` (200 sin DB) y `GET /health/ready` (`SELECT 1`; 200/503)
  - Alembic inicializado con plantilla **asincrónica** (env.py con `run_sync` adaptado); `env.example` con todas las variables sin secretos
- **Dependencias**: ninguna
- **Governance**: BAJO
- **Leer antes**:
  - `knowledge-base/02_descripcion_general.md` §Stack, §Arquitectura general
  - `knowledge-base/08_arquitectura_propuesta.md` §Estructura de directorios, §Variables de entorno
  - `knowledge-base/06_funcionalidades.md` §Épica 1 (US-001, US-002)
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-09, §DD-10, §SU-01…SU-05

---

## FASE 1 — Núcleo de datos y autenticación

### [C-02] `core-models`
- **Estado**: `[x]` completado (archivado 2026-10-30)
- **Scope**: Modelos de acceso + infraestructura genérica de persistencia + migración inicial
  - Modelos SQLModel: `Usuario`, `AsignacionRol`, `IntentoAcceso`, `EventoSeguridad`
  - `AsignacionRol`: CHECK rol ∈ {ADMIN, RECEPCION, MECANICO, CLIENTE}; **índice único parcial** `(usuario_id, rol) WHERE revocada_en IS NULL` (RN-03)
  - `app/core/repository.py`: `BaseRepository[T]`, `SoftDeleteRepository[T]` — `add`/`update` con `flush()`, nunca `commit()`
  - `app/core/unit_of_work.py`: UoW base como context manager async (commit al salir, rollback con excepción, no cierra la sesión)
  - `app/core/paginacion.py`: envoltorio `{items,total,page,size,pages}` (page desde 1; size 1–100 default 20; fuera de rango → 422)
  - Migración de **desarrollo** 001 (autogenerate; C-11 la consolida): tablas de acceso con FKs indexadas y `timestamptz`
  - Tests: unicidad parcial de rol abierto; transacción del UoW (commit/rollback)
- **Dependencias**: C-01
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §usuario, §asignacion_rol, §intento_acceso, §evento_seguridad
  - `knowledge-base/08_arquitectura_propuesta.md` §Patrones (Repository, UoW, catálogo)
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-02, §DD-03, §DD-08
  - `knowledge-base/05_reglas_de_negocio.md` §RN-01, §RN-03

---

### [C-03] `auth`
- **Estado**: `[x]` completado (archivado 2026-10-30)
- **Scope**: Autenticación JWT en cookie HttpOnly + autorización RBAC + cambio obligatorio de contraseña
  - `app/core/security.py`: bcrypt (`to_thread` + semáforo, hash **antes** de abrir la transacción, ≤72 bytes) + JWT PyJWT (`sub`, `iat` sin truncar, `exp`, roles vigentes; firmado con `SECRET_KEY`)
  - `POST /auth/registro` — 201 con usuario + rol CLIENTE + ficha cliente en **un solo UoW**; email/documento duplicado → 409; `extra="forbid"` (US-003, RN-02)
  - `POST /auth/login` — límite 5 fallos/60 s por email+IP → 429 + `Retry-After` sin tocar bcrypt; hash ficticio si el email no existe (mismo mensaje y tiempo); intento anotado en sesión/transacción propias siempre confirmadas; 200 con `Set-Cookie` HttpOnly/SameSite=Lax/Max-Age, cuerpo **sin** token, con `debe_cambiar_password` y `expira_en_segundos` (US-004, RN-08/09)
  - `POST /auth/logout` — borra cookie (US-005); `GET /auth/yo` — usuario + roles vigentes (DB) + roles del token (US-006, RN-04)
  - `POST /auth/cambiar-password` — flag limpiado, token nuevo emitido después; cookies anteriores 401 por `iat < password_cambiada_en` sin truncar (US-007, RN-06/07)
  - `app/core/dependencies.py`: `usuario_actual` (lee `request.cookies`; Bearer → 401), roles vigentes en cada petición, `requiere_rol()`, control de cambio obligatorio montado una sola vez en el grupo protegido (DD-10)
  - Migración de **desarrollo** 002: ajustes si hacen falta; Tests: login ok/fallido idénticos, 429 al 5.º fallo, token anterior al cambio → 401, rutas protegidas con cambio pendiente → 403
- **Dependencias**: C-02
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/03_actores_y_roles.md` (actores, rutas públicas, cambio obligatorio)
  - `knowledge-base/05_reglas_de_negocio.md` §RN-02, §RN-04…RN-09
  - `knowledge-base/07_flujos_principales.md` §Flujo 1, §Flujo 2, §Flujo 3
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-04, §DD-05, §DD-06, §DD-07

---

## FASE 2 — Dominio del taller

> Los changes C-04, C-05 y C-06 pueden proponerse en paralelo tras C-03. C-04 y C-05 deben archivarse antes de C-07.

### [C-04] `clientes-vehiculos`
- **Estado**: `[x]` completado (2026-10-30)
- **Scope**: Fichas de cliente y vehículos con borrado lógico
  - Modelos: `Cliente` (`usuario_id` UNIQUE nulo → 1:1 opcional; `documento` UNIQUE), `Vehiculo` (CHECK anio 1950–2100, `borrado_en`)
  - **Índice único parcial** `(patente) WHERE borrado_en IS NULL` (RN-01)
  - `POST /clientes` — alta sin usuario (RECEPCION/ADMIN); 409 documento duplicado (US-012)
  - `POST /clientes/{id}/vehiculos` — 404 cliente inexistente, 409 patente vigente repetida (US-013)
  - `DELETE /vehiculos/{id}` — baja lógica; 409 si tiene órdenes abiertas (estado no final, `es_final` — la columna se lee del catálogo cuando exista; por ahora dejar el punto de extensión documentado) (US-014, RN-16)
  - `GET /mis-vehiculos` — solo los propios del cliente ligado al usuario (US-015, RN-17)
  - `GET /clientes/{id}` — ficha con vehículos precargados, sin N+1 (US-016)
  - Migración de **desarrollo** 003: tablas cliente + vehiculo; Tests: 409 patente repetida vigente, patente libre tras baja, aislamiento de `/mis-vehiculos`
- **Dependencias**: C-03
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §cliente, §vehiculo
  - `knowledge-base/06_funcionalidades.md` §Épica 4 (US-012…US-016)
  - `knowledge-base/07_flujos_principales.md` §Flujo 9
  - `knowledge-base/05_reglas_de_negocio.md` §RN-01, §RN-16, §RN-17

---

### [C-05] `repuestos-stock`
- **Estado**: `[x]` completado (archivado 2026-10-30)
- **Scope**: Catálogo de repuestos con stock por movimientos e historial de precios
  - Modelos: `Repuesto` (precio NUMERIC(10,2) CHECK > 0, stock CHECK >= 0, `borrado_en`), `MovimientoStock`, `HistorialPrecioRepuesto` (CHECK `precio_nuevo > precio_anterior`)
  - **Índice único parcial** `(codigo) WHERE borrado_en IS NULL`
  - `GET /repuestos?q=&page=&size=` — envoltorio paginado; `q` con **parámetros ligados** (RN-18); roles ADMIN/RECEPCION/MECANICO (US-017)
  - `POST /repuestos` (con `stock_inicial`) — 201 + movimiento «Stock inicial» en el mismo UoW (US-018, RN-14)
  - `PATCH /repuestos/{id}` — `exclude_unset`; si cambia el precio → línea en `historial_precio_repuesto` en la **misma transacción**; stock no editable → 422; RECEPCION → 403 (US-019, RN-20)
  - `DELETE /repuestos/{id}` — baja lógica (US-020, RN-16)
  - `POST /repuestos/{id}/reponer` — único punto de escritura del stock + movimiento (US-021, RN-14)
  - `GET /repuestos/{id}/movimientos` y `.../precios` (US-022)
  - Migración de **desarrollo** 004: tablas repuesto, movimiento_stock, historial_precio_repuesto; Tests: 409 código repetido vigente, historial solo con cambio de precio, sin línea si solo cambia descripción
- **Dependencias**: C-03
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §repuesto, §movimiento_stock, §historial_precio_repuesto
  - `knowledge-base/06_funcionalidades.md` §Épica 5 (US-017…US-022)
  - `knowledge-base/07_flujos_principales.md` §Flujo 8
  - `knowledge-base/05_reglas_de_negocio.md` §RN-14, §RN-18, §RN-20

---

### [C-06] `usuarios-roles-auditoria`
- **Estado**: `[x]` completado (archivado 2026-10-31)
- **Scope**: Administración de personal, roles con vigencia y auditoría (todo ADMIN)
  - `POST /usuarios` — alta de empleado con contraseña provisoria y `debe_cambiar_password=true`; 409 email repetido; emite `evento_seguridad` (US-008)
  - `POST /usuarios/{id}/roles` — otorgar rol con `vencimiento` opcional (zona horaria obligatoria, futuro); 409 si ya tiene rol abierto (índice parcial); reasignar vencido cierra la fila anterior (US-009, RN-03)
  - `DELETE /usuarios/{id}/roles/{rol}` — escribe `revocada_en`, nunca borra; 409 si es el propio ADMIN (RN-05); la sesión afectada recibe 403 en la siguiente petición (RN-04)
  - `GET /eventos` — paginado con envoltorio; 422 page/size inválidos (US-011)
  - `evento_seguridad` en: alta de personal, cambio de rol/contraseña, revocación
  - Tests: unicidad de rol abierto, revocar propio ADMIN → 409, permiso perdido con sesión abierta tras revocar
- **Dependencias**: C-03
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/03_actores_y_roles.md` §RBAC, §autoprotección
  - `knowledge-base/06_funcionalidades.md` §Épica 3 (US-008…US-011)
  - `knowledge-base/05_reglas_de_negocio.md` §RN-03, §RN-04, §RN-05
  - `knowledge-base/04_modelo_de_datos.md` §asignacion_rol, §evento_seguridad

---

## FASE 3 — Órdenes de trabajo

### [C-07] `ordenes-crud`
- **Estado**: `[x]` completado (archivado 2026-10-31)
- **Scope**: Modelo de órdenes (composición + catálogo de estados) con apertura, listado y detalle
  - Modelos: `EstadoOrden` (PK = `codigo`, `posicion` UNIQUE, `es_final`), `OrdenTrabajo`, `ItemOrden`, `HistorialEstadoOrden`
  - `ItemOrden`: **UNIQUE** `(orden_id, repuesto_id)` — composición, sin repetidos; `precio_unitario` copiado del repuesto (RN-10)
  - Repositorio de `estado_orden` de **sólo lectura** (no hereda de `BaseRepository`); la migración crea la tabla **vacía** (DD-01, RN-19)
  - `POST /ordenes` — RECEPCION/ADMIN; contrato `vehiculo_id`, `falla`, `items[{repuesto_id, cantidad}]` sin precio/total/estado; catálogo vacío → 409; total calculado por el servidor; historial null→PENDIENTE (US-023, RN-10, RN-19)
  - `GET /ordenes?estado=&page=&size=` — estado fuera del contrato → 422 (US-024)
  - `GET /ordenes/{id}` — vehículo, cliente, ítems con repuesto, historial; **consultas fijas** sin N+1 (2 vs 4 ítems = mismas consultas, ejercicio C-15 de la consigna); dueño ajeno → 403; inexistente → 404 (US-025, RN-17)
  - `GET /estados-orden` — catálogo por posición, finales marcados (US-029, RN-19)
  - `GET /mis-ordenes` — solo las de los vehículos propios, paginado (US-030, RN-17)
  - Migración de **desarrollo** 005: tablas orden_trabajo, item_orden, estado_orden, historial_estado_orden; Tests: 409 catálogo vacío, sin ítems/repetidos → 422/409, precios copiados, total del servidor
- **Dependencias**: C-04, C-05
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §estado_orden, §orden_trabajo, §item_orden, §historial_estado_orden
  - `knowledge-base/06_funcionalidades.md` §Épica 6 (US-023…US-025, US-029, US-030)
  - `knowledge-base/07_flujos_principales.md` §Flujo 4
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-01

---

### [C-08] `ordenes-lifecycle`
- **Estado**: `[x]` completado (archivado 2026-10-31)
- **Scope**: Máquina de estados de la orden con la transacción crítica de stock
  - `POST /ordenes/{id}/iniciar` — MECANICO; PENDIENTE → EN_REPARACION con `mecanico_id` = yo; 409 si el estado no lo permite; línea de historial (US-026, RN-11)
  - `POST /ordenes/{id}/terminar` — mecánico asignado **o** ADMIN (ruta sin `requiere_rol` simple); en **un solo UoW**: verificar permiso y estado → chequear stock de cada ítem → si alguno no alcanza, lanzar y revertir **todo** (409, sin escrituras parciales, ejercicio C-11 de la consigna) → descontar stock + `movimiento_stock` por salida → estado TERMINADA + historial; tras confirmar, aviso con `BackgroundTasks` (`asyncio.sleep(0.5)` + log) (US-027, RN-13, RN-14)
  - `POST /ordenes/{id}/cancelar` — ruta **sin** `requiere_rol`; el servicio evalúa primero relación personal o dueño (403) y **después** estado PENDIENTE (409); PENDIENTE → CANCELADA + historial (US-028, RN-12)
  - Baja de vehículo desbloqueada: `es_final` del catálogo decide "órdenes abiertas" (RN-16, cierra el punto de extensión de C-04)
  - Tests: 409 por stock insuficiente sin escrituras (stock, movimientos e historial intactos), 403 antes que 409 en cancelar, terminar orden ajena → 403
- **Dependencias**: C-07
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/07_flujos_principales.md` §Flujo 5, §Flujo 6, §Flujo 7
  - `knowledge-base/05_reglas_de_negocio.md` §RN-11, §RN-12, §RN-13, §RN-14
  - `knowledge-base/06_funcionalidades.md` §US-026, §US-027, §US-028
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-11

---

## FASE 4 — Integridad en la base

### [C-09] `append-only-triggers`
- **Estado**: `[x]` completado (archivado 2026-10-31)
- **Scope**: Disparador de sólo agregado instalado por migración escrita a mano + prueba SQL
  - Migración de **desarrollo** 006 **escrita a mano** (no autogenerate): función + disparadores que rechazan UPDATE y DELETE en `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto` (RN-15); comentario explícito en la migración de que es a mano (DD-08). **Esta migración sobrevive a la consolidación**: en C-11 se renumera a `002` y se conserva tal cual
  - La migración se escribe sin depender de identificadores autogenerados (solo `op.execute` con `CREATE OR REPLACE FUNCTION` / `DROP TRIGGER IF EXISTS`), para que renumerarla sea mecánico
  - `test/solo_agregado.sql`: script para psql con los **6 rechazos** (UPDATE/DELETE × 3 tablas) + el rechazo del FK de estado fuera del catálogo (US-031, ejercicio C-14 de la consigna)
  - Verificar upgrade/downgrade reproducibles (el downgrade remueve los disparadores)
  - Tests: los 6 rechazos fallan con error de disparador; INSERT sigue funcionando
- **Dependencias**: C-07
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §historial_estado_orden, §movimiento_stock, §historial_precio_repuesto
  - `knowledge-base/05_reglas_de_negocio.md` §RN-15, §RN-19
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-08
  - `knowledge-base/06_funcionalidades.md` §US-031

---

## FASE 5 — Estado inicial y entrega

### [C-10] `seed-inicial`
- **Estado**: `[x]` completado (archivado 2026-10-31)
- **Scope**: `seed.py` que deja la base en el estado inicial conocido
  - Vacía tablas y carga en orden: catálogo `estado_orden` (PENDIENTE, EN_REPARACION, TERMINADA final, CANCELADA final) **primero**; usuarios (admin@, admin2@, recepcion@, mecánicos, cliente@, nuevo@ con cambio obligatorio); clientes (Laura con usuario + 2 vehículos, Jorge sin usuario + 1 vehículo); repuestos (4 piezas con stock inicial como movimiento); órdenes (una PENDIENTE, una EN_REPARACION asignada pidiendo 4 bujías con stock 2 — caso de stock insuficiente); historial de precios 8000→8500; `evento_seguridad` de `SISTEMA` «Carga de los datos iniciales»
  - Contraseñas ficticias solo en `seed.py`, nunca como secretos reales en el repo
  - Idempotente: se puede re-ejecutar dejando siempre el mismo estado
  - Tests: re-ejecución limpia; la orden EN_REPARACION tiene stock insuficiente para terminar (prepara el caso de C-08)
- **Dependencias**: C-06, C-07
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §Seed data inicial
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-01 (catálogo aparte de la migración)
  - `knowledge-base/10_preguntas_abiertas.md` §pregunta media de seed
  - `knowledge-base/03_actores_y_roles.md` §cambio obligatorio (usuario `nuevo@`)

---

### [C-11] `evidencia-entrega`
- **Estado**: `[x]` completado (archivado 2026-10-31)
- **Scope**: **Consolidación de migraciones** + suite HTTP de la consigna + evidencias + README de entrega
  - **Consolidar el esquema en las dos migraciones del entregable** (ver §Estrategia de migraciones): borrar `migrations/versions/*` → `alembic revision --autogenerate -m "esquema inicial"` sobre base vacía con todos los modelos importados en `env.py` → renumerar a `002` la migración del disparador de C-09 (ajustar `down_revision`, conservarla tal cual) → verificar `upgrade head` → `alembic check` sin diferencias → `downgrade base` → `upgrade head` → `python seed.py` → `solo_agregado.sql` → capturas C-14/C-15 → `pytest`
  - `test/*.http` con los casos ejercicio C-01…C-19 de la consigna, cada uno con la respuesta esperada; login con `# @no-cookie-jar` y captura del `Set-Cookie` (DD-04)
  - Verificación del ejercicio C-15: detalle de orden con 2 y 4 ítems → mismas consultas (SQL_ECHO en dev); ejercicio C-16: `q` con intento de injection → lista vacía, total 0, sin 500 (RN-18)
  - Evidencia de C-14 (`solo_agregado.sql`) en consola o fragmento según pida el docente (ver pregunta abierta de formato)
  - `README` de entrega: cómo instalar, variables (`env.example`), migrar, seed, arrancar (uvicorn puerto 8000), ejecutar las pruebas, y las credenciales ficticias que deja `seed.py` (`Taller2026` y los emails de cada rol)
  - Checklist final: ninguna entrada inválida → 500; ningún error expone texto de la base (RN-18); login Bearer sin cookie → 401 (DD-04)
- **Dependencias**: C-08, C-09, C-10
- **Governance**: ALTO (la consolidación reescribe el historial de migraciones del entregable)
- **Leer antes**:
  - `knowledge-base/01_vision_y_objetivos.md` (criterios de aceptación del TP)
  - `knowledge-base/02_descripcion_general.md` §API REST (convenciones de códigos y envoltorios)
  - `knowledge-base/06_funcionalidades.md` §Épica 7 (US-031)
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-08 (dos migraciones en el entregable)
  - `knowledge-base/10_preguntas_abiertas.md` §pregunta alta de evidencia

---

## Resumen

| ID | Change | Fase | Deps | Governance |
|----|--------|------|------|------------|
| C-01 | foundation-setup | 0 | — | BAJO |
| C-02 | core-models | 1 | C-01 | CRITICO |
| C-03 | auth | 1 | C-02 | CRITICO |
| C-04 | clientes-vehiculos | 2 | C-03 | MEDIO |
| C-05 | repuestos-stock | 2 | C-03 | ALTO |
| C-06 | usuarios-roles-auditoria | 2 | C-03 | ALTO |
| C-07 | ordenes-crud | 3 | C-04, C-05 | ALTO |
| C-08 | ordenes-lifecycle | 3 | C-07 | CRITICO |
| C-09 | append-only-triggers | 4 | C-07 | CRITICO |
| C-10 | seed-inicial | 5 | C-06, C-07 | MEDIO |
| C-11 | evidencia-entrega | 5 | C-08, C-09, C-10 | ALTO |

**Primer change a implementar**: `C-01` (`foundation-setup`).
