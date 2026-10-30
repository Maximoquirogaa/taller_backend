# Design

## Context

C-01 dejó el servidor arrancando con motor/fábrica en el lifespan, sesión por petición (`expire_on_commit=False`) y Alembic asincrónico inicializado **sin versiones**. Los módulos de dominio existen como esqueletos con docstring vacío. Ver `proposal.md` — Why.

Restricciones que condicionan el diseño: la KB fija la estructura de directorios obligatoria (`app/core/{repository,unit_of_work,paginacion}.py`), el esquema **solo** por Alembic sin `create_all` (DD-08, regla dura), repositorios con `flush()` nunca `commit()` (regla dura), unicidad garantizada por la base vía índices únicos parciales (DD-03, C-19) y roles como filas vigentes en `asignacion_rol` (DD-02, RN-03). Referencias: `knowledge-base/04_modelo_de_datos.md` §usuario/§asignacion_rol/§intento_acceso/§evento_seguridad y `knowledge-base/08_arquitectura_propuesta.md` §Patrones.

## Goals / Non-Goals

**Goals:**
- 4 modelos de acceso (`Usuario`, `AsignacionRol`, `IntentoAcceso`, `EventoSeguridad`) cuyas reglas de unicidad y de catálogo de roles las garantiza PostgreSQL.
- Repositorios genéricos reutilizables por todos los módulos: `BaseRepository[T]` y `SoftDeleteRepository[T]`.
- UoW base asíncrono que confirma o revierte sin cerrar la sesión, listo para que C-03 use un solo UoW en el registro (RN-02).
- Envoltorio de paginación con contrato acotado, usado por todos los listados posteriores.
- Migración 001 con las tablas de acceso y tests automatizados del núcleo (unicidad parcial + transacción).

**Non-Goals:**
- Endpoints, auth, JWT, bcrypt ni dependencias de seguridad (C-03).
- Modelos de clientes/vehículos, repuestos y órdenes (C-04…C-07) — `SoftDeleteRepository` se define acá pero se usa recién allí.
- Disparador de sólo agregado (RN-15) — migración escrita a mano en C-09.
- `seed.py` real (C-10) y evidencias de la consigna (C-11).

## Decisions

### D1 — Modelos de acceso en `app/modules/usuarios/models.py`
Los 4 modelos viven en el módulo `usuarios` (estructura obligatoria de la KB) y comparten el `SQLModel.metadata` que Alembic compara. `IntentoAcceso` y `EventoSeguridad` acompañan ahí por ser auditoría de acceso, sin FK hacia `usuario` (la KB lo explicita: el intento debe sobrevivir al rollback del usuario inexistente — DD-07).
- **Alternativas**: un paquete `app/models/` central (rechazada: rompe la estructura obligatoria y la separación por módulo).

### D2 — Roles como columna `str` con CHECK en la base, no Enum nativo de PG
`AsignacionRol.rol` se modela como texto con `CheckConstraint(rol IN ('ADMIN','RECEPCION','MECANICO','CLIENTE'))`.
- **Alternativas**: `sqlalchemy.Enum` con tipo nativo de PG (rechazada: crea un tipo separado que habría que migrar a mano cada vez que cambia el catálogo, y la consigna pide CHECK) y validación solo en Pydantic (rechazada: RN-01/la evaluación piden garantía de la base, C-19).

### D3 — Índice único parcial declarado en el modelo para que lo genere Alembic
`Index("uq_asignacion_rol_abierta", "usuario_id", "rol", unique=True, postgresql_where=text("revocada_en IS NULL"))` en `__table_args__`. Así el autogenerate lo emite en la migración 001 y `downgrade` lo elimina.
- **Alternativas**: índice escrito a mano en la migración (rechazada: el diff lo vería como sobrante y lo borraría en la siguiente autogeneración).

### D4 — UoW base como clase con `async with`, recibiendo la sesión
`UnitOfWork(session)` implementa `__aenter__`/`__aexit__`: al salir sin excepción → `commit()`; con excepción → `rollback()` y la propaga; **nunca** cierra la sesión (la sesión es de la petición, dueña es `get_session`). Los UoW por módulo (stubs ya creados en C-01) componen este base y exponen sus repositorios — la composición del UoW de `usuarios` la arma C-03 cuando tenga el flujo de registro.
- **Alternativas**: UoW que crea su propia sesión (rechazada: rompe "una operación = una transacción" sobre la sesión de la petición y complica el encadenamiento con `get_session`) y decorador de función (rechazada: menos explícito para el patrón Router/Service/UoW/Repository que evalúa la consigna).

### D5 — Repositorios con `flush()` como único mecanismo de escritura
`BaseRepository[T]` envuelve el modelo y ofrece al menos `get_by_id`, `get_all`, `count`, `add`, `update` y `delete` (nombres fijados por la consigna) siempre con `flush()`: los FK se resuelven y los `IntegrityError` aparecen **dentro** de la transacción del UoW, que es quien decide commit o rollback. `SoftDeleteRepository[T]` hereda de él, filtra los dados de baja y agrega `get_by_id_including_deleted` y `soft_delete` (no existen en la clase base), para `vehiculo`/`repuesto` (C-04/C-05).
- **Alternativas**: `commit()` en el repositorio (rechazada por regla dura del proyecto) y `add()` sin flush (rechazada: los `IntegrityError` aparecerían recién en el commit, tarde para traducirlos a 409 — RN-18).

### D6 — Alembic necesita los modelos importados en `env.py`
`migrations/env.py` importa explícitamente `app.modules.usuarios.models` y usa `SQLModel.metadata` como `target_metadata` (con `include_object` por defecto). Cada change que agregue modelos suma su import — es el punto único que hace posible el autogenerate **y** la consolidación final de C-11 (que regenera `001_esquema_inicial` con todos los modelos ya registrados).
- **Alternativas**: un `app/models.py` que importe todos (rechazada: duplica la estructura por módulo; se puede adoptar más adelante si el import crece).

### D6b — La migración 001 de este change es de desarrollo, no la del entregable
`001` se autogenera contra `taller_test` para poder correr los tests con el esquema real. **C-11 borra todas las versiones y regenera una única `001_esquema_inicial` con las 13 tablas**, conservando aparte la migración del disparador (C-09) como `002`. Consecuencia práctica para este change: no hace falta que la migración sea "bonita" ni definitiva; sí hace falta que `alembic check` quede limpio y que el índice parcial aparezca en el SQL emitido.
- **Alternativas**: esperar a C-11 para tener esquema (rechazada: los tests de C-02…C-09 necesitan tablas y la regla dura prohíbe `create_all`).

### D7 — Fechas con zona horaria y defaults de servidor
Todas las columnas temporales son `datetime` con `timezone=True` (→ `timestamptz`); `cuando`/`desde` usan `server_default=func.now()` para que el reloj lo ponga la base (un solo reloj, sin desfase entre procesos). Donde la app necesite controlar el instante (p. ej. `password_cambiada_en` en C-03), lo setea ella.
- **Alternativas**: defaults de Python (`datetime.now(timezone.utc)`) — aceptados solo donde la app decide el valor.

### D8 — Paginación como parámetros validados por Pydantic + función pura
`paginacion.py` expone: (a) un schema de parámetros `page` (ge=1) y `size` (ge=1, le=100, default 20) con mensajes propios, del que FastAPI deriva el **422** automático, y (b) una función pura `calcular_paginas(total, size)` + constructor del envoltorio `{items,total,page,size,pages}`. Regla de borde (consigna §2.9 / C-16): si `total`=0 → `pages`=1 y página 1 vacía con 200; si `page > pages` → **422** con mensaje propio («La página N no existe: hay M»). Ninguna consulta se arma concatenando datos del usuario (RN-18 / regla dura).
- **Alternativas**: validar a mano en cada router (rechazada: se repite en 8+ endpoints y se olvida) y `limit/offset` en snake_case de PG (mantenemos la conveniencia interna, pero el contrato público es `page`/`size`).

### D9 — Tests del núcleo contra PostgreSQL real, con la base creada por migraciones
`pytest` está instalado; `pytest-asyncio` se agrega a `requirements.txt` como dependencia de desarrollo junto con `pytest`. Los tests corren sobre una base de prueba `taller_test` que **se crea con `alembic upgrade head`** — nunca `create_all` (regla dura). Un fixture limpia las tablas de acceso entre tests (TRUNCATE ... RESTART IDENTITY).
- **Alternativas**: SQLite (rechazada: no soporta el índice único parcial `WHERE` ni reproduce asyncpg) y crear el esquema desde los tests (rechazada: viola DD-08).
- **Supuesto registrado**: el entorno tiene PostgreSQL 16 local accesible con las credenciales del `.env` (mismo criterio que el readiness de C-01); si no, los tests se saltan con mensaje claro en lugar de fallar en rojo.

## Risks / Trade-offs

- **[Autogenerate no emite el índice parcial]** → el diff lo ignora silenciosamente y RN-03 quedaría sin garantía → mitigación: task de verificación que consulta `pg_indexes` y prueba el segundo insert fallando.
- **[`IntegrityError` sin traducir llega a un 500]** → regla dura violada → mitigación: los tests del núcleo no lo cubren (es responsabilidad del servicio en C-03/C-04), pero la decisión D5 garantiza que el error aparezca dentro del UoW, donde se traduce a 409.
- **[Tests que requieren PG arriba]** → CI/otro desarrollador sin base falla → mitigación: supuesto D9 con skip explícito y mensaje, no error críptico.
- **[`SoftDeleteRepository` definido sin uso hasta C-04]** → código no ejercitado por unos changes → mitigación: clase pequeña y testeada con un modelo de prueba interno; se amortiza en C-04/C-05/C-07.
- **[Migración 001 y modelos pueden divergir en cambios futuros]** → mitigación: D6 hace que todo modelo nuevo se registre en `env.py` y se verifique con `alembic check` en cada change; C-11 regenera la migración única a partir de los modelos (D6b), así que la divergencia se corrige en la consolidación.

## Migration Plan

Greenfield: no hay datos que preservar. Despliegue = `alembic upgrade head` sobre base vacía → crea las 4 tablas e índices. Rollback = `alembic downgrade -1` (elimina tablas; sin filas que valgan la pena conservar). La verificación es un arranque de la app + `alembic current` en `head` + corrida de los tests del núcleo.

> Esta migración es **de desarrollo**: el entregable final se consolida en C-11 en `001_esquema_inicial` + `002_disparador_solo_agregado` (ver `CHANGES.md` §Estrategia de migraciones y DD-08).

## Open Questions

- Ninguna que afecte specs, enfoque o desglose de tareas: el nombre de la base de prueba (`taller_test`) y el fixture de limpieza son detalles de tareas y quedan fijados ahí.
