# Tasks – User Authentication (c-03-auth)

## Implementation Checklist

- [ ] **Model & Migration**
  - Verify that `c-02-core-models` already created the tables `usuario`, `asignacion_rol`, `intento_acceso`, `evento_seguridad`.
  - If any column is missing (e.g., `debe_cambiar_password`, `bcrypt_hash`), add it via a new migration (incremental) and run `alembic upgrade head`.

- [ ] **Password hashing utilities**
  - Implement `hash_password` and `verify_password` in `app/core/security.py` using async `bcrypt` via `to_thread` and a semaphore.
  - Add configuration `BCRYPT_COST` (default 12) in `app/core/config.py`.

- [ ] **JWT utilities**
  - Implement `create_access_token` and `decode_token` in `app/core/security.py` using `pyjwt`.
  - Ensure `SECRET_KEY` is required in the environment; raise error if missing.
  - Add `TOKEN_EXPIRE_SEGUNDOS` config (default 1800).

- [ ] **Auth router** (`app/modules/auth/router.py`)
  - `POST /auth/registro` – create `Usuario`, assign role `CLIENTE`, create initial `IntentoAcceso`, return `201`.
  - `POST /auth/login` – verify credentials, rate‑limit (5 attempts/60 s per email+IP), set HttpOnly cookie with JWT, return `200`.
  - `POST /auth/logout` – clear cookie, return `200`.
  - `POST /auth/cambiar-password` – validate old password, hash new one, update user, clear existing tokens, set `debe_cambiar_password` to `false`.
  - Add proper response models (`pydantic.BaseModel` with `extra="forbid"`).

- [ ] **Dependencies** (`app/core/dependencies.py`)
  - `usuario_actual` – read cookie, verify JWT, load user and active roles from DB, raise `HTTPException(401)` if invalid.
  - `requiere_rol` – decorator that checks required role(s) and raises `403` when missing.

- [ ] **Rate limiting**
  - Implement a simple in‑memory counter keyed by `email+IP` with a 60‑second window; return `429` with `Retry‑After` on exceed.

- [ ] **OpenAPI security scheme**
  - Add `securitySchemes` entry for cookie‑based JWT in `app/main.py` (FastAPI `openapi_schema`).

- [ ] **Tests** (`test/auth/`)
  - Unit tests for password hashing (verify correct/incorrect).
  - Integration tests for each endpoint:
    - Registration success & duplicate email → 201 / 409.
    - Login success, failure, rate‑limit → 200 / 401 / 429.
    - Logout clears cookie.
    - Protected route accessed with/without valid token → 200 / 401.
    - Password change updates hash, invalidates previous token.
  - Use a test DB fixture (`pytest‑asyncio` + `asyncpg`) and roll back after each test.

- [ ] **Documentation**
  - Update `knowledge-base/03_actores_y_roles.md` with auth flow.
  - Add OpenAPI examples for auth endpoints.

- [ ] **CI validation**
  - Ensure `pytest` passes (≥ 66 tests) and `alembic check` reports no schema drift.

- [ ] **Engram save**
  - After completing each bullet, commit a `mem_save` entry (automated by the orchestrator).

---
**When all checkboxes are ticked, run** `openspec validate c-03-auth` **to confirm the change is ready for apply.**