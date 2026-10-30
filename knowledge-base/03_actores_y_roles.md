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
