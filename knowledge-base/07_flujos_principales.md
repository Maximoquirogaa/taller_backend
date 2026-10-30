# Flujos Principales

## Flujo 1: Registro de cliente (RN-02)
**Disparador**: visitante envía `POST /auth/registro`. **Actor**: CLIENTE (potencial)

**Pasos**:
1. Contrato valida (`extra="forbid"`, password ≤ 72 bytes) → 422 si falla.
2. bcrypt calcula el hash **antes** de abrir la transacción (fuera del bucle, `to_thread` + semáforo).
3. Servicio abre el Unit of Work.
4. UoW inserta `usuario` + `asignacion_rol (CLIENTE)` + `cliente` (con `usuario_id`).
5. Al salir del bloque: commit (las tres quedan) o rollback (ninguna).
6. 201. Chocо de unicidad (email/documento) → `IntegrityError` traducido a 409 sin filas sueltas.

## Flujo 2: Login con límite de intentos (RN-08, RN-09)
**Disparador**: `POST /auth/login`. **Actor**: cualquier usuario

**Pasos**:
1. **Primero** el límite: contar fallos (`email`, `ip`, 60 s) sobre `intento_acceso`. Si ≥ 5 → 429 + `Retry-After`, sin tocar bcrypt.
2. Verificar contraseña contra el hash del usuario, o contra el **hash ficticio** si el email no existe (mismo mensaje y tiempo).
3. Cada intento (correcto o fallido) se anota en `intento_acceso` en **sesión y transacción propias**, siempre confirmadas.
4. Login correcto: JWT (`sub`, `iat` con hora completa sin truncar, `exp`, roles vigentes) firmado con `SECRET_KEY`; respuesta 200 con `Set-Cookie` access_token (HttpOnly, SameSite=Lax, Max-Age, Secure configurable) — el cuerpo no trae el token.
5. Login fallido → 401 idéntico exista o no la cuenta.

## Flujo 3: Cambio obligatorio de contraseña (RN-06, RN-07)
**Disparador**: usuario con `debe_cambiar_password` intenta usar el sistema. **Actor**: usuario

**Pasos**:
1. Cualquier ruta del grupo protegido (excepto `/auth` y salud) → 403 si el control detecta el cambio pendiente. Dos grupos en `main.py`; el control va montado una sola vez en el protegido.
2. `POST /auth/cambiar-password`: verifica contraseña actual, valida la nueva (≤ 72 bytes), hashea fuera de la transacción, actualiza `password_hash`, `password_cambiada_en` y limpia el flag.
3. Emite un token nuevo **después** de anotar el cambio.
4. Cookies anteriores: `iat < password_cambiada_en` sin truncar → 401 (incluso del mismo segundo). La cookie nueva → 200.

## Flujo 4: Alta de orden (RN-10, RN-19)
**Disparador**: RECEPCION/ADMIN `POST /ordenes`. **Actor**: recepción

**Pasos**:
1. Contrato: `vehiculo_id`, `falla`, `items[{repuesto_id, cantidad}]` — sin precio/total/estado.
2. Catálogo con filas → si vacío, 409 con mensaje propio.
3. Servicio abre UoW: valida repuestos vigentes, calcula precios unitarios desde el catálogo de repuestos y el total.
4. Inserta `orden_trabajo` (PENDIENTE) + `item_orden` (composición) + `historial_estado_orden` (null → PENDIENTE).
5. Commit → 201 con la respuesta enriquecida (patente, cliente, items con subtotal, historial).

## Flujo 5: Iniciar reparación (RN-11)
**Disparador**: MECANICO `POST /ordenes/{id}/iniciar`. **Actor**: mecánico

**Pasos**:
1. `requiere_rol(MECANICO)` → roles vigentes desde la base (403 si no).
2. Servicio: estado PENDIENTE → EN_REPARACION; `mecanico_id` = usuario actual; línea de historial.
3. Estado no válido → 409.

## Flujo 6: Terminar reparación con descuento de stock (RN-13, RN-14) — transacción crítica
**Disparador**: mecánico asignado o ADMIN `POST /ordenes/{id}/terminar`. **Actor**: mecánico/ADMIN

```
Servicio → async with uow:
  1. Verificar permiso (asignado o ADMIN) y estado EN_REPARACION (403/409)
  2. Por cada item_orden: chequear stock suficiente
     - Si alguno no alcanza → lanzar → UoW revierte TODO → 409 (C-11: nada cambió)
  3. Por cada item: stock -= cantidad + movimiento_stock (motivo salida, orden_id)
  4. estado → TERMINADA + historial_estado_orden
  5. commit implícito al salir del bloque
→ 200; luego BackgroundTasks: await asyncio.sleep(0.5) + log del aviso (solo si confirmó)
```

**Casos de error**: stock insuficiente → 409 sin escrituras; estado CANCELADA/TERMINADA → 409; sin permiso → 403.

## Flujo 7: Cancelación con permiso antes que estado (RN-12)
**Disparador**: RECEPCION/ADMIN/dueño `POST /ordenes/{id}/cancelar`. **Actor**: varios

**Pasos**:
1. La ruta **no** usa `requiere_rol` (el dueño no tiene rol de personal).
2. Servicio: ¿quién es y qué relación tiene con la orden (personal o dueño del vehículo)? → si no, 403.
3. Recién después: ¿estado permite cancelar (PENDIENTE)? → si no, 409.
4. PENDIENTE → CANCELADA + historial; commit; 200.

## Flujo 8: Reposición y cambio de precio (RN-14, RN-20)
**Pasos**:
1. `POST /repuestos/{id}/reponer`: cantidad > 0 → stock += cantidad + movimiento (único punto de escritura del stock).
2. `PATCH /repuestos/{id}`: `exclude_unset`; si `precio` difiere → UPDATE + línea `historial_precio_repuesto` (precio_anterior/nuevo) **en la misma transacción**; si solo cambia descripción → sin línea.

## Flujo 9: Baja lógica de vehículo/repuesto (RN-16)
**Pasos**:
1. Vehículo: ¿órdenes en estado no final? → 409. Si no → `borrado_en = now()`; 204.
2. Repuesto: baja lógica; deja de listarse y de poder usarse en órdenes nuevas.
3. Índices únicos parciales (`WHERE borrado_en IS NULL`) permiten re-registrar la misma patente/código vigente (C-19).
