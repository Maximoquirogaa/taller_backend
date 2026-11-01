# Proposal

## Why

Hoy `seed.py` es un stub que aborta con "pendiente hasta C-10". Sin datos iniciales la API arranca con el catálogo `estado_orden` **vacío** (por diseño, DD-01), ninguna orden se puede crear (RN-19 responde 409), no hay usuarios para iniciar sesión y no existe el caso de stock insuficiente que la consigna pide demostrar.

La entrega y la corrección necesitan un estado inicial **conocido y reproducible**: el mismo taller (usuarios por rol, clientes, vehículos, repuestos con stock, dos órdenes en estados distintos) después de `alembic upgrade head` y `python seed.py`, en cualquier máquina. Además C-11 depende de este script para consolidar migraciones y capturar la evidencia C-14 (el script `test/solo_agregado.sql` necesita filas reales para que el disparador de fila se active).

## What Changes

- `seed.py` deja de ser un stub y pasa a ser un script ejecutable (`python seed.py`) que deja la base en el estado inicial del TP.
- Vacía las 13 tablas (`TRUNCATE ... RESTART IDENTITY CASCADE`) y carga en orden de dependencias:
  1. Catálogo `estado_orden`: PENDIENTE(1), EN_REPARACION(2), TERMINADA(3, final), CANCELADA(4, final).
  2. Usuarios con contraseñas ficticias fijas y sus asignaciones de rol: `admin@`, `admin2@` (ADMIN), `recepcion@` (RECEPCION), `mecanico@`, `mecanico2@` (MECANICO), `cliente@` (CLIENTE), `nuevo@` (MECANICO con cambio de contraseña obligatorio).
  3. Clientes: Laura (vinculada a `cliente@`) con 2 vehículos y Jorge (sin usuario) con 1 vehículo.
  4. Repuestos: filtro de aceite (stock 10), pastillas de freno (4), bujía (2), aceite por litro (20), cada uno con su alta de stock registrada como `movimiento_stock`.
  5. Historial de precios del filtro: 8000 → 8500.
  6. Órdenes: una PENDIENTE (vehículo de Laura) y una EN_REPARACION (vehículo de Jorge, asignada a `mecanico@`) cuyo ítem pide **4 bujías con stock 2** — el caso de stock insuficiente que pide la consigna.
  7. Evento de seguridad `SISTEMA` «Carga de los datos iniciales».
- Re-ejecutable: correr el script dos veces deja exactamente el mismo estado (no acumula filas ni falla por unicidad).
- Tests: `test/test_seed.py` ejecuta la carga sobre la base de pruebas dos veces y verifica catálogo, conteos, roles, stock inicial como movimiento, credenciales utilizables y el caso de stock insuficiente.
- Se documenta en el propio `seed.py` (docstring) la lista de credenciales ficticias, para que el corrector pueda entrar sin adivinar.

## Capabilities

### New Capabilities

- `seed-inicial`: define qué estado deja la carga inicial del taller, sus garantías de reproducibilidad e idempotencia, las credenciales de ejemplo y las precondiciones de datos que la entrega necesita (stock inicial como movimiento y el caso de stock insuficiente).

### Modified Capabilities

_(ninguna: no cambian requisitos de capacidades existentes; el seed es una herramienta de puesta en marcha, no cambia contratos de la API)_

## Impact

- **Archivo principal**: `seed.py` (de stub a implementación real).
- **Tests**: nuevo `test/test_seed.py`; reutiliza la base `taller_test` migrada por Alembic del `conftest.py` raíz.
- **Datos**: escribe en las 13 tablas del esquema, incluida la tabla protegida `historial_estado_orden` (sólo `INSERT`, compatible con los disparadores de C-09).
- **Dependencias**: C-06 (usuarios/roles) y C-07 (órdenes), ya archivados. No toca migraciones ni la API.
- **Entrega (C-11)**: el orden `alembic upgrade head` → `python seed.py` → `test/solo_agregado.sql` pasa a funcionar de punta a punta, y las capturas C-14/C-15 se pueden tomar sobre datos reales.
- **Riesgo**: re-ejecutar el seed sobre una base con datos de trabajo los borra a propósito; el diagnóstico de ejecución lo advierte.
