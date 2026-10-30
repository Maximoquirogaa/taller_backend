# Reglas de Negocio

Códigos `RN-NN` tal como los usa la consigna (garante esperado entre paréntesis).

## Dominio: Acceso y usuarios

- **RN-01**: Email de usuario y documento de cliente son únicos; patente de vehículo y código de repuesto son únicos **entre los no dados de baja**. (UNIQUE + índices únicos parciales; 409 con mensaje propio.)
- **RN-02**: El auto-registro crea usuario + rol CLIENTE + ficha de cliente en **un solo Unit of Work**: o quedan las tres filas o ninguna. Si el documento ya pertenece a un cliente del taller → 409, sin apropiarse de la ficha.
- **RN-07**: Al cambiar la contraseña, las sesiones anteriores dejan de valer (comparar `iat` con `password_cambiada_en` **sin truncar a segundos**); el token que devuelve el propio cambio sí vale. (401.)
- **RN-08**: 5 intentos fallidos con el mismo email desde la misma IP en 60 s → login responde 429 con `Retry-After` **sin verificar la contraseña**. Un login correcto reinicia la cuenta (los fallos previos siguen en la tabla pero dejan de contar). (Conteo sobre `intento_acceso`.)
- **RN-09**: El login responde igual y tarda igual exista o no el email. (Mismo mensaje; verificación contra un hash ficticio cuando el usuario no existe.)

## Dominio: Roles y autorización

- **RN-03**: Un usuario tiene a lo sumo una asignación **abierta** por rol. (Índice único parcial; 409.)
- **RN-04**: Los permisos se deciden con los roles **vigentes en la base, en cada petición**. Los roles del token son informativos. (Revocar quita el permiso a una sesión abierta sin esperar a que venza el token.)
- **RN-05**: Un ADMIN no puede revocar su propio rol ADMIN; el sistema nunca queda sin administradores vigentes. (Comprobación en servicio; 409.)
- **RN-06**: Mientras el usuario tenga el cambio de contraseña pendiente, solo puede usar rutas de `/auth` y salud. (Dos grupos de rutas; 403.)

## Dominio: Órdenes de trabajo

- **RN-10**: Una orden nace PENDIENTE, con al menos un ítem y sin repuestos repetidos. El precio de cada ítem se **copia** del repuesto; el total lo calcula el servidor. (DTO: precio y total nunca viajan en el cuerpo.)
- **RN-11**: Transiciones válidas: PENDIENTE → EN_REPARACION (la inicia un mecánico, que queda asignado), EN_REPARACION → TERMINADA (la termina el mecánico asignado o un ADMIN) y PENDIENTE → CANCELADA. (409 si el estado no lo permite.)
- **RN-12**: Cancelan la orden RECEPCION, ADMIN o el **dueño del vehículo**. El permiso se evalúa **antes** que el estado. (403 antes que 409; la ruta de cancelar no lleva `requiere_rol`.)
- **RN-13**: Terminar una orden descuenta el stock de cada ítem, deja un movimiento por salida y una línea de historial de estados. Si un repuesto no alcanza, **no queda ninguna** de esas escrituras. (Un solo UoW; 409.)
- **RN-16**: Vehículo o repuesto dado de baja deja de aparecer y no se usa en órdenes nuevas; sus datos se conservan. Un vehículo con órdenes **abiertas** (estado no final según `es_final`) no se da de baja. (Borrado lógico; 409.)
- **RN-19**: Los estados posibles son las filas del catálogo `estado_orden`. El catálogo se consulta desde la API y no se edita. Si está vacío, crear una orden responde 409 con mensaje propio. (FK; repositorio de sólo lectura.)

## Dominio: Stock y repuestos

- **RN-14**: El stock solo cambia a través de **movimientos**: alta con stock inicial, reposición y terminación de órdenes. No se edita por PATCH. (Punto único de escritura.)
- **RN-18** (integridad de errores, aplica también acá): ninguna entrada inválida termina en 500; nunca se expone texto interno de la base.

## Dominio: Integridad y auditoría

- **RN-15**: `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto` son de **sólo agregado**: nadie modifica ni borra sus filas. (Disparador en la base, instalado por migración escrita a mano.)
- **RN-17**: Lo propio solo pide estar autenticado: un cliente ve sus vehículos y las órdenes de sus vehículos, y ninguna otra. (`/mis-*` + comprobación de dueño; 403.)
- **RN-18**: Ningún error devuelve texto interno de la base (entregaría el mapa del esquema). Ninguna entrada inválida termina en 500. (Traducción de `IntegrityError`; validación en el contrato.)
- **RN-20**: Cada cambio de precio de un repuesto deja una línea en `historial_precio_repuesto`, **en la misma transacción**. Un PATCH que no cambia el precio no deja línea. (Un solo UoW; CHECK `precio_nuevo > precio_anterior`.)

## Excepciones globales

- Unicidad **garantizada por la base**, no por una consulta previa (C-19, C-02).
- SQL nunca armado por concatenación con datos del usuario (búsqueda por `q` con parámetros ligados — C-16).
- El intento de acceso es la única escritura que **no** comparte la transacción de su petición (sesión propia, siempre confirmada — deja filas aunque la petición falle; se documenta en comentario con su costo).
