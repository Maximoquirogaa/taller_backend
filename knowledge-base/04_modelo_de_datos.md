# Modelo de Datos

## Dominios

- **Acceso y auditoría**: usuarios, asignación de roles con vigencia, intentos de acceso, eventos de seguridad.
- **Clientes y vehículos**: ficha de cliente (opcionalmente ligada 1:1 a un usuario), vehículos con borrado lógico.
- **Repuestos y stock**: catálogo de piezas con precio/stock, borrado lógico, movimientos e historial de precios de sólo agregado.
- **Órdenes de trabajo**: orden con ítems (composición), máquina de estados por catálogo, historial de estados de sólo agregado.

## ERD (relaciones)

```
usuario 1──< asignacion_rol >──(CHECK rol ∈ {ADMIN,RECEPCION,MECANICO,CLIENTE})
   │ 1
   │
   │ 0..1  (usuario_id UNIQUE nulo)          ← uno a uno opcional
   ▼
cliente 1──< vehiculo (borrado_en; patente única entre vigentes)
                │ 1
                │
                ▼
             orden_trabajo >──FK estado── estado_orden (catálogo; PK = codigo)
                │ 1                    ▲
                │                      │ desde_estado / hasta_estado (FK)
                ├──< item_orden >── repuesto (composición: ítem sin orden no existe)
                │         UNIQUE(orden_id, repuesto_id)
                └──< historial_estado_orden

repuesto 1──< movimiento_stock (orden_id nulo) 
repuesto 1──< historial_precio_repuesto

intentro_acceso  (sin FK; índice (email, ip, cuando))
evento_seguridad (sin FK; actor es texto)
```

Tipos: todas las fechas `timestamptz`; dinero `NUMERIC` (Python `Decimal`, nunca `float`); cada FK con índice (PG no los crea solo).

## Entidades

### usuario
- `id`, `email` **UNIQUE**, `nombre`, `password_hash`, `activo`, `debe_cambiar_password`, `password_cambiada_en` (timestamptz, nulo)
- Relación: 0..1 `cliente` (vía `cliente.usuario_id` UNIQUE nulo); N `asignacion_rol`

### asignacion_rol
- `id`, `usuario_id`, `rol` (CHECK: ADMIN | RECEPCION | MECANICO | CLIENTE), `desde`, `vence_en` (nulo), `revocada_en` (nulo), `otorgada_por` (nulo)
- **Índice único parcial** `(usuario_id, rol) WHERE revocada_en IS NULL` → RN-03
- Revocación escribe `revocada_en`; la fila nunca se borra

### intento_acceso
- `id`, `cuando`, `email`, `ip`, `exito`; índice `(email, ip, cuando)` → base del límite de login (RN-08)
- Sin relaciones con otras tablas; se escribe en sesión y transacción propias, siempre confirmadas

### evento_seguridad
- `id`, `cuando`, `actor` (texto, p. ej. `SISTEMA` o el usuario), `accion`; sin restricciones extra

### cliente
- `id`, `usuario_id` (nulo, **UNIQUE** → uno a uno opcional), `nombre`, `documento` **UNIQUE**, `telefono`
- Navegación: `Usuario.cliente` devuelve objeto (no lista)

### vehiculo
- `id`, `cliente_id`, `patente`, `marca`, `modelo`, `anio` (CHECK 1950–2100), `borrado_en` (nulo)
- **Índice único parcial** `(patente) WHERE borrado_en IS NULL` → un auto vendido no bloquea re-registrar la patente
- Baja lógica solo si no tiene órdenes abiertas (estado no final) — RN-16

### repuesto
- `id`, `codigo`, `descripcion`, `precio` NUMERIC(10,2) CHECK > 0, `stock` CHECK >= 0, `borrado_en` (nulo)
- **Índice único parcial** `(codigo) WHERE borrado_en IS NULL`
- Stock solo cambia por movimientos (alta inicial, reposición, terminación) — RN-14

### estado_orden (catálogo)
- PK = `codigo` (texto); `descripcion`, `posicion` **UNIQUE**, `es_final` (bool)
- Carga: `seed.py` — PENDIENTE(1), EN_REPARACION(2), TERMINADA(3, final), CANCELADA(4, final)
- La migración crea la tabla **vacía**; el catálogo no se edita desde la API (repositorio de solo lectura, no hereda de `BaseRepository`)

### orden_trabajo
- `id`, `vehiculo_id`, `mecanico_id` (nulo), `estado` FK → `estado_orden.codigo`, `falla`, `creada_en`, `total` NUMERIC(12,2) CHECK >= 0
- Estado nace PENDIENTE; transiciones solo por servicio (RN-11)

### item_orden (composición)
- `id`, `orden_id`, `repuesto_id`, `cantidad` CHECK > 0, `precio_unitario` NUMERIC(10,2) CHECK > 0
- **UNIQUE** `(orden_id, repuesto_id)` → sin repuestos repetidos en una orden
- `precio_unitario` se **copia** del repuesto al crear la orden; total lo calcula el servidor (RN-10)

### historial_estado_orden (sólo agregado)
- `id`, `orden_id`, `desde_estado` (nulo), `hasta_estado`, `usuario_id`, `cuando`; ambas FKs a `estado_orden`
- UPDATE/DELETE rechazados por disparador (RN-15); la migración del disparador está **escrita a mano**

### movimiento_stock (sólo agregado)
- `id`, `repuesto_id`, `orden_id` (nulo), `usuario_id`, `cantidad` CHECK > 0, `motivo`, `cuando`
- Protegido por el mismo disparador

### historial_precio_repuesto (sólo agregado)
- `id`, `repuesto_id`, `usuario_id`, `precio_anterior`, `precio_nuevo` (NUMERIC 10,2, CHECK > 0 y CHECK `precio_nuevo > precio_anterior`), `cuando`
- Se escribe en la misma transacción que el PATCH del precio (RN-20); un PATCH que no cambia precio no deja línea

## Seed data inicial (`seed.py`)

Vacía tablas y carga (mínimo):
- Catálogo: PENDIENTE, EN_REPARACION, TERMINADA (final), CANCELADA (final) — **primero**, porque todo estado apunta allí.
- Usuarios: `admin@`, `admin2@` (ADMIN), `recepcion@` (RECEPCION), `mecanico@`, `mecanico2@` (MECANICO), `cliente@` (CLIENTE), `nuevo@` (MECANICO + cambio obligatorio).
- Clientes: Laura (con usuario + 2 vehículos), Jorge (sin usuario + 1 vehículo).
- Repuestos: filtro aceite (10), pastillas freno (4), bujía (2), aceite litro (20); stock inicial como movimiento.
- Órdenes: orden 1 PENDIENTE (vehículo Laura); orden 2 EN_REPARACION (vehículo Jorge, asignada a mecánico, pide 4 bujías con stock 2 — caso C-11).
- Historial de precios: filtro 8000 → 8500. Evento seguridad: `SISTEMA` «Carga de los datos iniciales».
- Contraseñas de mentira, solo en `seed.py`.
