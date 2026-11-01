"""disparador_solo_agregado (migración DE DESARROLLO 006 — ESCRITA A MANO)

Instala en la base la garantía de sólo agregado (RN-15, US-031): una función
de disparador y tres disparadores `BEFORE UPDATE OR DELETE` que rechazan
cualquier intento de modificar o borrar filas de `historial_estado_orden`,
`movimiento_stock` e `historial_precio_repuesto`.

ESTA MIGRACIÓN ES ESCRITA A MANO Y NO SE AUTOGENERA. Alembic no detecta
funciones ni disparadores, así que el autogenerate nunca la produciría ni la
borraría. **Sobrevive a la consolidación de C-11**: allí se renumera a
`002_disparador_solo_agregado.py` y se le ajustan `revision` y `down_revision`;
el SQL de abajo se conserva tal cual (DD-08).

Por eso todo el SQL es literal y no depende de identificadores autogenerados:
sólo `op.execute` con `CREATE OR REPLACE FUNCTION`, `DROP TRIGGER IF EXISTS`
y `CREATE TRIGGER`. Cada sentencia va en su propio `op.execute` porque el
driver `asyncpg` no acepta varias sentencias en una misma ejecución.

El `downgrade` revierte el esquema al estado anterior (sin función ni
disparadores). `TRUNCATE` no se ve afectado: los disparadores son de fila y
`TRUNCATE` no los activa (la limpieza de la suite depende de eso).

Revision ID: 002_disparador_solo_agregado
Revises: 001_esquema_inicial
Create Date: 2026-10-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '002_disparador_solo_agregado'
down_revision: Union[str, Sequence[str], None] = '001_esquema_inicial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SQL_FUNCION = """
CREATE OR REPLACE FUNCTION fn_bloquear_modificacion_historial()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'La tabla % es de sólo agregado: % no está permitido (RN-15)',
        TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'P0001';
END;
$$;
"""

# (tabla, nombre del disparador) — pares constantes, sin identificadores autogenerados.
TABLAS_PROTEGIDAS = (
    ("historial_estado_orden", "trg_solo_agregado_historial_estado_orden"),
    ("movimiento_stock", "trg_solo_agregado_movimiento_stock"),
    ("historial_precio_repuesto", "trg_solo_agregado_historial_precio_repuesto"),
)


def _crear_disparador(tabla: str, disparador: str) -> None:
    """Crea (reemplazando si existe) el disparador de sólo agregado de una tabla."""
    op.execute(f"DROP TRIGGER IF EXISTS {disparador} ON {tabla}")
    op.execute(
        f"CREATE TRIGGER {disparador} "
        f"BEFORE UPDATE OR DELETE ON {tabla} "
        "FOR EACH ROW "
        "EXECUTE FUNCTION fn_bloquear_modificacion_historial()"
    )


def upgrade() -> None:
    """Instala la función de disparador y los tres disparadores de sólo agregado."""
    op.execute(SQL_FUNCION)
    for tabla, disparador in TABLAS_PROTEGIDAS:
        _crear_disparador(tabla, disparador)


def downgrade() -> None:
    """Quita los tres disparadores y la función, dejando el esquema como estaba."""
    for tabla, disparador in TABLAS_PROTEGIDAS:
        op.execute(f"DROP TRIGGER IF EXISTS {disparador} ON {tabla}")
    op.execute("DROP FUNCTION IF EXISTS fn_bloquear_modificacion_historial()")
