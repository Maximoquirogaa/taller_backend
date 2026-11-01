# Evidencias C-14 y C-15 — Instrucciones para capturar

> **Formato de entrega elegido (P-02, resuelta 2026-10-27)**: las evidencias de C-14 y C-15 son **capturas** (imagen o fragmento de consola) que tomás vos manualmente siguiendo estos pasos. Guardalas en `docs/evidencias/` y referencialas desde el README de entrega.

**Driver (P-01, resuelta)**: `asyncpg` — `postgresql+asyncpg://`. Todas las instrucciones de abajo asumen ese driver.

---

## Requisitos previos (una sola vez)

```powershell
# 1. Entorno
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. .env (copiar de env.example y completar; SIN valores por defecto en el código)
#    POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB / POSTGRES_HOST / POSTGRES_PORT
#    SECRET_KEY (generar: python -c "import secrets; print(secrets.token_urlsafe(32))")
#    SQL_ECHO=true          ← necesario para ver las consultas en consola (C-15)

# 3. Base + esquema + datos
createdb taller            # o el nombre que uses en POSTGRES_DB
alembic upgrade head
python seed.py

# 4. Servidor (terminal 1 — dejala abierta, ahí salen las consultas de C-15)
uvicorn main:app --reload --port 8000
```

> ⚠️ Antes de **cada** archivo `.http` de `test/`: `python seed.py` (la consigna lo exige).

---

## C-15 — Detalle de orden sin N+1 (mismo número de consultas con 2 y con 4 ítems)

**Qué se demuestra**: el detalle de una orden resuelve vehículo, cliente, ítems, repuestos e historial con un **número fijo de consultas**, sin crecer con la cantidad de ítems.

**Pasos**:

1. Verificá que el servidor corre con `SQL_ECHO=true` — cada SELECT debe verse en la terminal.
2. Desde VS Code (extensión REST Client) o tu herramienta favorita, en `test/`:
   - Logueate (`POST /auth/login` con `recepcion@example.com` o `admin@example.com`).
   - Creá **una orden con 2 ítems** y **otra con 4 ítems** (`POST /ordenes`) o usá las de seed si ya cumplen.
3. Pedí el detalle de cada una: `GET /ordenes/{id}` (2 ítems) y `GET /ordenes/{id}` (4 ítems).
4. Volcá la consola de **cada** petición: contá los SELECT — deben ser **la misma cantidad** en ambos casos.
5. **Captura**: screenshot de la terminal (o copiá el fragmento) mostrando:
   - la petición `GET /ordenes/{id}`,
   - los SELECT emitidos con SQL_ECHO,
   - el conteo igual en los dos casos.
6. Guardá: `docs/evidencias/C-15.png` (+ opcional `C-15.txt` con el fragmento de queries).

---

## C-14 — Disparador de sólo agregado + FK del catálogo (en psql)

**Qué se demuestra**: nadie puede modificar ni borrar filas de las tres tablas de sólo agregado (UPDATE y DELETE rechazados por el disparador = 6 rechazos), y una orden con un estado fuera del catálogo la rechaza la clave foránea.

**Pasos**:

1. Conectate a la base:
   ```powershell
   psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB
   ```
2. Desde psql, corré el script que está en el repo:
   ```sql
   \i test/solo_agregado.sql
   ```
   El script ya existe (C-09) y hace los 7 casos solo, con un `\echo` por caso. **Precondición**: la base debe tener datos (`alembic upgrade head` + `python seed.py`, este último llega en C-10); con las tablas vacías el disparador de fila no se activa.
   También se puede correr de una sin entrar a psql:
   ```powershell
   psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB -f test/solo_agregado.sql
   ```
3. **Resultado esperado** en la misma ventana (exactamente 7 `ERROR:`):
   - 6× error del disparador: `La tabla <tabla> es de sólo agregado: UPDATE|DELETE no está permitido (RN-15)`,
   - 1× error de clave foránea: `inserción o actualización en la tabla «orden_trabajo» viola la llave foránea «orden_trabajo_estado_fkey»`.
4. **Captura**: screenshot de la ventana de psql con los 7 rechazos visibles (podés sacarle `\echo on` o simplemente dejar que la salida se vea completa).
5. Salí de psql (`\q`) y guardá: `docs/evidencias/C-14.png`.

---

## Checklist de entrega de evidencias

- [ ] `docs/evidencias/C-14.png` — 6 rechazos del disparador + 1 FK en psql
- [ ] `docs/evidencias/C-15.png` — detalle con 2 y 4 ítems, misma cantidad de consultas
- [ ] README de entrega: link a ambas capturas + los pasos de levantamiento (venv → deps → `.env` → `alembic upgrade head` → `python seed.py` → servidor)

> Si preferís fragmento de texto en vez de imagen, el contenido es el mismo: guardá `C-14.txt` / `C-15.txt` con la salida pegada. La consigna acepta "captura o un fragmento de la consola".
