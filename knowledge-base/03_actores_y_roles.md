# Actores y Roles

## Actores del sistema

| Actor | Descripción | Cómo interactúa |
|-------|-------------|-----------------|
| ADMIN | Administrador del taller | Alta de personal, roles con vigencia, catálogo y reposición de repuestos, terminar órdenes, ver `/eventos`, modificar precios (deja historial) |
| RECEPCION | Recepción del taller | Alta de clientes y vehículos, apertura de órdenes, cancelación de órdenes |
| MECANICO | Personal técnico | Inicia y termina órdenes (las asignadas), consulta repuestos/movimientos/precios |
| CLIENTE | Dueño de vehículos | Se registra solo, ve sus vehículos (`/mis-vehiculos`) y sus órdenes (`/mis-ordenes`), cancela sus órdenes pendientes |
| SISTEMA | Actor textual de auditoría | Aparece en `evento_seguridad.actor` en la carga inicial de `seed.py` (no es un usuario) |

Los roles viven en `asignacion_rol` (filas vigentes: `revocada_en IS NULL` y `vence_en` nulo o futuro). **No** hay columna `rol` en `usuario`. Revocar no borra la fila (historial). Reasignar un rol vencido cierra la fila anterior y abre otra (máx. una abierta por rol por usuario — RN-03).

## RBAC — Matriz de permisos

| Rol | Usuarios/roles | Clientes/vehículos | Repuestos | Órdenes | Eventos |
|-----|----------------|--------------------|-----------|---------|---------|
| ADMIN | Alta de personal; listar/asignar/revocar roles | Alta y lectura | CRUD + reponer + precios + movimientos | Crear, listar, detalle, terminar (cualquiera), cancelar | Lectura paginada |
| RECEPCION | — | Alta de clientes/vehículos; lectura con vehículos | Lectura (lista y detalle) | Crear, listar, detalle, cancelar | — |
| MECANICO | — | — | Lectura (lista, detalle, movimientos, precios) | Listar, detalle, **iniciar** (queda asignado), terminar si está asignado | — |
| CLIENTE | — | Solo los propios (`/mis-*`) | — | Solo los de sus vehículos; cancelar los pendientes propios | — |

Permisos que cruzan roles:
- **Terminar orden**: el mecánico asignado **o** ADMIN (ruta no usa `requiere_rol` simple).
- **Cancelar orden**: RECEPCION, ADMIN **o el dueño del vehículo** — la ruta no lleva `requiere_rol`; el servicio evalúa primero relación (403) y después estado (409).
- **Lo propio** (`/mis-vehiculos`, `/mis-ordenes`, detalle propio): solo requiere estar autenticado + comprobación de dueño (RN-17).
- **Autoprotección**: un ADMIN no puede revocarse su propio ADMIN (RN-05); el sistema nunca queda sin administradores vigentes.

## Rutas públicas (sin cookie)

- `GET /health/live`, `GET /health/ready`
- `POST /auth/registro`, `POST /auth/login`, `POST /auth/logout`

`GET /auth/yo` y `POST /auth/cambiar-password` están en el grupo abierto pero **requieren sesión** (401 sin cookie). Todo el grupo protegido responde 401 sin sesión válida y **403** si el usuario tiene el cambio de contraseña pendiente (salvo rutas de `/auth` y salud — RN-06).

## Cambio obligatorio de contraseña

Usuarios con `debe_cambiar_password = true` (p. ej. alta de personal con contraseña provisoria, seed `nuevo@example.com`): solo usan rutas de `/auth` y salud. Tras cambiar la contraseña, las cookies anteriores dejan de valer (comparación `iat` vs `password_cambiada_en` **sin truncar a segundos** — RN-07); la cookie que devuelve el propio cambio sí vale.

## Flujo de sesión (`user-auth`, C-03)

1. **Registro** — `POST /auth/registro`: valida contrato estricto (`extra="forbid"`, 422), exige contraseña con las reglas de `validar_password` (sin espacios, con dígitos, longitud acotada). Crea `usuario` (hash bcrypt costo `BCRYPT_COST=12`, calculado **antes** de abrir la transacción, vía `to_thread` + semáforo), asigna rol `CLIENTE` en `asignacion_rol` y anota el primer `intento_acceso(exito=true)` inicial, todo en una sola unidad de trabajo → `201`. Email duplicado → `409`.
2. **Login** — `POST /auth/login`: verifica bcrypt; registra cada intento en `intento_acceso`. El límite de intentos fallidos (5 en 60 s por `email+ip`, RN-08) se cuenta **sobre la tabla `intento_acceso`** (fallos posteriores al último éxito) y responde `429` con cabecera `Retry-After` (ventana completa de 60 s) **sin** escribir la fila del intento rechazado. Credenciales inválidas → `401` (mensaje único, no revela si existe el email). Éxito → cookie `access_token` (`HttpOnly`, `SameSite=lax`, `Path=/`) + `200 {debe_cambiar_password, expira_en_segundos}`.
3. **Uso de la sesión** — el token JWT (HS256, `iat` flotante sin truncar, DD-05) viaja **solo** en la cookie de sesión (DD-04: un `Authorization: Bearer` se ignora → 401). La dependencia `usuario_actual` valida firma/vencimiento, carga el usuario y **sus roles vigentes de la base en cada petición** (RN-04: revocar un rol mata la sesión funcional al instante). Logout borra la cookie (el token en sí sigue siendo decodificable hasta su `exp`: caducidad física sin lista de revocación).
4. **Cambio de contraseña** — `POST /auth/cambiar-password`: exige la vigente (`401` si no), calcula el hash nuevo fuera de la transacción, anota `password_cambiada_en`, limpia la bandera y reemite cookie válida. Todo token `iat < password_cambiada_en` vale 401 (RN-07); el token POST-cambio vale. Si la nueva no cumple el contrato → `422` y nada cambia.

Errores de sesión: `401 {"detail":"Sesión inválida o vencida: iniciá sesión de nuevo."}`; cambio pendiente en rutas protegidas: `403 {"detail": MENSAJE_CAMBIO_PENDIENTE}`; sin rol vigente: `403 {MENSAJE_SIN_PERMISO}` (ver `app/core/mensajes_auth.py`).

## Ejemplos OpenAPI (auth)

Esquema de seguridad declarado en `main.py` (`securitySchemes`):

```yaml
components:
  securitySchemes:
    cookieAuth:
      type: apiKey
      in: cookie
      name: access_token
```

`POST /auth/registro` → `201`:

```json
{
  "email": "laura@example.com",
  "nombre": "Laura Gómez",
  "password": "clave-segura-9"
}
```

```json
{ "email": "laura@example.com", "nombre": "Laura Gómez", "rol": "CLIENTE" }
```

`POST /auth/login` → `200` (además setea la cookie `access_token`):

```json
{ "debe_cambiar_password": false, "expira_en_segundos": 1800 }
```

`GET /auth/yo` → `200` (requiere cookie; ver `security` en la spec):

```json
{
  "email": "laura@example.com",
  "nombre": "Laura Gómez",
  "debe_cambiar_password": false,
  "roles_vigentes": ["CLIENTE"],
  "roles_token": ["CLIENTE"]
}
```

`POST /auth/cambiar-password` → `200` (devuelve cookie nueva válida):

```json
{ "password_actual": "clave-segura-9", "password_nueva": "otra-clave-mas-2026" }
```

```json
{ "debe_cambiar_password": false, "expira_en_segundos": 1800 }
```

`POST /auth/logout` → `200` (borra la cookie):

```json
{ "mensaje": "Sesión cerrada." }
```
