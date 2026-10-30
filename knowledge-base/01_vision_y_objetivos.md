# Visión y Objetivos

## Propósito del sistema

API REST asincrónica para la gestión diaria de un **taller mecánico**: órdenes de trabajo, stock de repuestos, clientes y vehículos, con acceso por roles. El sistema reúne en un único proyecto los caps. 1–6 de Programación III (FastAPI, contratos/CRUD, asincronía, persistencia con Alembic, autenticación/autorización, repositorios + Unit of Work), demostrando una API en capas `Router → Service → UoW → Repository → Model` donde cada capa sabe lo suyo y nada más.

La recepción da de alta clientes y vehículos y abre una orden por ingreso; el mecánico la repara y al terminar se descuenta el stock; el administrador mantiene el catálogo, repone stock y administra personal y roles; el cliente se registra solo y consulta sus vehículos y órdenes.

## Objetivos por actor

| Actor | Objetivo principal | Objetivos secundarios |
|-------|-------------------|----------------------|
| ADMIN | Mantener catálogo de repuestos, reponer stock | Alta de personal, asignar/revocar roles con vigencia, terminar órdenes, ver eventos de seguridad |
| RECEPCION | Alta de clientes y vehículos; abrir órdenes | Cancelar órdenes, consultar clientes/vehículos/órdenes |
| MECANICO | Tomar (iniciar) y terminar órdenes asignadas | Consultar repuestos y sus movimientos/precios |
| CLIENTE | Registrarse y consultar sus vehículos y órdenes | Cancelar órdenes de sus vehículos pendientes |
| Sistema | Garantizar integridad, seguridad y auditoría | Límite de intentos de login, catálogo de estados, tablas de sólo agregado |

## Alcance v1.0

- API REST asincrónica (FastAPI + asyncpg/psycopg + PostgreSQL 16).
- Autenticación con bcrypt + JWT en cookie HttpOnly; autorización con roles vigentes consultados en la base en cada petición.
- Gestión completa de usuarios, roles (4 con vigencia/revocación), clientes, vehículos (borrado lógico), repuestos (stock + borrado lógico + historial de precios) y órdenes de trabajo con máquina de estados por catálogo.
- Transacciones con Unit of Work; repositorios genéricos (base + soft-delete); catálogo `estado_orden`; tablas de sólo agregado protegidas por disparador.
- Esquema versionado con Alembic (migración autogenerada + una escrita a mano); `seed.py` con datos mínimos; casos de prueba `.http` (C-01…C-19).
- Salud del proceso (`/health/live`) y de la base (`/health/ready`).
- Aviso al cliente simulado con `BackgroundTasks` al terminar una orden.

## Fuera de alcance

- **Concurrencia (cap. 7)**: no se evalúa bloqueos ni aislamiento; dos terminaciones simultáneas pueden producir una actualización perdida de stock (aceptado).
- **Colas con Redis (cap. 8)**: el aviso corre en el mismo proceso; si se reinicia se pierde, sin reintento (aceptado, el aviso es simulado).
- Frontend web / SPA: solo API (el auto-registro se menciona como contexto de dominio).
- Pagos, facturación, notificaciones reales (email/SMS), multi-taller.
- El segundo mecanismo de sólo agregado por permisos de rol de base (defensa en profundidad) no se pide: se usa un solo rol de base.

## Métricas de éxito

- Proyecto levanta desde cero: venv → deps → `.env` → `alembic upgrade head` → `python seed.py` → servidor.
- Ninguna entrada inválida termina en 500; 401 vs 403 siempre correctos; unicidad delegada a la base.
- Detalle de orden con consultas fijas (sin N+1) demostrado en consola (caso C-15).
- Disparador de sólo agregado rechaza UPDATE/DELETE en las tres tablas (C-14).
- Pesos de evaluación como proxy de completitud: UoW/repositorios 20%, auth 16%, modelos/migraciones 14%, autorización 14%, integridad 10%, CRUD 10%, config 8%, asincronía/N+1 8%.
