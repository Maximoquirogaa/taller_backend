# Spec – User Authentication (user-auth)

## Purpose
Provide a secure authentication mechanism for the API using JWTs stored in HttpOnly cookies and bcrypt password hashing. This capability enables user registration, login, logout, token refresh, and role‑based access control for protected routes.

## Requirements
- **R1**: Register a new user with a unique email and password. Password must be hashed with bcrypt (max 72 bytes) before persisting.
- **R2**: Login with email and password returns a JWT in an HttpOnly, SameSite=Lax cookie. The JWT includes the user ID and active roles.
- **R3**: Logout clears the authentication cookie.
- **R4**: Authenticated requests must read the JWT from the cookie, verify its signature, and expose `request.state.user` with role information.
- **R5**: Password change must invalidate existing tokens and set `debe_cambiar_password` flag.
- **R6**: All authentication failures return HTTP 401 without leaking internal error details.
- **R7**: Rate‑limit login attempts to 5 failures per 60 seconds per email+IP, returning 429 with `Retry‑After`.

## Scenarios
1. **Successful registration** – POST `/auth/registro` with unique email and password creates a `Usuario` row, assigns role `CLIENTE`, creates an initial `IntentoAcceso` row, and returns `201`.
2. **Duplicate email** – Returns `409`.
3. **Successful login** – Valid credentials return `200` and set authentication cookie.
4. **Invalid login** – Returns `401` after a fake bcrypt hash verification (constant‑time).
5. **Rate‑limit exceeded** – Returns `429` with `Retry‑After`.
6. **Logout** – Clears cookie, returns `200`.
7. **Protected endpoint without token** – Returns `401`.
8. **Protected endpoint with expired token** – Returns `401`.

## Non‑functional
- Use async bcrypt via `to_thread` and a semaphore.
- JWT signing key sourced from env `SECRET_KEY` (no default).
- Tokens have configurable expiration (`TOKEN_EXPIRE_SEGUNDOS`).
- All DB writes occur within a single Unit‑of‑Work transaction.
