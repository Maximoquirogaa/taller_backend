# Design – User Authentication (user-auth)

## Architecture Overview
The authentication layer is built as a set of FastAPI routers mounted under `/auth`. It consists of:
1. **Password hashing** – async bcrypt via `to_thread` and a semaphore to avoid blocking the event loop.
2. **JWT handling** – `pyjwt` creates signed tokens with the secret key from `SECRET_KEY`. Tokens are stored in an HttpOnly, SameSite=Lax cookie with configurable expiration (`TOKEN_EXPIRE_SEGUNDOS`).
3. **Unit of Work (UoW)** – All write operations (registration, login, password change) are performed inside a single `async with uow:` block. The UoW flushes but never commits; the FastAPI lifespan handles transaction commit/rollback.
4. **Role‑based Access Control** – A dependency `usuario_actual` reads the cookie, validates the token, loads the user and active roles from the DB, and raises `HTTPException(401)` if missing or invalid. RBAC checks are performed via a `requiere_rol` dependency.
5. **Rate limiting** – A simple in‑memory counter keyed by `email+IP` with a 60‑second window; exceeding 5 attempts returns `429` with `Retry‑After`.

## Data Flow
```
Client → POST /auth/registro → bcrypt hash → DB (Usuario, AsignacionRol) → 201
Client → POST /auth/login → bcrypt verify → JWT sign → Set‑Cookie (HttpOnly) → 200
Client → any protected route → Cookie → JWT verify → DB role lookup → request.state.user
Client → POST /auth/logout → Clear cookie → 200
```

## Components
- **`app/core/security.py`** – functions `hash_password`, `verify_password`, `create_access_token`, `decode_token`.
- **`app/modules/auth/router.py`** – FastAPI router exposing `registro`, `login`, `logout`, `cambiar-password`.
- **`app/core/dependencies.py`** – `usuario_actual` and `requiere_rol` dependencies.
- **`app/core/unit_of_work.py`** – Context manager handling DB session lifecycle.
- **`app/core/paginacion.py`** – reused for pagination of login attempts (optional).

## Error Handling
- All auth failures return generic `401` without exposing whether the email exists.
- Database integrity errors (duplicate email) are caught and translated to `409`.
- Rate‑limit violations return `429` with a proper `Retry‑After` header.
- Token expiration and revocation (password change) result in `401`.

## Security Considerations
- Bcrypt runs off‑thread; max cost defined by `BCRYPT_COST` env variable.
- Secret key never defaults; app fails to start if missing.
- Tokens contain only `sub` (user ID) and `roles`; no sensitive data.
- Cookie is `HttpOnly`, `Secure` configurable, `SameSite=Lax`.
- All write paths are wrapped in a single UoW to ensure atomicity.

## Migration Impact
- New tables (`usuario`, `asignacion_rol`, `intento_acceso`, `evento_seguridad`) added via the **core‑models** change (C‑02).
- No schema changes to existing tables.

## Open Questions
- Whether to support refresh tokens (out of scope for this change).
- Rate‑limit storage persistence (in‑memory acceptable for now).
