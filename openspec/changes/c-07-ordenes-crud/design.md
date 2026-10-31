# Design: Órdenes de Trabajo — CRUD (c-07-ordenes-crud)

## Context

Ver `proposal.md` (§Why y §Alcance explícito) y `specs/ordenes-crud/spec.md`.

Estado real que condiciona el diseño:

- `app/modules/ordenes/` existe con seis archivos que sólo contienen el docstring de capa (`models.py`, `schemas.py`, `repository.py`, `service.py`, `unit_of_work.py`, `router.py`): C-07 los completa desde cero.
- El head de migraciones es `004_repuestos_stock` (revisiones: `001_esquema_inicial` → `2a785d268e95_clientes_vehiculos` → `004_repuestos_stock`). `CHANGES.md` reserva la `005` para este change.
- `migrations/env.py` importa explícitamente los modelos de cada módulo (D6); sin el import de `app.modules.ordenes` el autogenerate no vería las tablas nuevas.
- Patrón de módulo consolidado: el router construye `UoW…(sesion)`, el servicio abre `async with uow`, los repositorios sólo hacen `flush()`, las excepciones de dominio del módulo se traducen en el router con `from exc` (ver `app/modules/repuestos/*` y `app/modules/clientes/*`).
- `BaseRepository[T]` (`app/core/repository.py`) expone `get_by_id`, `get_all`, `count`, `add`, `update`, `delete`; `SoftDeleteRepository[T]` esconde las filas con `borrado_en` no nulo. `RepositorioVehiculos.get_by_id` y `RepositorioRepuestos.get_by_id` ya aplican baja lógica.
- `ParametrosPagina`, `PaginaDe[T]` y `construir_pagina` (`app/core/paginacion.py`) son el contrato de todos los listados, con 422 para `page`/`size` inválidos y para páginas inexistentes.
- `usuario_actual` resuelve 401 y roles vigentes de la base en cada petición; `requiere_rol(*roles)` resuelve 403 (RN-04). El control de cambio obligatorio está montado una vez sobre `router_protegido` (DD-10).
- `test/conftest.py` crea y migra `taller_test` **sólo** con `alembic upgrade head` y trunca tablas por lista explícita. Los `conftest.py` de módulo repiten la lista y agregan un helper `autenticar_usuario`.

## Goals / Non-Goals

**Goals:**

- Dejar el esquema de las cuatro tablas en una migración de desarrollo `005`, reproducible con upgrade/downgrade y alineada con los modelos SQLModel.
- Implementar la apertura atómica de una orden (orden + ítems + historial) con precios y total calculados exclusivamente por el servidor.
- Garantizar que el detalle se arme con un número fijo de consultas, verificable con el ejercicio C-15 (2 vs 4 ítems).
- Respetar la separación de permisos: staff para tablero y apertura, dueño o staff para detalle, cualquier autenticado para catálogo y órdenes propias.
- Dejar el catálogo de estados como dato de sólo lectura que la migración crea vacío (DD-01) y que C-10 puebla.

**Non-Goals:**

- Transiciones de estado, asignación de mecánico y descuento de stock (C-08, RN-11/RN-12/RN-13).
- Disparadores de sólo agregado sobre `historial_estado_orden` (C-09, RN-15); en C-07 la protección es sólo de repositorio (no se exponen `update`/`delete`).
- Carga inicial del catálogo (C-10) y consolidación de migraciones (C-11).
- Concurrencia optimista, bloqueos de fila o control de versiones (fuera del alcance del TP, DD-11).
- Endpoints de edición o baja de órdenes.

## Decisions

### D1. Capability nueva `ordenes-crud`

- **Decisión**: publicar una única capability `ordenes-crud` con seis requirements (apertura, catálogo, listado, detalle, órdenes propias y errores controlados).
- **Por qué**: la convención del proyecto es change → capability homónima (`c-05` → `repuestos-stock`, `c-06` → `usuarios-roles-auditoria`) y todas las rutas de este change comparten el mismo límite: el ciclo de lectura/creación de órdenes. No se modifica `clientes-vehiculos`, `repuestos-stock` ni `pagination`: C-07 los consume sin cambiar sus garantías.
- **Alternativas**: crear dos capabilities (`ordenes-crud` y `estados-orden`) — se descartó porque el catálogo es un requisito de apoyo de la misma capability y no un dominio autónomo.

### D2. Esquema de las cuatro tablas

- **Decisión**:

  | Tabla | Columnas y restricciones |
  |---|---|
  | `estado_orden` | `codigo` (texto, PK), `descripcion` (texto, máx. 120), `posicion` (int, UNIQUE, CHECK > 0), `es_final` (bool, NOT NULL, default `false`) |
  | `orden_trabajo` | `id` (PK), `vehiculo_id` (FK `vehiculo.id`, indexada), `mecanico_id` (FK `usuario.id`, nullable, indexada), `estado` (FK `estado_orden.codigo`, indexada), `falla` (texto, máx. 500), `creada_en` (`timestamptz`, default `now()` UTC), `total` (`NUMERIC(12,2)`, CHECK >= 0) |
  | `item_orden` | `id` (PK), `orden_id` (FK `orden_trabajo.id`, indexada), `repuesto_id` (FK `repuesto.id`, indexada), `cantidad` (int, CHECK > 0), `precio_unitario` (`NUMERIC(10,2)`, CHECK > 0), UNIQUE `(orden_id, repuesto_id)` |
  | `historial_estado_orden` | `id` (PK), `orden_id` (FK, indexada), `desde_estado` (FK `estado_orden.codigo`, nullable), `hasta_estado` (FK `estado_orden.codigo`, NOT NULL), `usuario_id` (FK `usuario.id`, nullable, indexada), `cuando` (`timestamptz`, default `now()` UTC) |

- **Por qué**: replica literalmente `knowledge-base/04_modelo_de_datos.md` §estado_orden/§orden_trabajo/§item_orden/§historial_estado_orden. La PK textual de `estado_orden` hace que la FK de `orden_trabajo.estado` y las dos de historial sean la garantía de RN-19. El UNIQUE compuesto de `item_orden` es la garantía de «sin repuestos repetidos» de RN-10, no una validación de aplicación. Los CHECK replican los de repuestos y evitan totales/cantidades absurdos.
- **Detalle de nulabilidad**: `desde_estado` es nulo sólo en la fila inicial (nulo → PENDIENTE); `usuario_id` queda nullable para permitir eventos de `SISTEMA` en `seed.py` (C-10) y para no bloquear la carga inicial; las filas creadas por la API siempre lo llevan.
- **Alternativas**: `orden_trabajo.total` como columna calculada/`GENERATED` — se descartó porque la KB pide que el total lo calcule el servidor y el cálculo depende de los ítems ya insertados; `item_orden` sin UNIQUE y deduplicación en Python — rechazada porque la base debe garantizar la regla (excepción global del proyecto).

### D3. Catálogo de estados vacío y su 409 (DD-01, RN-19)

- **Decisión**: la migración `005` crea `estado_orden` **sin** `INSERT`. `RepositorioEstadosOrden` no hereda de `BaseRepository`, no expone `add/update/delete`, y ofrece sólo `listar()` (orden por `posicion`), `get_por_codigo(codigo)` y `existe_catalogo()`. Al abrir una orden, el servicio consulta el catálogo **antes** de escribir; si no hay filas lanza `CatalogoEstadosVacio` → 409 con mensaje propio.
- **Por qué**: DD-01 separa esquema (migración) de datos iniciales (seed). El 409 evita crear una orden cuya FK de estado fallaría con un `IntegrityError` genérico y da un mensaje de dominio comprensible (RN-19). Un repositorio de sólo lectura hace imposible que un endpoint edite el catálogo por accidente.
- **Alternativas**: sembrar el catálogo en la migración — viola DD-01 y haría que C-10 no pudiera ser idempotente desde cero; un CHECK con la lista de estados — descartado en DD-01 porque no lleva `posicion`/`es_final` ni se consulta desde la API.

### D4. Apertura atómica: el servidor copia precios y calcula el total (RN-10)

- **Decisión**: `POST /ordenes` recibe `EntradaCrearOrden` con `vehiculo_id`, `falla` e `items[{repuesto_id, cantidad}]`. El servicio, dentro de un único `async with UoWOrdenes`:

  1. verifica catálogo no vacío;
  2. carga el vehículo vigente (`RepositorioVehiculos.get_by_id`, que oculta bajas);
  3. carga **en una sola consulta** todos los repuestos activos pedidos (`get_activos_por_ids`), y compara ids para detectar inexistentes/dados de baja;
  4. detecta repuestos repetidos en el payload y lanza `ConflictoComposicion` → 409;
  5. crea `OrdenTrabajo` con `estado="PENDIENTE"`, `creada_en=now(UTC)` y `total` calculado como `sum(precio × cantidad)` con `Decimal` cuantizado a 2 decimales;
  6. crea un `ItemOrden` por ítem copiando `precio_unitario = repuesto.precio` (nunca el del cliente);
  7. crea `HistorialEstadoOrden(desde_estado=None, hasta_estado="PENDIENTE", usuario_id=actor)`.

  Todo se confirma al salir del bloque; cualquier excepción revierte las tres clases de escritura.
- **Por qué**: es la traducción directa de Flujo 4 y RN-10. Copiar el precio en el ítem conserva el valor histórico aunque el repuesto cambie de precio después (RN-20). El total se calcula una sola vez y no se recalcula en lecturas.
- **Alternativas**: calcular el total en el router o en el schema — se descartó porque el contrato no debe contener lógica de negocio y el servicio es el único que ve los precios vigentes; recalcular el total al leer — contradice la semántica de precio copiado.

### D5. Códigos de error de la apertura

- **Decisión**: catálogo vacío, repuesto inexistente/dado de baja y repuesto repetido → **409** (`CatalogoEstadosVacio`, `RepuestoNoDisponible`, `ConflictoComposicion`). Vehículo inexistente/dado de baja → **404** (`VehiculoNoEncontrado`). Contrato inválido (sin ítems, cantidad ≤ 0, campos extra, `precio_unitario`/`total`/`estado` en el cuerpo) → **422** antes de abrir el UoW. `IntegrityError` en la inserción → **409** traducido en el router, sin texto de PostgreSQL.
- **Por qué**: US-023 fija 409 para repuesto inexistente y catálogo vacío; 422 para «sin ítems» por ser un fallo de contrato. La KB no fija el código del vehículo inexistente: se elige 404 por coherencia con el resto de la API (recurso referenciado que no existe). El 409 de repetidos se alinea con la restricción UNIQUE y con el resultado observable de una carrera.
- **Alternativas**: vehículo inexistente → 409 — posible, pero un 404 es más preciso y no rompe ninguna regla; repetidos → 422 — se descartó porque la garantía final es la restricción de la base y el mismo caso por carrera respondería 409; usar 422 y 409 para el mismo hecho sería inconsistente.

### D6. Listado: paginación estándar y estado validado por contrato

- **Decisión**: `GET /ordenes` usa `ConsultaOrdenes(ParametrosPagina)` con un campo `estado: EstadoOrdenCodigo | None`, donde `EstadoOrdenCodigo` es un `StrEnum` de Python con los cuatro códigos del catálogo. Un valor fuera del enum lo rechaza FastAPI con 422 antes de consultar la base. El repositorio devuelve `(items, total)` con el mismo filtro, orden `creada_en DESC, id DESC`, y el servicio arma la página con `construir_pagina`. La respuesta es `PaginaDe[SalidaOrdenResumen]` con `patente` precargada por `joinedload` para no hacer una consulta por fila.
- **Por qué**: cumple US-024 y la spec `pagination` sin inventar un envoltorio nuevo. El enum de contrato es la fuente del 422 («estado fuera del contrato»); el catálogo de la base sigue siendo la fuente de verdad de los estados existentes. Si el catálogo está vacío, el filtro devuelve una página vacía con 200 (no es un error de contrato).
- **Alternativas**: validar el estado consultando la base y responder 422 si no existe — se descartó porque mezcla «fuera del contrato» con «catálogo vacío» y agrega una consulta previa; aceptar `estado` como texto libre — no cumple el 422.
- **Nota de contrato**: `size` por defecto 20, `1..100`; página inexistente → 422 con el mensaje de `construir_pagina`.

### D7. Detalle con precarga y número fijo de consultas (C-15)

- **Decisión**: `RepositorioOrdenes.get_detalle(orden_id)` emite **una** consulta base con:

  ```python
  select(OrdenTrabajo)
      .where(OrdenTrabajo.id == orden_id)
      .options(
          joinedload(OrdenTrabajo.vehiculo).joinedload(Vehiculo.cliente),
          joinedload(OrdenTrabajo.estado),
          selectinload(OrdenTrabajo.items).joinedload(ItemOrden.repuesto),
          selectinload(OrdenTrabajo.historial).joinedload(HistorialEstadoOrden.desde_estado),
          selectinload(OrdenTrabajo.historial).joinedload(HistorialEstadoOrden.hasta_estado),
      )
  ```

  `joinedload` resuelve las relaciones muchos-a-uno en la misma sentencia; `selectinload` resuelve las colecciones con una sentencia adicional cada una. El total es **4 SELECT** (orden+vehículo+cliente+estado, ítems, historial, estados del historial si se precargan por separado) y no crece con la cantidad de ítems.
- **Por qué**: la regla dura prohíbe depender de lazy loading y US-025 exige consultas fijas. `selectinload` sobre la colección de ítems evita el N+1 clásico; el repuesto de cada ítem se resuelve en la misma sentencia de ítems con `joinedload`. El test de C-15 cuenta sentencias con un listener `before_cursor_execute` y compara 2 vs 4 ítems: deben coincidir.
- **Alternativas**: `selectinload` para todo — funciona, pero agrega sentencias para relaciones muchos-a-uno; `lazy="selectin"` en los modelos — oculta el costo y puede disparar cargas no deseadas en otras lecturas; cargar ítems con una consulta por ítem — es exactamente el N+1 que C-15 penaliza.
- **Detalle del contrato de salida**: `SalidaOrdenDetalle` incluye `vehiculo` (`SalidaVehiculo`), `cliente` (`SalidaClienteBreve`: id, nombre, documento, teléfono), `items` (`SalidaItemOrden` con repuesto anidado, cantidad, `precio_unitario` y `subtotal`) e `historial` (`SalidaHistorialEstado` con desde/hasta, usuario y `cuando`). El subtotal se calcula en el schema de salida a partir de columnas persistidas, no se guarda.

### D8. Permisos: staff vs dueño y distinción 403/404 (RN-17)

- **Decisión**:

  | Ruta | Autorización |
  |---|---|
  | `POST /ordenes` | `requiere_rol("RECEPCION", "ADMIN")` |
  | `GET /ordenes` | `requiere_rol("ADMIN", "RECEPCION", "MECANICO")` |
  | `GET /ordenes/{id}` | sólo `usuario_actual`; el servicio decide: staff (ADMIN/RECEPCION/MECANICO vigente) ve cualquiera; CLIENTE sólo si `orden.vehiculo.cliente.usuario_id == usuario.id`; si no → 403 |
  | `GET /estados-orden` | sólo `usuario_actual` (cualquier autenticado) |
  | `GET /mis-ordenes` | sólo `usuario_actual`; filtra por la ficha del usuario |

  El detalle busca primero la orden: si no existe → 404. Después evalúa la relación con el vehículo: si existe pero es ajena → 403. La ruta no lleva `requiere_rol` porque un CLIENTE debe poder entrar; la comprobación de rol se hace en el servicio con los `roles_vigentes` de la petición.
- **Por qué**: 401 (sin sesión) lo resuelve `usuario_actual`; 403 (sin permiso) lo resuelven `requiere_rol` o el servicio. Un CLIENTE sin rol de staff no debe recibir 403 genérico antes de que el servicio pueda reconocerlo como dueño. El orden 404 → 403 evita filtrar la existencia de una orden a un usuario que no es su dueño; es el mismo criterio que usa C-08 para cancelar (permiso antes que estado).
- **Alternativas**: `requiere_rol` en el detalle y una ruta separada para clientes — duplicaría lógica y rutas; devolver 404 en lugar de 403 para órdenes ajenas — oculta mejor la existencia, pero la KB pide explícitamente 403.

### D9. `/mis-ordenes` sin ficha de cliente

- **Decisión**: `RepositorioOrdenes.buscar_por_usuario(usuario_id, offset, limit)` hace `join` de `OrdenTrabajo → Vehiculo → Cliente` y filtra `Cliente.usuario_id == usuario_id`. El servicio resuelve la ficha con `RepositorioClientes.get_por_usuario_id`; si no existe, devuelve una página vacía con 200 (`total=0`, `pages=1`) sin consultar órdenes.
- **Por qué**: RN-17 dice que un cliente ve las órdenes de sus vehículos «y ninguna otra»; un usuario de staff sin ficha no es dueño de nada y una lista vacía es la respuesta correcta, no un 404. Mantiene el mismo envoltorio y los mismos 422 de paginación que el resto.
- **Alternativas**: 404 si no tiene ficha — confunde «no tenés ficha» con «no existe el recurso» y rompe la simetría con `GET /mis-vehiculos`, que hoy devuelve lista vacía.

### D10. UoW del módulo y escrituras en un solo bloque

- **Decisión**: `UoWOrdenes(UnitOfWork)` expone `ordenes`, `items`, `historial`, `estados` (sólo lectura) y reutiliza `vehiculos` (de `clientes`) y `repuestos` (de `repuestos`) para las validaciones de referencia. Todos los repositorios heredan de `BaseRepository` salvo `RepositorioEstadosOrden`. Ningún método llama a `commit()`: sólo `add`, `update` y `flush()`. El router construye `UoWOrdenes(session)` y lo pasa al servicio; el servicio abre `async with`.
- **Por qué**: cumple la regla dura del UoW y evita duplicar consultas de vehículos/repuestos. La apertura de orden es una multi-escritura (orden + N ítems + historial) que debe confirmarse o revertirse completa (RN-10/RN-02 por analogía). Reutilizar los repositorios existentes mantiene una sola definición de «vigente» (baja lógica) para vehículos y repuestos.
- **Alternativas**: un UoW sólo con repositorios de órdenes y consultas SQL duplicadas para vehículo/repuesto — se descartó por duplicación y riesgo de divergencia; que el servicio construya el UoW — contradice el patrón del proyecto.

### D11. Migración de desarrollo 005 y consolidación en C-11

- **Decisión**: crear `migrations/versions/005_ordenes_crud.py` con `revision = "005_ordenes_crud"` y `down_revision = "004_repuestos_stock"`. El docstring dice explícitamente «migración DE DESARROLLO 005 — C-11 la consolida». `upgrade()` crea en orden: `estado_orden`, `orden_trabajo`, `item_orden`, `historial_estado_orden` (con FKs, CHECK, UNIQUE e índices); **no inserta filas**. `downgrade()` las elimina en orden inverso. Se agrega `from app.modules.ordenes import models as _modelos_ordenes` en `migrations/env.py`.
- **Por qué**: la regla dura exige que el esquema salga **sólo** de Alembic y que el entregable tenga exactamente `001` + `002`; C-11 borra las migraciones de desarrollo y regenera `001` con todos los modelos. Mantener la `005` incremental permite correr los tests contra el esquema real sin adelantar la consolidación. El catálogo vacío es requisito de DD-01 y de C-10.
- **Riesgo controlado**: si el autogenerate no detecta el UNIQUE compuesto o los CHECK por diferencias de metadata, se corrige el **modelo** y se regenera la migración; nunca se agrega un `ALTER` suelto.
- **Alternativas**: consolidar ya en C-07 — se descartó porque C-11 es el change dueño de la consolidación y necesita que C-08/C-09/C-10 terminen; crear las tablas con `create_all` — prohibido.

### D12. Estrategia de tests y verificación de consultas fijas

- **Decisión**: `test/ordenes/conftest.py` replica el patrón de `test/repuestos/conftest.py`, suma las cuatro tablas al `TRUNCATE` (con `estado_orden` incluida) y agrega una fixture `catalogo` que inserta los cuatro estados en orden. Los tests de modelo cubren PK/UNIQUE/CHECK/FK; los de repositorio cubren el catálogo de sólo lectura, el filtro y el conteo de sentencias; los de router cubren cada escenario del spec. El conteo de C-15 se hace con un listener de SQLAlchemy sobre el motor de pruebas que incrementa un contador en `before_cursor_execute` y se compara entre una orden de 2 ítems y una de 4.
- **Por qué**: TDD estricto en el apply: cada tarea escribe el test primero y lo ve fallar por la razón correcta (tabla inexistente, método ausente, 404/405 en vez de 201). La fixture de catálogo es indispensable porque la migración lo deja vacío (DD-01); usarla mantiene el 409 de catálogo vacío como un test explícito y no como un efecto colateral.
- **Alternativas**: sembrar el catálogo en el `conftest` global — rompería el aislamiento y haría imposible el test de catálogo vacío; contar consultas con `SQL_ECHO` y parsear stdout — frágil; usar un contador de eventos es determinista.

## Risks / Trade-offs

- **[Código de vehículo inexistente en `POST /ordenes` no fijado por la KB]** → Se elige 404 (D5) y se documenta; si el usuario prefiere 409, el cambio es localizado en el router y en un escenario del spec.
- **[Repuesto repetido: 409 vs 422]** → Se elige 409 porque la garantía final es el UNIQUE compuesto y una carrera no puede responder 422 de forma consistente. El contrato no puede detectar duplicados sin lógica de servicio.
- **[El catálogo vacío impide abrir órdenes hasta C-10]** → Es el comportamiento buscado (DD-01/RN-19). Mitigación: fixture de tests con los cuatro estados y `seed.py` en C-10; el 409 es parte del contrato, no un defecto.
- **[Número exacto de consultas del detalle depende del mapeo de relaciones]** → Mitigación: el test de C-15 no fija un número mágico, sino que compara 2 vs 4 ítems y exige igualdad (y un techo razonable, p. ej. ≤ 6 SELECT); si una relación nueva rompe la igualdad, el test falla.
- **[UNIQUE compuesto y CHECK pueden no autogenerarse igual en la consolidación]** → Mitigación: `alembic check` en C-11 y comparación de la metadata; el modelo es la fuente de verdad, nunca un `ALTER` manual.
- **[`historial_estado_orden.usuario_id` nullable permite filas sin actor]** → Mitigación: la API siempre lo escribe; la nulabilidad existe sólo para el seed de C-10 y se documenta en el modelo.
- **[Duplicar tablas en las listas de `TRUNCATE` de tres `conftest.py`]** → Mitigación: C-07 actualiza `test/conftest.py` y los `conftest.py` de clientes/repuestos/usuarios con las nuevas tablas; el test de suite completa detecta un truncado incompleto por FK.
- **[`falla` con límite de 500 caracteres no fijado por la KB]** → Es un límite defensivo del contrato; si la consigna exigiera otro, se ajusta en el schema y en la migración en el mismo change.

## Migration Plan

1. Agregar los modelos y el import en `migrations/env.py`.
2. Generar `005_ordenes_crud` con `alembic revision --autogenerate -m "ordenes crud"` sobre una base en `004_repuestos_stock` y revisar el diff (orden de creación, FKs, CHECK, UNIQUE e índices). Confirmar que no haya `INSERT` en `estado_orden`.
3. Aplicar `alembic upgrade head` sobre `taller_test` (lo hace la fixture de sesión) y verificar `alembic downgrade -1` → `alembic upgrade head` reproducibles.
4. Desplegar código: montar `router_ordenes` en `router_protegido` (`main.py`).
5. Rollback de código: quitar el `include_router`. Rollback de esquema: `alembic downgrade 004_repuestos_stock` (sólo en desarrollo; en producción el rollback es la consolidación de C-11).
6. No tocar `migrations/versions/001…004`: la consolidación es de C-11.

## Open Questions

- Ninguna bloqueante. Quedan como supuestos explícitos: vehículo inexistente → 404, repetido → 409, `falla` ≤ 500 caracteres y `historial.usuario_id` nullable. Si el docente fija otro código o límite, se ajusta en el apply sin cambiar la arquitectura.
