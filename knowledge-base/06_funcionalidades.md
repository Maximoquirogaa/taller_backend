# Funcionalidades

Historias de usuario agrupadas por épica. Códigos US alineados a endpoints y reglas.

## Épica 1: Salud y ciclo de vida

### US-001 — Liveness
**Como** cualquiera **Quiero** `GET /health/live` **Para** saber que el proceso responde sin tocar la base. **CA**: 200 sin DB. **RN**: — (Ejercicio 1).

### US-002 — Readiness
**Como** operador **Quiero** `GET /health/ready` **Para** distinguir proceso vivo vs base caída. **CA**: ejecuta `SELECT 1`; 200 si contesta, 503 si no. **RN**: —

## Épica 2: Autenticación

### US-003 — Registro de cliente
**Como** visitante **Quiero** `POST /auth/registro` **Para** darme de alta como cliente y usuario a la vez. **CA**: 201 con las tres filas (usuario, rol CLIENTE, ficha) o ninguna; documento existente → 409 sin apropiarse; correo repetido → 409; 422 por contrato (`extra="forbid"`, máx. 72 bytes). **RN**: RN-02, RN-01

### US-004 — Login
**Como** usuario **Quiero** `POST /auth/login` **Para** iniciar sesión. **CA**: 200 con `Set-Cookie` HttpOnly/SameSite=Lax/Max-Age (cuerpo **sin** token); 401 con mismo cuerpo y tiempo exista o no el correo; 429 + `Retry-After` al 5.º fallo en 60 s por email+IP; cuerpo con `debe_cambiar_password` y `expira_en_segundos`. **RN**: RN-08, RN-09

### US-005 — Logout
**Como** usuario **Quiero** `POST /auth/logout` **Para** borrar la cookie. **CA**: 200. **RN**: —

### US-006 — Quién soy
**Como** usuario **Quiero** `GET /auth/yo` **Para** ver mi usuario, roles vigentes y roles del token. **CA**: 200 con ambas listas; 401 sin cookie/válida. **RN**: RN-04

### US-007 — Cambio obligatorio de contraseña
**Como** usuario con contraseña provisoria **Quiero** `POST /auth/cambiar-password` **Para** elegir mi contraseña y desbloquear el sistema. **CA**: solo `/auth` y salud accesibles mientras esté pendiente (403); tras el cambio la cookie nueva vale y las anteriores 401 incluso en el mismo segundo; 422 si excede 72 bytes. **RN**: RN-06, RN-07

## Épica 3: Usuarios, roles y auditoría (ADMIN)

### US-008 — Alta de personal
**Como** ADMIN **Quiero** `POST /usuarios` **Para** crear un empleado con contraseña provisoria. **CA**: 201; 409 email repetido; 422 contrato. **RN**: RN-01

### US-009 — Asignar rol con vigencia
**Como** ADMIN **Quiero** `POST /usuarios/{id}/roles` **Para** otorgar un rol (vencimiento opcional con zona horaria y en el futuro). **CA**: 201; 409 si ya tiene rol abierto; 422 si el vencimiento es pasado o sin zona; reasignar vencido cierra fila anterior. **RN**: RN-03

### US-010 — Revocar rol
**Como** ADMIN **Quiero** `DELETE /usuarios/{id}/roles/{rol}` **Para** quitar un rol sin borrar el historial. **CA**: 200; la fila queda con `revocada_en`; la sesión afectada recibe 403 en la siguiente petición; 409 si es su propio ADMIN. **RN**: RN-04, RN-05

### US-011 — Eventos de seguridad
**Como** ADMIN **Quiero** `GET /eventos` **Para** auditar altas, cambios de rol/contraseña y la carga inicial. **CA**: 200 paginado; 422 page/size inválidos. **RN**: —

## Épica 4: Clientes y vehículos

### US-012 — Alta de cliente
**Como** RECEPCION/ADMIN **Quiero** `POST /clientes` **Para** registrar un cliente sin usuario. **CA**: 201; 409 documento duplicado; 422. **RN**: RN-01

### US-013 — Alta de vehículo
**Como** RECEPCION/ADMIN **Quiero** `POST /clientes/{id}/vehiculos` **Para** cargar un vehículo al cliente. **CA**: 201; 404 cliente inexistente; 409 patente vigente repetida; 422 año fuera de rango. **RN**: RN-01

### US-014 — Baja de vehículo
**Como** RECEPCION/ADMIN **Quiero** `DELETE /vehiculos/{id}` **Para** dar de baja lógica. **CA**: 204; 409 si tiene órdenes abiertas; la patente queda libre para otro cliente (índice parcial). **RN**: RN-16, C-19

### US-015 — Mis vehículos
**Como** cliente **Quiero** `GET /mis-vehiculos` **Para** ver solo los míos. **CA**: 200; solo los propios. **RN**: RN-17

### US-016 — Detalle de cliente con vehículos
**Como** RECEPCION/ADMIN **Quiero** `GET /clientes/{id}` **Para** ver la ficha con sus vehículos (precarga, sin N+1). **CA**: 200; 404. **RN**: —

## Épica 5: Repuestos y stock

### US-017 — Catálogo con búsqueda y paginación
**Como** ADMIN/RECEPCION/MECANICO **Quiero** `GET /repuestos?q=&page=&size=` **Para** encontrar repuestos. **CA**: envoltorio `{items,total,page,size,pages}`; `q` con parámetros ligados (injection → lista vacía, total 0); page fuera de rango → 422; size 1–100. **RN**: RN-18

### US-018 — Alta de repuesto
**Como** ADMIN **Quiero** `POST /repuestos` (con `stock_inicial`) **Para** incorporar pieza al catálogo. **CA**: 201 con movimiento «Stock inicial»; 409 código vigente repetido; 422 precio ≤ 0. **RN**: RN-01, RN-14

### US-019 — Modificar descripción/precio
**Como** ADMIN **Quiero** `PATCH /repuestos/{id}` **Para** actualizar solo los campos enviados (`exclude_unset`). **CA**: si cambia el precio, línea en historial en la misma transacción; si no, sin línea; stock no es editable (422); RECEPCION → 403. **RN**: RN-20, RN-14

### US-020 — Baja de repuesto
**Como** ADMIN **Quiero** `DELETE /repuestos/{id}` **Para** baja lógica. **CA**: 204; no usado en órdenes nuevas. **RN**: RN-16

### US-021 — Reposición de stock
**Como** ADMIN **Quiero** `POST /repuestos/{id}/reponer` **Para** sumar stock. **CA**: 200 con movimiento registrado; único punto de escritura del stock. **RN**: RN-14

### US-022 — Movimientos y precios
**Como** rol autorizado **Quiero** `GET /repuestos/{id}/movimientos` y `.../precios` **Para** auditar salidas y cambios de precio. **CA**: 200; 404. **RN**: RN-15, RN-20

## Épica 6: Órdenes de trabajo

### US-023 — Abrir orden
**Como** RECEPCION/ADMIN **Quiero** `POST /ordenes` con `vehiculo_id`, `falla` e `items[]` **Para** registrar un ingreso. **CA**: 201 con precios copiados, total calculado e historial PENDIENTE; 409 repuesto inexistente o catálogo vacío (orden no creada); sin precio/total/estado en el cuerpo; sin ítems o repetidos → 422/409. **RN**: RN-10, RN-19

### US-024 — Listar y filtrar órdenes
**Como** ADMIN/RECEPCION/MECANICO **Quiero** `GET /ordenes?estado=&page=&size=` **Para** ver el tablero. **CA**: 200 envuelto; estado no declarado en el contrato → 422. **RN**: —

### US-025 — Detalle de orden
**Como** personal o dueño del vehículo **Quiero** `GET /ordenes/{id}` **Para** ver vehículo, cliente, ítems (con repuesto) e historial. **CA**: 200 con consultas fijas (C-15, 2 vs 4 ítems = mismas consultas); dueño ajeno → 403; inexistente → 404. **RN**: RN-17

### US-026 — Iniciar reparación
**Como** MECANICO **Quiero** `POST /ordenes/{id}/iniciar` **Para** tomar la orden. **CA**: PENDIENTE → EN_REPARACION con `mecanico_id` = yo; 409 si el estado no lo permite. **RN**: RN-11

### US-027 — Terminar reparación
**Como** mecánico asignado o ADMIN **Quiero** `POST /ordenes/{id}/terminar` **Para** cerrar y descontar stock. **CA**: en una sola transacción baja stock, movimientos e historial; stock insuficiente → 409 sin escrituras parciales (C-11); tras confirmar, aviso en BackgroundTasks (C-12). **RN**: RN-13, RN-11, RN-14

### US-028 — Cancelar orden
**Como** RECEPCION, ADMIN o dueño **Quiero** `POST /ordenes/{id}/cancelar` **Para** anular una orden pendiente. **CA**: 200; orden ajena → 403 **antes** de mirar estado; terminada → 409; sin `requiere_rol` en la ruta. **RN**: RN-12

### US-029 — Catálogo de estados
**Como** autenticado **Quiero** `GET /estados-orden` **Para** conocer la máquina de estados. **CA**: 200 por posición; finales marcados; 401 sin sesión. **RN**: RN-19

### US-030 — Mis órdenes
**Como** cliente **Quiero** `GET /mis-ordenes` **Para** ver el estado de mis vehículos. **CA**: 200 paginado, solo propias. **RN**: RN-17

## Épica 7: Integridad (pruebas SQL)

### US-031 — Sólo agregado verificable
**Como** corrector **Quiero** `test/solo_agregado.sql` **Para** probar en psql los 6 rechazos del disparador (UPDATE/DELETE × 3 tablas) y el FK de estado fuera del catálogo. **CA**: todo rechazado (C-14). **RN**: RN-15, RN-19
