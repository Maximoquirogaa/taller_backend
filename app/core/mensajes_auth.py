"""Contratos de sesión y errores del módulo auth (el cliente no ve nunca el token).

Los mensajes de error de sesión viven acá para que 401 tenga el mismo cuerpo en
todas las rutas (RN-09 exige idéntico login; RN-18 pide mensajes propios sin
 texto de la base).
"""

MENSAJE_CREDENCIALES_INVALIDAS = "Credenciales inválidas: revisá el email y la contraseña."
MENSAJE_SESION_INVALIDA = "Sesión inválida o vencida: iniciá sesión de nuevo."
MENSAJE_SIN_PERMISO = "No tenés permiso para usar esta acción."
MENSAJE_CAMBIO_PENDIENTE = "Tenés el cambio de contraseña pendiente: cambiá la contraseña para seguir."
MENSAJE_SESION_CERRADA = "Sesión cerrada."
MENSAJE_EMAIL_DUPLICADO = "El email ya está registrado."
MENSAJE_LIMITE_INTENTOS = "Demasiados intentos fallidos: esperá antes de volver a intentar."

ROL_CLIENTE = "CLIENTE"
NOMBRE_COOKIE_SESION = "access_token"
