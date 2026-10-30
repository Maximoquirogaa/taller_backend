# Proposal

## Why
Add a robust authentication system to the API. The current project lacks JWT-based login, password hashing, and role‑based access control, which are required by the specification and security rules. Implementing auth early enables all subsequent functional changes (clients, orders, etc.) to be protected.

## What Changes
- Introduce JWT authentication stored in HttpOnly cookies.
- Add bcrypt password hashing for user registration and password changes.
- Create login, logout, and token refresh endpoints.
- Add middleware to extract the current user and enforce role‑based permissions.
- Register new database models: `Usuario`, `AsignacionRol`, `IntentoAcceso`, `EventoSeguridad`.
- Update the FastAPI app to mount protected routes under a security group.
- Add OpenAPI security scheme definitions.

## Capabilities

### New Capabilities
- `user-auth`: Handles user registration, login, logout, password management, and JWT cookie handling. This capability defines the public authentication API and internal security checks.

### Modified Capabilities
- *(none)* – No existing capabilities are altered; this change introduces a completely new authentication layer.

## Impact
- New tables in PostgreSQL (`usuario`, `asignacion_rol`, `intent_acc`, `evento_seguridad`).
- All protected endpoints will now require a valid session cookie.
- Existing health checks remain unchanged.
- Front‑end clients must include credentials for login requests.
- Security audits must verify the JWT signing key is stored in environment variables.
