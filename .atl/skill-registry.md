# Skill Registry

**Delegator use only.** Any agent that launches sub-agents reads this registry to resolve compact rules, then injects them directly into sub-agent prompts. Sub-agents do NOT read this registry or individual SKILL.md files.

See `_shared/skill-resolver.md` for the full resolution protocol.

## User Skills

Scanned `~/.agents/skills/` and `~/.config/opencode/skills/`. Skipped SDD workflow skills (`active-orchestrator`, `kb-creator`, `roadmap-generator`, `find-skill`, `agent-instruction`, `discovery-research`, `skill-creator`, `skill-registry`) — orchestrator-phase, not coding/task skills.

| Trigger | Skill | Path |
|---------|-------|------|
| FastAPI APIs, Pydantic models, dependencies, SSE streaming, serving frontend apps | fastapi | `C:\Users\Administrador\.agents\skills\fastapi\SKILL.md` |
| FastAPI Python development, APIs, async operations | fastapi-python | `C:\Users\Administrador\.agents\skills\fastapi-python\SKILL.md` |
| New FastAPI projects, async patterns, DI, error handling, project scaffolding | fastapi-templates | `C:\Users\Administrador\.agents\skills\fastapi-templates\SKILL.md` |
| Python backend with FastAPI, JWT/OAuth2, SQLAlchemy async, caching, deslopification | python-backend | `C:\Users\Administrador\.agents\skills\python-backend\SKILL.md` |
| Designing APIs, auth, DB query optimization, CI/CD, security, production backends | backend-development | `C:\Users\Administrador\.agents\skills\backend-development\SKILL.md` |
| SQLAlchemy models, Alembic migrations, schema changes, query optimization, migration review | sqlalchemy-alembic-expert-best-practices-code-review | `C:\Users\Administrador\.agents\skills\sqlalchemy-alembic-expert-best-practices-code-review\SKILL.md` |
| Database layer setup, models, migrations, queries, async session, connection pool | sqlalchemy-postgres | `C:\Users\Administrador\.agents\skills\sqlalchemy-postgres\SKILL.md` |
| SQLModel models, sessions, queries, FastAPI integration, relationships, CRUD | sqlmodel | `C:\Users\Administrador\.agents\skills\sqlmodel\SKILL.md` |
| Implementing auth systems, securing APIs, JWT, OAuth2, sessions, RBAC, auth debugging | auth-implementation-patterns | `C:\Users\Administrador\.agents\skills\auth-implementation-patterns\SKILL.md` |
| Add login/sign-up/auth to a TypeScript/JavaScript app with Better Auth | create-auth | `C:\Users\Administrador\.agents\skills\create-auth\SKILL.md` |
| E2E tests with Playwright/Cypress, flaky test debugging, testing standards | e2e-testing-patterns | `C:\Users\Administrador\.agents\skills\e2e-testing-patterns\SKILL.md` |
| JavaScript/TypeScript tests with Jest/Vitest/Testing Library, TDD, mocking | javascript-testing-patterns | `C:\Users\Administrador\.agents\skills\javascript-testing-patterns\SKILL.md` |
| Browser automation, test web pages, work with Playwright tests via CLI | playwright-cli | `C:\Users\Administrador\.agents\skills\playwright-cli\SKILL.md` |
| Interacting with/testing local web apps, screenshots, browser logs | webapp-testing | `C:\Users\Administrador\.agents\skills\webapp-testing\SKILL.md` |
| Design/redesign/critique/polish frontend UI, UX review, design systems | impeccable | `C:\Users\Administrador\.agents\skills\impeccable\SKILL.md` |
| Semantic HTML components, page structure, markup/accessibility review | semantic-html | `C:\Users\Administrador\.agents\skills\semantic-html\SKILL.md` |
| Review UI code against Web Interface Guidelines, accessibility/UX audit | web-design-guidelines | `C:\Users\Administrador\.agents\skills\web-design-guidelines\SKILL.md` |
| Build web components/pages/dashboards, styling or beautifying any web UI | frontend-design | `C:\Users\Administrador\.config\opencode\skills\frontend-design-local\SKILL.md` |
| React composition, compound components, render props, context providers, React 19 APIs | vercel-composition-patterns | `C:\Users\Administrador\.agents\skills\vercel-composition-patterns\SKILL.md` |
| React/Next.js performance: components, pages, data fetching, bundle optimization | vercel-react-best-practices | `C:\Users\Administrador\.agents\skills\vercel-react-best-practices\SKILL.md` |
| PostgreSQL query optimization, EXPLAIN, JSONB, VACUUM, replication, pg_stat | postgres-pro | `C:\Users\Administrador\.config\opencode\skills\postgres-pro\SKILL.md` |

## Compact Rules

Pre-digested rules per skill. Delegators copy matching blocks into sub-agent prompts as `## Project Standards (auto-resolved)`.

### fastapi
- Always `Annotated[...]` for params and dependencies; one type alias per dependency (`CurrentUserDep = Annotated[User, Depends(get_current_user)]`)
- Never use `...` defaults on required params/fields; never use Pydantic `RootModel` (use `Annotated[list[int], Field(...), Body()]`)
- Prefer return type annotations for responses; use `response_model` only when the public schema differs from the return value
- Put `prefix`/`tags`/shared deps on `APIRouter(...)`, not in `include_router()`
- One HTTP operation per function
- `def` by default (threadpool); `async def` only when every inner call is non-blocking — never block the event loop
- No `ORJSONResponse`/`UJSONResponse` (deprecated); SSE via `response_class=EventSourceResponse`
- Lifespan for startup/shutdown; prefer SQLModel over SQLAlchemy, HTTPX over Requests, uv/Ruff tooling

### fastapi-python
- Functional/declarative style over classes; `def` for pure functions, `async def` only for I/O
- Type-hint every signature; prefer Pydantic models over raw dictionaries
- snake_case files (`routers/user_routes.py`); descriptive names with auxiliary verbs (`is_active`, `has_permission`)
- Early returns and guard clauses at function entry, happy path last, avoid `else`
- Lifespan context managers for startup/shutdown; middleware for logging/monitoring
- `HTTPException` for expected errors; rely on FastAPI's dependency injection
- Minimize blocking I/O — async for all DB and external API calls; RORO pattern

### fastapi-templates
- Layout: `app/{api/v1/endpoints, core, models, schemas, services, repositories, main.py}`
- Deps: fastapi, uvicorn[standard], pydantic-settings, sqlalchemy[asyncio]>=2.0, asyncpg, PyJWT, pwdlib[argon2]; python-multipart only for OAuth2PasswordRequestForm
- Dev deps: pytest, pytest-asyncio, httpx, aiosqlite (test DB `sqlite+aiosqlite:///:memory:`)
- Async fixtures need `@pytest_asyncio.fixture` (strict mode default)
- httpx 0.28+ removed `AsyncClient(app=...)` — use `ASGITransport(app=app)`
- Tests: override `get_db` via `app.dependency_overrides`, clear overrides after each test
- Long-form patterns in `references/details.md`

### python-backend
- Async-first for all I/O; sync `def` routes for blocking code (threadpool), never block inside `async def`
- Fail fast: validate at entry with Pydantic (`EmailStr`, `Field(...)`), raise `HTTPException`, never trust user input
- Layout: `src/<feature>/{router,schemas,models,service,dependencies}.py` + `config.py`/`database.py`/`main.py`
- SQLAlchemy async: `create_async_engine(..., pool_pre_ping=True)` + `async_sessionmaker(expire_on_commit=False)` + generator dependency yielding session
- JWT/OAuth2/hashing/CORS rules in `references/security_patterns.md`; DB patterns in `references/database_patterns.md`
- Caching/rate limiting via Upstash Redis (`references/upstash_patterns.md`)

### backend-development
- Security: Argon2id password hashing, parameterized queries, OAuth 2.1 + PKCE, rate limiting, security headers, input validation
- PostgreSQL for ACID, Redis for caching, REST for public APIs, gRPC for internal services
- Testing pyramid 70-20-10 (unit-integration-E2E); contract tests for microservices
- API checklist: schema → validation → auth → rate limit → docs → error handling
- DB checklist: schema → indexes → connection pooling → migrations → backup → perf tests
- Detailed guidance in `references/` (backend-security, -authentication, -performance, -api-design, -testing, -devops)
- Blue-green/canary deploys, feature flags, OpenTelemetry tracing, Prometheus/Grafana

### sqlalchemy-alembic-expert-best-practices-code-review
- Always `postgresql_concurrently=True` inside autocommit blocks for index creation/changes
- Split unique constraint creation into concurrent unique index + separate constraint step
- Add FKs and CHECK constraints as `NOT VALID` first, then validate separately
- Column type changes: multi-step approach to avoid long table locks
- Limit non-unique composite indexes to ≤3 columns; drop redundant indexes covered by composite indexes
- Verify every query pattern is indexed (check with EXPLAIN)
- Per-rule explanations with good/bad examples in `rules/*.md`

### sqlalchemy-postgres
- Stack: SQLAlchemy 2.0 async (asyncpg) + Pydantic v2 + Alembic + PostgreSQL only
- Always 2.0 style `Mapped[]` / `mapped_column()` — never legacy `Column` or `declarative_base()`
- Separate layers: `models/` (DB) · `schemas/` (API, `model_config = ConfigDict(from_attributes=True)`) · `repositories/` · `services/`
- Async engine `postgresql+asyncpg://...` with async session factory + FastAPI session dependency
- Layout: `src/{db/{base,session,dependencies}, models, schemas, repositories, alembic}`
- Done when: pooling configured, Base with id/created_at/updated_at, repo pattern, Alembic async-ready

### sqlmodel
- SQLModel API first — never `declarative_base()`, `Mapped[]`, `mapped_column()`, `relationship()`, `sessionmaker()` for normal code
- Import from `sqlmodel`; table models `SQLModel, table=True` + `Field()`; non-table SQLModel classes for create/update/public schemas
- Queries: `session.exec(select(Model))` (never `.execute()`/`.query()`, no `.scalars()`); `session.get(Model, id)` for PK lookups
- Split pattern: `XBase` / `X(XBase, table=True)` / `XCreate` / `XUpdate` (all-optional) / `XPublic`
- Partial update: `model_dump(exclude_unset=True)` → `db_obj.sqlmodel_update(...)` → commit → refresh
- Datetimes (0.0.45+): plain aware `datetime` fields (auto UTCDateTime); never `sa_type=DateTime(timezone=True)`; `default_factory=lambda: datetime.now(UTC)`
- Relationships via `Relationship(back_populates=...)`, `link_model` for M2M, `cascade_delete`/`ondelete` for deletes; `create_all` only after all models imported

### auth-implementation-patterns
- Never store plain passwords — always bcrypt/argon2 hashing
- Short-lived access tokens (15–30 min max); rotate JWT/session secrets regularly
- Tokens in httpOnly+secure+sameSite cookies, not localStorage (XSS); CSRF protection for session auth
- Always validate auth server-side; never trust client data; rate-limit auth endpoints
- Enforce password strength, log security events (login attempts, failures), use MFA when possible
- Separate AuthN (identity) from AuthZ (permissions); RBAC + resource ownership checks
- Use HTTPS everywhere; secure password reset tokens with expiration

### create-auth
- Better Auth is TypeScript/JavaScript only — not applicable to Python/FastAPI projects (use auth-implementation-patterns instead)
- Phase 1 planning REQUIRED: scan project (framework, DB/ORM, existing auth, package manager) → ask all questions in one call → present plan → get confirmation before code
- Config split: server `auth.ts`, client `auth-client.ts`, route handler `app/api/auth/[...all]/route.ts`
- CLI drives schema: `npx auth@latest` install/generate/migrate — re-run generate/migrate after any plugin addition (fixes type errors)
- Security checklist: `BETTER_AUTH_SECRET` 32+ chars, `advanced.useSecureCookies: true` in prod, `trustedOrigins`, rate limits, email verification, never disable CSRF
- Protected routes: check session server-side (`auth.api.getSession`), redirect to `/sign-in` when null

### e2e-testing-patterns
- E2E only for critical journeys, auth flows, cross-browser — unit logic and API contracts belong in unit/integration tests
- Selectors: `data-testid`/role/label — never CSS classes or `nth-child`
- Tests independent and deterministic; create and destroy test data per test; page objects for page logic
- Wait on conditions/networkidle, never fixed timeouts; mock external APIs for speed; parallelize
- Debug: headed mode, `--debug`, trace/screenshot/video, `test.step` for reporting, `page.pause()`
- Test user-visible behavior, not implementation details; meaningful assertions on visible outcomes

### javascript-testing-patterns
- AAA (Arrange-Act-Assert); one or logically related assertions per test; descriptive test names
- Test behavior, not implementation; cover edge cases and error paths, not just happy path
- Mock external dependencies for isolation; faker factories with `overrides` for test data
- Integration tests: supertest + real test DB, truncate in `beforeEach`, teardown in `afterAll`
- Testing Library: prefer semantic queries (`getByRole`, placeholder) over `data-testid`
- `beforeEach`/`afterEach` for setup/teardown; clean up to prevent pollution; keep tests fast
- Aim 80%+ coverage; TDD when possible; type-safe tests via TypeScript

### playwright-cli
- Drive the browser with `playwright-cli` commands (`open`, `goto`, `click e15`, `type`, `snapshot`, `close`); allowed tools are playwright-cli/npx playwright only
- Target elements by snapshot refs first; CSS selectors and `getByRole(...)`/`getByTestId(...)` locators also work
- Every command returns a page + snapshot — use `find "text"` / `find --regex` and `snapshot --depth=N` instead of dumping huge snapshots
- Named sessions `-s=name` for isolation/persistence; always clean up (`close`, `close-all`, `kill-all`)
- Storage/cookies: `state-save`/`state-load`, `cookie-set --httpOnly --secure`
- Advanced flows (request mocking, wait strategies, downloads, frames) in `references/*.md`

### webapp-testing
- Write native Python Playwright scripts for local web apps
- Run helper scripts with `--help` first and treat `scripts/` as black boxes — never read their source unless truly necessary (context pollution)
- Server lifecycle: `python scripts/with_server.py --server "cmd" --port N -- python your.py` (supports multiple servers)
- Always `page.wait_for_load_state('networkidle')` before inspecting dynamic pages
- Reconnaissance-then-action: screenshot → inspect DOM → discover selectors → act
- `sync_playwright()`, chromium headless, always `browser.close()`

### postgres-pro
- Always `EXPLAIN (ANALYZE, BUFFERS)` before and after any index/query change; verify the planner actually uses the index
- `CREATE INDEX CONCURRENTLY` for production index changes; partial indexes for filtered hot paths
- Never `SELECT *` in production queries; never disable autovacuum globally; never create indexes without analyzing query patterns first
- Index type by workload: B-tree / GIN (JSONB containment `@>`) / GiST / BRIN
- Run `ANALYZE` after bulk changes; tune `autovacuum_vacuum_scale_factor` for high-churn tables
- Monitor via `pg_stat_*` views (dead tuples, `pg_stat_replication` lag); use connection pooling (pgbouncer)
- `uuid` type for UUIDs (not `text`); prepared statements to prevent SQL injection

### impeccable
- Run `<skill-base>/scripts/impeccable context` once per session (Windows: `impeccable.cmd`); follow its directives, do not rerun
- Read `reference/craft-floor.md` immediately before any UI edit (quality floor, absolute bans); skip only for planning-only work
- The brief wins — honor pinned aesthetics even over saturated-pattern warnings; refinement preserves, redesign replaces (never polish the discarded look)
- Choose mode from the surface (Persuade/Operate/Read/Experience), persist only in that surface's brief
- Verify by looking at the rendered result at shipping sizes; batch checks rather than screenshotting every tweak
- No argument → read `reference/routing.md` and present the menu; never auto-run a command
- Report `CONTEXT_STALE` findings, never repair drift as a side effect of a design task (except `auto` findings)

### semantic-html
- Native HTML over ARIA (first rule of ARIA); never override native semantics with `role`; no redundant ARIA (`role="list"` on `<ul>`, duplicate `aria-label`)
- Landmarks-first planning; skip link is the first focusable element in `<body>` targeting `<main id="main-content" tabindex="-1">`
- Heading levels follow document structure, never appearance; visual size via CSS classes (e.g. `.u-Heading-XXL`)
- Buttons for actions, links for navigation; repeated buttons need unique accessible names
- Forms: `fieldset`/`legend` grouping, real `<label>`s, hint text, error messages tied to inputs
- Tables only for genuine tabular data; responsive table strategies; design for content realism (long words, multi-language, dynamic length)
- Red flags: high div+ARIA counts on simple components, headings chosen for looks

### web-design-guidelines
- Fetch fresh guidelines before every review: `https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md` (WebFetch)
- Read the target files, apply ALL rules from the fetched guidelines
- Output findings in the terse `file:line` format specified by the guidelines
- If no file/pattern argument is given, ask the user which files to review

### frontend-design
- Commit to one bold aesthetic direction before coding (purpose, tone, constraints, differentiation) — intentionality over intensity
- NEVER generic AI aesthetics: no Inter/Roboto/Arial/system fonts, no purple-gradient-on-white clichés, no predictable layouts
- Typography: distinctive display + refined body font pairing; CSS variables for color/theme; dominant colors with sharp accents
- Motion: CSS-only for HTML, Motion library for React; one orchestrated staggered page-load reveal beats scattered micro-interactions
- Spatial composition: asymmetry, overlap, grid-breaking, deliberate negative space or controlled density; atmospheric backgrounds (meshes, noise, grain)
- Match implementation complexity to the vision: maximal needs elaborate code, minimal needs restraint and precision

### vercel-composition-patterns
- Never add boolean props to customize behavior — use composition, compound components, or explicit variant components
- Children over render props (`renderX` props only where children can't work)
- Provider is the only place that knows how state is managed; define a generic context interface (state, actions, meta); lift state into providers for sibling access
- React 19+ only: no `forwardRef` (ref is a plain prop), `use()` instead of `useContext()`
- Rule files under `rules/` by prefix (`architecture-`, `state-`, `patterns-`, `react19-`); full guide in `AGENTS.md`

### vercel-react-best-practices
- Priority: eliminate waterfalls (`Promise.all` for independent ops, cheap sync checks before any `await`, Suspense streaming) > bundle size (direct imports, no barrel files, `next/dynamic` for heavy components)
- Server: `React.cache()` for per-request dedup, hoist static I/O to module level, no module-level mutable request state in RSC/SSR, minimize data serialized to client
- Re-render: derive state during render (not effects), functional `setState`, primitive effect deps, never define components inside components, refs for transient values
- Rendering: ternary not `&&` for conditionals, hoist static JSX, `content-visibility` for long lists
- JS perf: `Set`/`Map` for O(1) lookups, early exit, hoist RegExp out of loops, combine iterations, `toSorted()` for immutability
- Individual rules in `rules/*.md` (category prefixes: `async-`, `bundle-`, `server-`, `client-`, `rerender-`, `rendering-`, `js-`, `advanced-`)

## Project Conventions

| File | Path | Notes |
|------|------|-------|
| _(none found)_ | — | No AGENTS.md/agents.md, CLAUDE.md, .cursorrules, GEMINI.md, or copilot-instructions.md at project root yet |

No convention files exist at this phase (agent-instruction runs after skill-registry). Re-run this registry after AGENTS.md/CLAUDE.md is generated so referenced paths can be extracted here.
