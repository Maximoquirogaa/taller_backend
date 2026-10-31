# usuarios-roles-auditoria Specification

## Purpose

Administrar el personal del taller y sus roles con vigencia (alta de empleado, otorgamiento, revocación y autoprotección del administrador) y exponer la auditoría de seguridad de esos cambios y de los cambios de contraseña.

## Requirements

### Requirement: Alta de personal con contraseña provisoria

La API SHALL exponer `POST /usuarios` (solo rol ADMIN vigente) que cree un empleado con contraseña provisoria, `debe_cambiar_password = true` y su evento de seguridad, en una sola transacción. Sin rol ADMIN vigente SHALL responder 403 y sin sesión válida 401.

#### Scenario: Alta exitosa de empleado
- **WHEN** un ADMIN envía email nuevo, nombre y contraseña provisoria que cumple la política
- **THEN** responde 201 con el usuario creado (sin hash ni contraseña), el usuario queda con `debe_cambiar_password = true` y existe una fila en `evento_seguridad` del alta

#### Scenario: Email ya registrado
- **WHEN** un ADMIN da de alta un email que ya pertenece a cualquier usuario
- **THEN** responde 409 con mensaje propio, no queda ningún usuario nuevo y no se escribe evento de seguridad

#### Scenario: Contrato estricto del alta
- **WHEN** el cuerpo incluye campos no declarados, un email inválido o una contraseña fuera de la política (incluido más de 72 bytes)
- **THEN** responde 422 con mensajes propios, sin escribir filas y sin terminar en 500

#### Scenario: Personal no autorizado
- **WHEN** un usuario sin rol ADMIN vigente (RECEPCION, MECANICO o CLIENTE) intenta dar de alta personal
- **THEN** responde 403 sin crear el usuario

### Requirement: Otorgamiento de rol con vigencia (RN-03)

La API SHALL exponer `POST /usuarios/{id}/roles` (solo ADMIN) que abra una asignación del rol indicado, con `vencimiento` opcional que SHALL llevar zona horaria y ser futuro. Con una asignación abierta del mismo rol SHALL responder 409 y no escribir nada.

#### Scenario: Otorgamiento exitoso sin vencimiento
- **WHEN** un ADMIN otorga `MECANICO` a un usuario existente sin enviar `vencimiento`
- **THEN** responde 201, la asignación queda abierta (`revocada_en` y `vence_en` nulos) con `otorgada_por` igual al ADMIN y se registra el evento de cambio de rol

#### Scenario: Otorgamiento con vencimiento futuro
- **WHEN** un ADMIN otorga un rol con `vencimiento` con zona horaria posterior al instante actual
- **THEN** responde 201 y la asignación queda con ese `vence_en`

#### Scenario: Rol ya abierto
- **WHEN** un ADMIN otorga un rol que el usuario ya tiene en una asignación abierta
- **THEN** responde 409 con mensaje propio y no se crea una segunda fila ni un evento

#### Scenario: Vencimiento inválido
- **WHEN** el `vencimiento` enviado no lleva zona horaria o es anterior al instante actual
- **THEN** responde 422 sin abrir la asignación

#### Scenario: Reasignación de un rol vencido o revocado
- **WHEN** un ADMIN otorga un rol cuya fila anterior está vencida o revocada
- **THEN** responde 201 y la fila anterior se conserva intacta mientras la nueva queda abierta

#### Scenario: Usuario inexistente
- **WHEN** un ADMIN otorga un rol a un `id` de usuario que no existe
- **THEN** responde 404 sin escribir la asignación

### Requirement: Revocación de rol sin borrar la fila (RN-04)

La API SHALL exponer `DELETE /usuarios/{id}/roles/{rol}` (solo ADMIN) que escriba `revocada_en` sobre la asignación abierta y la conserve; SHALL rechazar con 404 si el usuario no tiene ese rol abierto y no SHALL borrar ninguna fila.

#### Scenario: Revocación exitosa
- **WHEN** un ADMIN revoca un rol que el usuario tiene abierto
- **THEN** responde 200, la fila queda con `revocada_en` y `desde` conservados, y se registra el evento de revocación

#### Scenario: El permiso perdido alcanza a la sesión abierta
- **WHEN** el usuario afectado vuelve a pedir una ruta que exigía el rol revocado con la misma cookie
- **THEN** responde 403 en esa siguiente petición, sin esperar al vencimiento del token

#### Scenario: Rol no vigente
- **WHEN** un ADMIN revoca un rol que el usuario no tiene abierto (inexistente, ya revocado o vencido)
- **THEN** responde 404 sin modificar filas ni escribir evento

#### Scenario: Personal no autorizado
- **WHEN** un usuario sin rol ADMIN vigente intenta revocar un rol
- **THEN** responde 403 sin modificar la asignación

### Requirement: Autoprotección del administrador (RN-05)

Un ADMIN SHALL poder administrar roles de terceros, pero SHALL recibir 409 si intenta revocar su propio rol ADMIN vigente, de modo que el sistema nunca quede sin administradores.

#### Scenario: ADMIN revoca su propio ADMIN
- **WHEN** un ADMIN autenticado revoca el rol ADMIN de su propio usuario
- **THEN** responde 409 con mensaje propio, la asignación permanece abierta y no se escribe evento de revocación

#### Scenario: ADMIN administra roles de terceros
- **WHEN** un ADMIN revoca un rol de otro usuario
- **THEN** la operación se completa con su código propio (no aplica la autoprotección)

### Requirement: Consulta paginada de eventos de seguridad (US-011)

La API SHALL exponer `GET /eventos` (solo ADMIN) que devuelva el envoltorio `{items, total, page, size, pages}` con los eventos ordenados del más reciente al más antiguo, y SHALL rechazar con 422 `page` o `size` fuera de rango.

#### Scenario: Listado paginado
- **WHEN** un ADMIN consulta `/eventos` con parámetros válidos
- **THEN** responde 200 con el envoltorio estándar y los eventos ordenados por instante descendente

#### Scenario: Parámetros de paginación inválidos
- **WHEN** un ADMIN consulta `/eventos?page=0` o `/eventos?size=500`
- **THEN** responde 422 con mensaje propio, sin consultar la tabla

#### Scenario: Página inexistente
- **WHEN** un ADMIN pide una página mayor a la última disponible
- **THEN** responde 422 con el mensaje propio del envoltorio de paginación

#### Scenario: Personal no autorizado
- **WHEN** un usuario sin rol ADMIN vigente consulta `/eventos`
- **THEN** responde 403

### Requirement: Auditoría de alta de personal y cambios de rol

Cada alta de personal, otorgamiento y revocación de rol SHALL dejar una fila en `evento_seguridad` dentro de la misma transacción del cambio, con `actor` igual al email del ADMIN que actuó y una `accion` que identifique la operación y el rol afectado. Si la operación falla, SHALL no quedar el evento.

#### Scenario: Evento escrito junto al cambio
- **WHEN** un ADMIN completa cualquiera de las tres operaciones de personal y roles
- **THEN** queda una fila en `evento_seguridad` con el email del ADMIN como `actor` y la acción del cambio, visible en `GET /eventos`

#### Scenario: Sin escritura parcial ante fallo
- **WHEN** la operación de alta o de rol falla (por ejemplo 409 por duplicado)
- **THEN** no queda ni el cambio ni su evento de seguridad

### Requirement: Auditoría del cambio de contraseña

Cada cambio de contraseña exitoso, incluido el que desbloquea una contraseña provisoria, SHALL dejar una fila en `evento_seguridad` con el email del usuario como `actor`, en la misma transacción en que se actualiza el hash y se limpia la bandera; un cambio rechazado SHALL no escribir evento.

#### Scenario: Cambio de contraseña auditado
- **WHEN** un usuario cambia su contraseña con la contraseña actual correcta
- **THEN** responde 200 con la cookie nueva y queda una fila en `evento_seguridad` del cambio, visible en `GET /eventos`

#### Scenario: Cambio rechazado sin evento
- **WHEN** el cambio falla por contraseña actual incorrecta (401) o por contrato inválido (422)
- **THEN** no se modifica el hash, no se limpia la bandera y no se escribe ningún evento

#### Scenario: Contraseña provisoria desbloquea el grupo protegido
- **WHEN** un empleado dado de alta por un ADMIN inicia sesión con la contraseña provisoria e intenta una ruta protegida
- **THEN** responde 403 por el cambio pendiente, y tras cambiarla con su cookie nueva accede y queda el evento del cambio
