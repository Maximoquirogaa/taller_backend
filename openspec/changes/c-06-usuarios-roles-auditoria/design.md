# Design: Usuarios, Roles y Auditoría (c-06-usuarios-roles-auditoria)

## Context

Ver `proposal.md` y `specs/usuarios-roles-auditoria/spec.md`. C-03 dejó el módulo `app/modules/usuarios/` con `models.py` (`Usuario`, `AsignacionRol`, `IntentoAcceso`, `EventoSeguridad`), `repository.py` (`RepositorioUsuarios.get_por_email`, `RepositorioRoles.asignar`/`existe_abierta`, `roles_vigentes_de`), `schemas.py`/`service.py`/`router.py` sólo para `/auth` y un `UoWUsuarios` con `usuarios`, `roles` e `intentos` — **sin `eventos`**.

Estado real que condiciona el diseño:

- `/usuarios` y `/eventos` no existen; `evento_seguridad` no tiene ningún emisor en el proyecto (C-03 no audita login ni cambio de contraseña).
- `usuario`, `asignacion_rol` y `evento_seguridad` ya existen desde `migrations/versions/001_esquema_inicial.py`, con el índice único parcial `uq_asignacion_rol_abierta (usuario_id, rol) WHERE revocada_en IS NULL` (RN-03). El head es `004_repuestos_stock` y el número `005` está reservado en `CHANGES.md` para C-07.
- `RepositorioRoles` no tiene `revocar`, `get_abierta` ni cierre de asignaciones vencidas.
- Seguridad ya resuelta: `usuario_actual` (401), `requiere_rol(*roles)` (403) y `exige_sin_cambio_pendiente` (403, montado una sola vez sobre `router_protegido`); los roles se leen de la base en cada petición vía `roles_vigentes_de`, por lo que revocar alcanza a la sesión abierta (RN-04).
- Patrón de módulo a seguir: `app/modules/repuestos/*` (router construye el UoW con la dependencia de sesión, servicio lo abre con `async with`, excepciones de dominio por módulo traducidas en el router con `from exc`).
- Paginación disponible: `ParametrosPagina`, `PaginaDe[T]` y `construir_pagina` en `app/core/paginacion.py`.

## Goals / Non-Goals

**Goals:**

- Exponer las cuatro rutas de administración de personal y auditoría bajo `router_protegido`, con `requiere_rol("ADMIN")` como única autorización (sin leer roles del token).
- Implementar el ciclo de vida de `asignacion_rol` (abrir, cerrar por vencimiento al reasignar y revocar escribiendo `revocada_en`) sin borrar nunca una fila.
- Garantizar la autoprotección del ADMIN en la capa de servicio, con independencia de la ruta.
- Escribir `evento_seguridad` en alta de personal, otorgamiento, revocación **y** cambio de contraseña, con `actor` igual al email de quien actuó.
- Dejar el contrato listo para tests TDD: cada comportamiento observable del spec tiene su archivo y su caso de prueba nombrado en `tasks.md`.

**Non-Goals:**

- Listado, baja o edición de usuarios (`GET/PATCH/DELETE /usuarios` no están en la consigna; quedan fuera de C-06).
- Recuperación o reseteo de contraseña por un ADMIN: la contraseña provisoria sólo se entrega en el alta.
- Regenerar sesiones o invalidar tokens al revocar un rol: se resuelve con la relectura de roles en cada petición (RN-04), no con una lista de revocación.
- Migración de esquema, triggers de sólo-agregado sobre `evento_seguridad` (C-09) y consolidación de migraciones (C-11).

## Decisions

### 1. Capability nueva `usuarios-roles-auditoria`, sin delta sobre `user-auth`

- **Decisión**: el delta se publica como capability nueva `usuarios-roles-auditoria`. `user-auth` conserva intactas sus 12 requirements.
- **Por qué**: `user-auth` describe autenticación (credenciales, sesión, cookies, RN-06/07/08/09) y la *aplicación* de RBAC en cada petición; no describe la administración del directorio de identidades. Los requisitos de C-06 (unicidad de rol abierto, autoprotección del ADMIN, auditoría consultable) son un límite cohesivo distinto que puede crecer sin tocar auth. Además `CHANGES.md` §C-06 ya nombra el change `usuarios-roles-auditoria` y la convención archivada es change → capability homónima (`c-05` → `repuestos-stock`).
- **Sobre el cambio de contraseña**: C-06 instrumenta `service.cambiar_password` para que escriba un evento, pero ninguna garantía de `user-auth` cambia: sigue respondiendo 200 con cookie nueva, sigue invalidando tokens anteriores (RN-07) y sigue devolviendo 401/422 en los mismos casos. La conducta nueva (“un cambio exitoso deja un evento”) se especifica como requirement de la capability de auditoría.
- **Alternativas**: (a) extender `user-auth` con 7 requirements nuevos — se descartó porque mezcla administración de personal con autenticación y hace crecer una capability que ya tiene 12 requirements heterogéneos; (b) delta `MODIFIED` sobre el requirement de cambio de contraseña de `user-auth` — se descartó porque obliga a copiar el bloque completo para no cambiar su significado, y el comportamiento observable de auth no se altera.

### 2. El evento de auditoría vive en la misma transacción del cambio

- **Decisión**: alta de personal, otorgamiento, revocación y cambio de contraseña escriben su `evento_seguridad` **dentro** del mismo `UoWUsuarios` que el cambio de negocio (una sola `commit`). Si la operación falla, no queda ni el cambio ni el evento.
- **Por qué**: la auditoría de C-06 es de *cambios de dominio*: el evento debe describir un hecho que existe. Un evento huérfano (“se otorgó el rol X”) sobre una transacción revertida es un falso positivo que rompe la trazabilidad que pide US-011. Es la misma lógica con la que RN-02, RN-13 y RN-20 exigen multi-escrituras en un solo bloque.
- **Excepción documentada**: `intento_acceso` (DD-07) sí usa sesión propia porque cuenta *fallos*, es decir hechos que existen precisamente cuando la transacción principal revierte. `evento_seguridad` no cuenta fallos: sólo registra cambios confirmados, así que no hereda esa excepción.
- **Alternativas**: sesión y transacción propias (patrón DD-07) — se descartó por los eventos huérfanos; `BackgroundTasks` — se descartó porque perdería el evento si el proceso muere tras responder y no tiene sentido en v1 sin colas (DD-07).

### 3. Sin migración nueva: el `005` pertenece a C-07

- **Decisión**: C-06 no crea migración. Usa `usuario`, `asignacion_rol` y `evento_seguridad` tal como los dejó `001_esquema_inicial` (más el índice parcial `uq_asignacion_rol_abierta`), y no registra modelos nuevos en `migrations/env.py`.
- **Por qué**: (a) el esquema ya cubre todo lo que el cambio necesita (incluido el índice que garantiza RN-03); (b) `CHANGES.md` §C-07 reserva explícitamente la migración de desarrollo `005` para órdenes de trabajo, y C-11 consolida el entregable en `001` + `002`; (c) crear un `005` vacío o renumerar migraciones introduce riesgo de divergencia de `alembic_version` en `taller_test` sin beneficio funcional.
- **Consecuencia**: los tests de C-06 corren contra el head actual (`004_repuestos_stock`) y `test/usuarios/conftest.py` trunca las tablas de acceso existentes sin agregar tablas.
- **Alternativas**: migración con un `CHECK` adicional de `vence_en > desde` — se descartó: no está en la KB y un vencimiento pasado ya se rechaza con 422 en el contrato.

### 4. Semántica de “abierta” vs “vigente” al reasignar un rol (RN-03)

- **Decisión**: `RepositorioRoles.get_abierta(usuario_id, rol)` devuelve la fila con `revocada_en IS NULL` (que es exactamente lo que indexa `uq_asignacion_rol_abierta`). El servicio distingue:
  - fila abierta **vigente** (`vence_en` nulo o futuro) → `409` con mensaje propio;
  - fila abierta **vencida** (`vence_en <= now()`) → se **cierra** escribiendo `revocada_en = now()` y se abre la nueva fila, todo en el mismo UoW;
  - sin fila abierta (revocada) → se abre la nueva directamente.
- **Por qué**: el índice parcial sólo mira `revocada_en`, así que una fila vencida bloquea el `INSERT` aunque ya no otorgue permisos (`roles_vigentes_de` la ignora). Cerrarla con `revocada_en` es la única columna de cierre existente y mantiene la historia completa (“desde – hasta”), tal como pide la KB: “Reasignar un rol vencido cierra la fila anterior y abre otra”.
- **Alternativas**: (a) devolver 409 también para la fila vencida — contradice US-009 y dejaría al ADMIN sin forma de re-otorgar el rol; (b) `UPDATE vence_en = now()` — falsea el vencimiento pactado; (c) borrar la fila — prohibido (la fila nunca se borra).
- **Trade-off**: `revocada_en` pasa a significar “asignación cerrada” (por revocación o por reasignación de una vencida). El evento de auditoría distingue el motivo (`rol_otorgado` vs `rol_revocado`), y para una fila vencida el cierre es un efecto secundario del otorgamiento, no una revocación.

### 5. Revocación escribe `revocada_en`, nunca `DELETE`

- **Decisión**: `RepositorioRoles.revocar(asignacion, cuando)` delega en `SoftDeleteRepository.soft_delete` con `campo_baja = "revocada_en"` (el docstring del repositorio base ya anticipa este uso) o en un `update` equivalente; el servicio **nunca** llama a `delete`. `RepositorioRoles` no hereda de `SoftDeleteRepository` (seguiría escondiendo las filas revocadas en el historial que necesita `get_historial`): expone `get_abierta`, `get_historial` y `revocar` explícitos.
- **Por qué**: `access-data-model` (“Revocación conserva la fila”) y RN-04 necesitan que el historial siga siendo consultable; el borrado físico es irreversible y rompería la auditoría.
- **Alternativas**: heredar de `SoftDeleteRepository` con `campo_baja="revocada_en"` — se descartó porque `count`/`get_all` filtrarían las filas revocadas y C-06 necesita verlas para decidir y para auditar.

### 6. Autoprotección en el servicio, antes de escribir (RN-05)

- **Decisión**: el servicio de revocación recibe `actor_id` (id del ADMIN autenticado, tomado de `UsuarioAutenticado.id`, nunca de la ruta) y `actor_email`; si `actor_id == usuario_id` y `rol == "ADMIN"` lanza `AutorrevocacionProhibida` → el router responde **409**. La comprobación ocurre antes de tocar la fila y antes de escribir el evento.
- **Por qué**: la regla es de negocio (RN-05), no de autorización de ruta; ponerla en el servicio la hace válida para cualquier futura ruta que revoque roles, y el 409 (y no 403) es lo que fija la KB. Comparar contra el id de la sesión evita que un ADMIN revoque a otro ADMIN (eso sigue permitido) o se revoque a sí mismo.
- **Alternativas**: dependencia de ruta dedicada — se descartó porque duplicaría la regla por endpoint y no cubriría usos internos; 403 — contradice RN-05/US-010.
- **Nota**: no se implementa un “último administrador” global; RN-05 sólo prohíbe la autorrevocación del propio ADMIN.

### 7. Contrato de vencimiento con zona horaria (US-009)

- **Decisión**: `EntradaAsignarRol.vencimiento: AwareDatetime | None` (Pydantic v2 rechaza `datetime` sin `tzinfo` con 422) y un `field_validator` que exige `vencimiento > datetime.now(UTC)`; el servicio repite la comprobación defensiva y lanza `VencimientoInvalido` → 422. Se normaliza a UTC antes de persistir (todas las columnas son `timestamptz`).
- **Por qué**: la KB exige “zona horaria obligatoria, futuro”. Validar en el contrato garantiza el 422 antes de abrir la transacción y el chequeo en el servicio evita que un llamador interno esquive la regla.
- **Alternativas**: validar sólo en el servicio (el 422 llegaría después de abrir el UoW) o aceptar `date` — ambas descartadas.

### 8. Router construye el UoW; el servicio lo abre (bcrypt antes del `async with`)

- **Decisión**: cada endpoint crea `uow = UoWUsuarios(session)` y llama al servicio con `uow` como primer argumento (patrón `repuestos`). En `crear_empleado` el servicio calcula `hash_password` **antes** de `async with uow:`; las excepciones de dominio del módulo se traducen en el router (`409`, `404`, `422`) con `from exc`.
- **Por qué**: cumple las dos reglas duras a la vez — “el router construye el UoW con dependencia; el servicio lo abre con `async with`” y “el hash se calcula antes de abrir el UoW”. `IntegrityError` (email duplicado, índice parcial de rol) se traduce a 409 en el router, sin texto de PostgreSQL (RN-01/RN-18).
- **Alternativas**: que el servicio construya `UoWUsuarios(sesion)` (como hace C-03) — funciona, pero repite la construcción en cada servicio y se aleja del patrón del módulo más reciente; se mantiene **sólo** en el `cambiar_password` existente, que ya calcula el hash fuera de la transacción y sólo se instrumenta con el evento.

### 9. `GET /eventos` sobre el envoltorio existente

- **Decisión**: `RepositorioEventos.buscar_paginado(offset, limit)` devuelve `(items, total)` ordenando por `cuando DESC, id DESC`; el servicio arma la página con `construir_pagina`, que aplica `validar_pagina` (422 si la página no existe). `page`/`size` los valida `ParametrosPagina` (422 en `page=0`, `size=500`, no enteros, campos extra).
- **Por qué**: la spec `pagination` es el contrato de *todos* los listados; reutilizarla da el mismo formato y los mismos 422 sin inventar otro.
- **Alternativas**: devolver `list[SalidaEvento]` — descartado por violar US-011 (“paginado con envoltorio”).

### 10. `eventos` en el UoW y mensajes propios del módulo

- **Decisión**: `UoWUsuarios` suma `eventos: RepositorioEventos`; los mensajes de error de dominio se declaran como constantes en `app/modules/usuarios/service.py` (mismo estilo que `app/modules/repuestos/service.py`), no en `app/core/mensajes_auth.py`, porque no son mensajes de sesión.
- **Alternativas**: módulo `mensajes.py` nuevo — se descartó para no fragmentar mensajes de un módulo chico; reusar `mensajes_auth` — mezclaría dominios.

### 11. Limpieza obligatoria de un `print` de depuración

- **Decisión**: eliminar `print(f"[DEBUG-401] ...")` de `app/core/dependencies.py:105`, que hoy filtra el id y el `repr` del usuario por stdout en cada 401.
- **Por qué**: es una fuga de datos internos a logs fuera del contrato de observabilidad y el propio proyecto prohíbe exponer detalles internos; el `_falla_sesion()` siguiente ya cubre el caso.
- **Alternativas**: convertirlo en `logger.debug` — se descartó: el `repr` del usuario incluiría datos de la fila y no aporta al diagnóstico del 401, que ya es determinista.

## Risks / Trade-offs

- **[`revocada_en` con doble significado (revocación vs cierre de vencida)]** → Mitigación: el evento de auditoría registra la acción (`rol_otorgado`/`rol_revocado`) y el actor; `get_historial` muestra `desde`/`vence_en`/`revocada_en`, de modo que el cierre administrativo es distinguible del vencimiento pactado.
- **[Carrera entre dos ADMIN que otorgan el mismo rol a la vez]** → Mitigación: la comprobación `get_abierta` da el mensaje propio y el índice único parcial `uq_asignacion_rol_abierta` es la garantía final; el `IntegrityError` se traduce a 409 en el router, sin exponer el esquema.
- **[Evento perdido si la transacción revierte después de escribirlo]** → Es el comportamiento buscado (atomicidad, decisión 2); el trade-off es que un intento fallido de alta no deja rastro en `evento_seguridad`. Los fallos de credenciales ya viven en `intento_acceso`.
- **[`actor` es texto libre, sin FK]** (diseño de la tabla) → Mitigación: se escribe siempre el email del usuario actuante o `SISTEMA`; renombrar un email no reescribe el historial, lo cual es correcto para auditoría.
- **[Contraseña provisoria conocida por el ADMIN hasta el primer login]** → Mitigación: `debe_cambiar_password=true` bloquea el grupo protegido (RN-06) y el cambio deja evento; C-06 no expone la contraseña en ninguna respuesta.
- **[Tests dependientes de `taller_test` y de un `.env` presente]** → Mitigación: `test/usuarios/conftest.py` reutiliza el patrón de `test/repuestos/conftest.py` (fixtures `motor_pruebas`, `cliente_http`, `sesion_db`, `autenticar_usuario`), que salta la suite con mensaje claro si PostgreSQL o la configuración faltan; no se agrega dependencia nueva.

## Migration Plan

No aplica: C-06 no modifica el esquema. Despliegue = montar el router nuevo en `main.py`; rollback = quitar el `include_router` y las rutas, sin tocar datos. Las filas escritas en `asignacion_rol` y `evento_seguridad` son compatibles con el esquema vigente y no requieren limpieza.

## Open Questions

- Ninguna bloqueante. Queda registrado como supuesto que `GET /usuarios` (listado de personal) no forma parte de la consigna y no se implementa en C-06; si el usuario lo quiere, es un change aparte.
