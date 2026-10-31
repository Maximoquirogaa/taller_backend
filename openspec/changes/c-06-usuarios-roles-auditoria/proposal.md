# Proposal: Usuarios, Roles y Auditoría (c-06-usuarios-roles-auditoria)

## Why
C-03 dejó la autenticación completa (registro, login, sesión y cambio de contraseña), pero el taller no tiene forma de administrar a su personal: no existe `POST /usuarios`, no se pueden otorgar ni revocar roles con vigencia y ningún suceso de acceso queda auditado más allá de `intento_acceso`. Sin esta capa, RN-04 (autorización por roles vigentes en la base) no tiene quién cambie esos roles, RN-05 (autoprotección del administrador) no se puede garantizar y la consigna no puede demostrar la auditoría de US-011.

## What Changes
- Nuevo router protegido `router_usuarios` (`app/modules/usuarios/router.py`) montado en `router_protegido` (`main.py`), con todo el ciclo bajo `requiere_rol("ADMIN")`.
- `POST /usuarios`: alta de personal con contraseña provisoria, `debe_cambiar_password=true` y evento de seguridad en la misma transacción (US-008, RN-01).
- `POST /usuarios/{id}/roles`: otorgamiento de rol con `vencimiento` opcional, obligatoriamente con zona horaria y en el futuro; 409 si ya hay una asignación abierta del mismo rol; reasignar un rol vencido o revocado abre una fila nueva sin tocar el historial (US-009, RN-03).
- `DELETE /usuarios/{id}/roles/{rol}`: revocación que escribe `revocada_en` sobre la fila vigente (nunca `DELETE`) y 409 cuando un ADMIN intenta revocar su propio `ADMIN` (US-010, RN-05).
- `GET /eventos`: listado paginado del `evento_seguridad` con el envoltorio estándar y los 422 de `page`/`size` (US-011).
- Ampliación del UoW y los repositorios del módulo: `eventos` en `UoWUsuarios`, más `revocar`, `get_abierta` y `get_vigentes`/`get_historial` en `RepositorioRoles`, y `buscar_paginado` en un `RepositorioEventos` nuevo.
- Instrumentación de auditoría en el cambio de contraseña existente de C-03 (`service.cambiar_password`) para que deje su `evento_seguridad`.
- Limpieza: eliminar el `print("[DEBUG-401] ...")` de `app/core/dependencies.py`.
- **Sin migración**: `usuario`, `asignacion_rol` y `evento_seguridad` existen desde `001_esquema_inicial`; el número `005` queda reservado para C-07.

## Capabilities

### New Capabilities
- `usuarios-roles-auditoria`: administración del personal y de sus roles con vigencia (alta de empleado, otorgamiento, revocación y autoprotección del administrador) y la auditoría de seguridad consultable que registra esos cambios y los cambios de contraseña.

### Modified Capabilities
- *(none)*. El cambio instrumenta `POST /auth/cambiar-password` para escribir un evento, pero no altera ninguna garantía de la capability `user-auth`: sigue respondiendo 200 con la cookie nueva y sigue invalidando los tokens anteriores. La auditoría es comportamiento nuevo y por eso se especifica en `usuarios-roles-auditoria` (ver `design.md`, decisión 1).

## Impact
- **Base de datos**: sin migración ni cambios de esquema; se usan `usuario`, `asignacion_rol` (índice parcial `uq_asignacion_rol_abierta`) y `evento_seguridad` ya existentes.
- **API**: cuatro rutas nuevas (`POST /usuarios`, `POST /usuarios/{id}/roles`, `DELETE /usuarios/{id}/roles/{rol}`, `GET /eventos`) que requieren cookie de sesión y rol `ADMIN` vigente; 401 sin sesión, 403 sin rol o con cambio de contraseña pendiente.
- **Código**: `app/modules/usuarios/{router,schemas,service,repository,unit_of_work}.py`, `app/modules/usuarios/mensajes.py` (mensajes propios nuevos), `main.py` y `app/core/dependencies.py`.
- **Tests**: nueva carpeta `test/usuarios/` (`conftest.py`, `test_models.py`, `test_repository.py`, `test_service.py`, `test_router.py`).
- **Dependencias**: C-03 (auth, `usuario_actual`, `requiere_rol`, `hash_password`). Habilita C-07 en adelante con un ADMIN capaz de repartir roles reales.
