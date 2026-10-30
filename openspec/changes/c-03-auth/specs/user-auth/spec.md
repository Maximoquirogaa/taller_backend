# Spec Delta – User Authentication (user-auth)

## Purpose

Autenticar a los usuarios con JWT en cookie HttpOnly, hashear contraseñas con bcrypt y decidir la autorización con los roles vigentes en la base, de modo que todos los endpoints funcionales queden protegidos (C-04 en adelante) y ningún fallo de autenticación exponga información de la base.

## ADDED Requirements

### Requirement: Registro de cuenta de cliente

La API SHALL exponer `POST /auth/registro` (ruta pública) que cree el usuario con su contraseña hasheada y la asignación vigente del rol `CLIENTE` dentro de **una sola transacción**: o quedan ambas filas o ninguna. El registro crea también un registro inicial de intento de acceso exitoso para evitar que la primera consulta del login parta de un vacío.

#### Scenario: Registro exitoso

- **WHEN** `POST /auth/registro` recibe un `email` inexistente con datos válidos
- **THEN** responde `201`, quedan persistidos el usuario con la contraseña **hasheada** (nunca el texto plano) y la asignación vigente de `CLIENTE`, y la contraseña enviada no aparece en ninguna fila de la base

#### Scenario: Email duplicado rechazado

- **WHEN** `POST /auth/registro` recibe un `email` ya registrado
- **THEN** responde `409` con un mensaje propio (sin filas nuevas a medias) y sin exponer texto interno de PostgreSQL

#### Scenario: Contrato estricto en el registro

- **WHEN** `POST /auth/registro` recibe campos extra no declarados en el contrato (`extra="forbid"`) o una contraseña que supera los límites definidos (máximo 72 bytes)
- **THEN** responde `422` con mensajes de validación propios, sin escribir ninguna fila y sin terminar en `500`

### Requirement: Login con credenciales verificadas por bcrypt

La API SHALL exponer `POST /auth/login` (ruta pública) que verifique la contraseña contra el hash bcrypt del usuario (fuera del bucle de eventos) y, si es correcta y el usuario está activo, responda `200` con la cookie de sesión. El cuerpo de la respuesta SHALL incluir si el usuario tiene pendiente el cambio de contraseña y la duración configurada del token, y SHALL **nunca** incluir el token.

#### Scenario: Login exitoso produce cookie de sesión

- **WHEN** `POST /auth/login` recibe credenciales válidas de un usuario activo
- **THEN** responde `200` con la cookie de sesión marcada `HttpOnly` y `SameSite=Lax` (con expiración por edad y `Secure` configurable), y el cuerpo contiene el estado del cambio de contraseña y los segundos de expiración, pero **no** el token

#### Scenario: Login fallido idéntico exista o no la cuenta (RN-09)

- **WHEN** `POST /auth/login` recibe una contraseña incorrecta, con un email existente o inexistente
- **THEN** en ambos casos responde `401` con el **mismo** mensaje, y para el email inexistente se verifica la contraseña contra un hash ficticio con bcrypt, de modo que el tiempo no distinga qué cuentas existen

#### Scenario: Usuario inactivo rechazado con mensaje genérico

- **WHEN** `POST /auth/login` recibe credenciales de un usuario desactivado
- **THEN** responde `401` con el mensaje genérico (sin aclarar si falló la contraseña o el estado de la cuenta)

### Requirement: Límite de intentos fallidos por email e IP (RN-08)

El login SHALL contar primero los intentos fallidos registrados para el par (email, IP) dentro de los últimos 60 segundos; si alcanzan 5, SHALL responder `429` con la cabecera `Retry-After` **sin verificar la contraseña** (sin tocar bcrypt).

#### Scenario: Límite de fallos dispara 429

- **WHEN** desde la misma IP se registran 5 fallos con el mismo email dentro de 60 segundos y llega un nuevo intento con ese email desde esa IP
- **THEN** responde `429` con `Retry-After` y no se ejecuta ninguna verificación de contraseña

#### Scenario: Login correcto reinicia la cuenta

- **WHEN** tras varios fallos llega un login **correcto** para el par (email, IP)
- **THEN** responde `200` y los fallos previos dejan de contar (los registros quedan en la tabla de intentos pero no suman al límite)

### Requirement: Intento de acceso registrado en transacción propia (DD-07)

Cada intento de login (exitoso o fallido) SHALL dejar su fila de auditoría en una transacción **propia siempre confirmada**, sin clave foránea hacia el usuario, de modo que el intento que se quiere contar quede registrado aunque la petición principal revierta.

#### Scenario: Intento fallido sobre email inexistente queda registrado

- **WHEN** `POST /auth/login` falla para un email que no existe
- **THEN** la fila del intento queda persistida con email, IP, instante y resultado, aunque no haya fila alguna de usuario para ese email

### Requirement: Token de sesión solo en cookie HttpOnly (DD-04)

El token de sesión SHALL viajar únicamente en la cookie `HttpOnly` (`SameSite=Lax`, vencimiento configurable `TOKEN_EXPIRE_SEGUNDOS` y `Secure` configurable) y SHALL contener el identificador del usuario, el instante de emisión **completo** (con fracciones, sin truncar a segundos) y el vencimiento. El cuerpo de ninguna respuesta SHALL contener el token y la autenticación SHALL **nunca** leer `Authorization: Bearer`.

#### Scenario: Cabecera Bearer no aceptada

- **WHEN** una petición a una ruta protegida llega con `Authorization: Bearer <token>` y sin cookie de sesión
- **THEN** la API responde `401` (cabeceras de autorización no se leen ni se aceptan)

### Requirement: Rutas protegidas exigen sesión válida

Toda ruta del grupo protegido SHALL exigir la cookie de sesión con firma válida, no vencida y de un usuario activo, y SHALL cargar en cada petición al usuario y sus roles vigentes **desde la base**. Sin cookie, con firma inválida, vencida o con usuario desactivado, la ruta protegida SHALL responder `401`, y el usuario queda disponible para la lógica del endpoint.

#### Scenario: Sin cookie en ruta protegida

- **WHEN** una petición llega a una ruta del grupo protegido sin cookie de sesión
- **THEN** responde `401` con mensaje propio, sin llegar a la lógica del endpoint

#### Scenario: Token vencido o con firma inválida

- **WHEN** una ruta protegida recibe una cookie con token vencido o mal firmado
- **THEN** responde `401` con mensaje propio

#### Scenario: Usuario desactivado con token vigente

- **WHEN** un usuario desactivado conserva un token no vencido
- **THEN** las rutas protegidas responde `401` (el usuario se reconsulta en la base en cada petición)

### Requirement: Roles vigentes en la base deciden la autorización (RN-04)

Los roles incluidos en el token SHALL ser informativos. La comprobación de permisos por rol SHALL consultar las asignaciones vigentes en la base **en cada petición** (asignación no revocada y sin vencer); sin el rol requerido, la ruta SHALL responder `403` incluso con token válido.

#### Scenario: Rol revocado con sesión abierta denegado

- **WHEN** a un usuario se le revoca un rol mientras su sesión sigue abierta y vuelve a pedir la ruta que lo exigía
- **THEN** responde `403` sin esperar al vencimiento del token

#### Scenario: Rol vigente permitido

- **WHEN** un usuario con la asignación vigente pide la ruta que exige ese rol
- **THEN** responde como permitido (los roles de la petición se deciden con la consulta a la base, no con los del token)

### Requirement: Cambio de contraseña invalida sesiones anteriores (RN-07)

La API SHALL exponer `POST /auth/cambiar-password` (con sesión) que verifique la contraseña actual: inválida SHALL responder `401`; correcta SHALL actualizar el hash de la nueva (calculado fuera de la transacción, dentro del límite de 72 bytes), anotar el instante del cambio, limpiar la bandera de cambio obligatorio y emitir una cookie **nueva válida emitida después del cambio**. Todo token emitido **antes** del cambio SHALL ser rechazado comparando el instante de emisión completo con el instante del cambio (sin truncar a segundos); ningún token de sesiones anteriores vale, incluso del mismo segundo.

#### Scenario: Cambio correcto valida solo la cookie nueva

- **WHEN** el usuario cambia su contraseña con la actual correcta
- **THEN** responde `200` con la cookie nueva válida, la bandera de cambio obligatorio queda limpia y las rutas protegidas rechazan el token anterior con `401`

#### Scenario: Token emitido en el mismo segundo anterior rechazado

- **WHEN** la cookie anterior fue emitida en el segundo inmediatamente anterior al instante del cambio
- **THEN** las rutas protegidas responde `401`: la comparación no trunca a segundos (se compara el instante completo)

#### Scenario: Contraseña actual incorrecta o nueva inválida

- **WHEN** `POST /auth/cambiar-password` recibe una contraseña actual incorrecta (o una nueva fuera de los límites del contrato)
- **THEN** responde `401` (o `422` por validación del contrato) sin modificar hash, instante del cambio ni bandera

### Requirement: Cambio obligatorio bloquea el grupo protegido (RN-06, DD-10)

Mientras el usuario tenga el cambio de contraseña pendiente, las rutas del grupo protegido (excepto `/auth` y salud) SHALL responder `403` antes de ejecutar la lógica del endpoint; el control SHALL estar montado **una sola vez** sobre el grupo protegido (no ruta por ruta). Las rutas `/auth` y de salud SHALL seguir utilizables, y tras completar el cambio el usuario recupera el acceso al grupo protegido.

#### Scenario: Ruta protegida con cambio pendiente

- **WHEN** un usuario con cambio de contraseña pendiente intenta cualquier ruta fuera de `/auth` y salud
- **THEN** responde `403` con mensaje propio, sin ejecutar la lógica del endpoint ni escribir datos

#### Scenario: Tras el cambio el acceso se recupera

- **WHEN** el usuario completa el cambio de contraseña e intenta una ruta protegida con la cookie nueva
- **THEN** la ruta responde con su código propio (ya no queda bloqueado por la bandera)

### Requirement: Cierre de sesión

La API SHALL exponer `POST /auth/logout` (ruta pública) que borre la cookie de sesión y responda `200`, sin exigir una sesión válida.

#### Scenario: Logout borra la cookie

- **WHEN** `POST /auth/logout` llega con o sin cookie de sesión
- **THEN** responde `200` con la orden de borrado de la cookie (la sesión desaparece del cliente; el token no vuelve a ser aceptado tras expirar o tras un cambio de contraseña)

### Requirement: Identidad y roles consultables (US-006)

La API SHALL exponer `GET /auth/yo` (con sesión) que devuelva email, nombre, estado del cambio de contraseña, los roles vigentes leídos de la base en ese instante y los roles informativos del token, sin exponer nunca el hash de la contraseña.

#### Scenario: Consulta de identidad propia

- **WHEN** un usuario autenticado consulta `GET /auth/yo`
- **THEN** responde `200` con sus datos y roles, sin el campo del hash de contraseña

#### Scenario: Sin sesión no hay identidad

- **WHEN** `GET /auth/yo` llega sin cookie válida
- **THEN** responde `401` con mensaje propio

### Requirement: Fallos sin filtrar la base (RN-18)

Ningún fallo de autenticación o autorización SHALL exponer el hash de la contraseña, texto interno de PostgreSQL ni trazas: los errores de integridad (email duplicado) SHALL traducirse a `409` con mensaje propio y ningún fallo manejado SHALL terminar en `500`.

#### Scenario: Error de integridad traducido con mensaje propio

- **WHEN** la base rechaza una escritura por unicidad (email existente)
- **THEN** el cliente recibe `409` con un mensaje propio que no incluye el mapa del esquema, texto de la base ni trazas

#### Scenario: Entrada inválida nunca termina en 500

- **WHEN** cualquier endpoint de `/auth` recibe un cuerpo inválido (tipos incorrectos, campos extra, límites excedidos)
- **THEN** responde `422`/`401`/`409` según corresponda, nunca `500`, y ninguna respuesta contiene el hash de la contraseña
