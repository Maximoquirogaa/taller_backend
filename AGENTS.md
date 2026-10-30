# TP Taller Mecánico — Instrucciones para Agentes

> Este archivo (y su copia `CLAUDE.md`) es lo PRIMERO que todo agente lee al entrar al repo.
> Generado a partir de `knowledge-base/` y `CHANGES.md`. No editar a mano sin re-sincronizar ambos archivos.

---

## Stack Tecnológico

| Capa | Tecnología | Versión |
|------|------------|---------|
| Lenguaje | Python | 3.12 |
| Framework | FastAPI (handlers `async def`) | 0.111+ |
| Modelos | SQLModel | 0.0.24 |
| ORM/Motor | SQLAlchemy asincrónico | 2.0 |
| Driver PG | asyncpg (psycopg 3 asincrónico aceptado) | 0.30 |
| Base | PostgreSQL | 16 |
| Migraciones | Alembic (plantilla asincrónica) | 1.13 |
| Config | pydantic-settings | 2.0 |
| Auth | bcrypt + PyJWT (cookie HttpOnly) | 4.0 / 2.8 |
| Servidor | uvicorn (via fastapi[standard]) | — |

Detalle completo: [knowledge-base/02_descripcion_general.md](knowledge-base/02_descripcion_general.md)

---

## Base de Conocimiento

La fuente de verdad del dominio vive en `knowledge-base/`. **Leé el archivo relevante ANTES de implementar.**

| Archivo | Cuándo leerlo |
|---------|---------------|
| [01_vision_y_objetivos.md](knowledge-base/01_vision_y_objetivos.md) | Propósito, actores, alcance, fuera de alcance |
| [03_actores_y_roles.md](knowledge-base/03_actores_y_roles.md) | Auth, RBAC, permisos, rutas |
| [04_modelo_de_datos.md](knowledge-base/04_modelo_de_datos.md) | 13 tablas, ERD, restricciones, seed |
| [05_reglas_de_negocio.md](knowledge-base/05_reglas_de_negocio.md) | Reglas codificadas (RN-01…RN-20) |
| [06_funcionalidades.md](knowledge-base/06_funcionalidades.md) | 31 historias de usuario por épica |
| [07_flujos_principales.md](knowledge-base/07_flujos_principales.md) | Flujos E2E (login, UoW de terminar orden, etc.) |
| [08_arquitectura_propuesta.md](knowledge-base/08_arquitectura_propuesta.md) | Patrones, estructura obligatoria, env vars |
| [09_decisiones_y_supuestos.md](knowledge-base/09_decisiones_y_supuestos.md) | DD-01…DD-12 y supuestos |
| [10_preguntas_abiertas.md](knowledge-base/10_preguntas_abiertas.md) | Dudas (Alta resueltas) y supuestos |
| [11_evidencias_c14_c15.md](knowledge-base/11_evidencias_c14_c15.md) | Cómo correr y capturar C-14/C-15 |

> ✅ Las preguntas de prioridad **Alta** de `10_preguntas_abiertas.md` ya están resueltas: driver **asyncpg** (P-01) y evidencias **capturas** con instrucciones en [11_evidencias_c14_c15.md](knowledge-base/11_evidencias_c14_c15.md) (P-02).

---

## Skills Disponibles

Fuente de verdad: `.atl/skill-registry.md` (generado por `skill-registry`). Filas adaptadas a las skills realmente instaladas:

| Agente | Rol | Skills que carga |
|--------|-----|------------------|
| **Backend Core** | FastAPI / SQLModel / UoW / migraciones | `fastapi`, `fastapi-python`, `fastapi-templates`, `sqlmodel`, `sqlalchemy-alembic-expert-best-practices-code-review`, `sqlalchemy-postgres` |
| **Backend Aux** | Auth, seguridad, patrones de servicio | `auth-implementation-patterns`, `python-backend`, `backend-development` |
| **Datos** | Optimización PostgreSQL | `postgres-pro` |
| **Testing** | Checks de app local | `webapp-testing`, `playwright-cli` |
| **Orquestación** | SDD / OPSX / docs del proyecto | `active-orchestrator`, `kb-creator`, `roadmap-generator`, `agents-md-generator`, `skill-creator` |

> Frontend (`impecable`, `frontend-design`, `vercel-*`, etc.) existe instalado pero el TP es **solo API** — no cargar skills de UI salvo que aparezca un task de eso.

Cargá la skill correspondiente al contexto ANTES de escribir código.

> Los compact rules de cada skill los resuelve el orquestador desde `.atl/skill-registry.md` (generado por `skill-registry`; no versionado — no está en el repo). Esta tabla solo mapea skill→rol.

---

## Roadmap de Changes

El plan de implementación completo está en [CHANGES.md](CHANGES.md). Resumen:

- **Total**: 11 changes en 6 fases.
- **Camino crítico**: `C-01 → C-02 → C-03 → C-05 → C-07 → C-08 → C-11` (C-09 y C-10 en paralelo, indispensables para la entrega).
- **Críticos**: C-02 (modelos/UoW), C-03 (auth), C-08 (máquina de estados), C-09 (disparadores).
- **Primer change**: `C-01` (foundation-setup).

**Antes de cualquier `/opsx:propose`**: leé [CHANGES.md](CHANGES.md), identificá las dependencias del change y los archivos de "Leer antes".

---

## Reglas Duras (específicas del proyecto)

> No existe `~/.claude/CLAUDE.md` global en este entorno: estas reglas son contrato completo del proyecto. Romperlas es un defecto. Formato `NUNCA X → hacer Y`:

- **Esquema solo Alembic** — NUNCA crear tablas con `create_all` ni aplicar `ALTER` a mano fuera de una migración → el esquema sale únicamente de `alembic upgrade head`; el entregable tiene **exactamente dos migraciones**: `001_esquema_inicial` (autogenerada con todos los modelos) y `002_disparador_solo_agregado` (escrita a mano). Las migraciones incrementales de cada change son de desarrollo y **C-11 las consolida**.
- **UoW manda las transacciones** — NUNCA `commit()` en repositorios (solo `flush()`) ni construir el UoW en el servicio → el router construye el UoW con dependencia; el servicio lo abre con `async with`; las multi-escrituras (RN-02, RN-13, RN-20) van en un solo bloque.
- **bcrypt asincrónico** — NUNCA ejecutar bcrypt dentro del bucle de eventos ni dentro de la transacción → `to_thread` + semáforo, y el hash se calcula antes de abrir el UoW; campos bcrypt máx. 72 bytes.
- **Token solo en cookie** — NUNCA devolver el JWT en el cuerpo ni leer `Authorization: Bearer` → solo cookie HttpOnly (SameSite=Lax, Max-Age, Secure configurable); Bearer o sin cookie → 401.
- **Stock solo con movimientos** — NUNCA editar `stock` por PATCH ni con UPDATE directo → el stock solo cambia vía `movimiento_stock` (alta inicial, reposición, terminación de órdenes).
- **Tablas append-only** — NUNCA modificar ni borrar filas de `historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto` → sólo agregado garantizado por el disparador (migración escrita a mano).
- **Errores sin filtrar la base** — NUNCA exponer `password_hash`, texto interno de PostgreSQL ni trazas al cliente → mensajes propios; traducir `IntegrityError` a 409; ninguna entrada inválida termina en 500.
- **Roles en la base** — NUNCA autorizar con los roles del token → consultar `asignacion_rol` vigente en cada petición; distinguir siempre 401 (sin sesión/válida) de 403 (sin permiso o cambio de contraseña pendiente).
- **Sin lazy loading** — NUNCA depender de la carga perezosa → toda relación que se lee se precarga en el repositorio (detalle de orden con número fijo de consultas, sin N+1).
- **Secretos solo en entorno** — NUNCA valores por defecto para `SECRET_KEY` ni `POSTGRES_PASSWORD` (si faltan, la app no arranca) → configuración vía entorno/`.env`; `.env` no se versiona; `env.example` sin secretos.
- **Contratos estrictos** — NUNCA mezclar contratos con modelos de tabla ni confiar el input → schemas con `extra="forbid"`, PATCH con `exclude_unset`, `snake_case` y type hints en todo el código Python.

---

## Flujo de Trabajo

```
1. Leer la KB relevante (knowledge-base/)        → entender el dominio
2. Identificar el change en CHANGES.md           → respetar dependencias
3. /opsx:propose C-NN-nombre                     → proposal + design + specs + tasks
4. Implementar las tasks (cargando skills)       → respetando las reglas duras
5. /opsx:archive C-NN-nombre + marcar [x]        → cerrar el change
```

Aplicar TODAS las reglas duras en cada paso. Ante conflicto entre la KB y este archivo, las reglas duras prevalecen.
