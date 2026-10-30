"""repuestos_stock (migración DE DESARROLLO 004 — C-11 la consolida)

Revision ID: 004_repuestos_stock
Revises: 2a785d268e95
Create Date: 2026-10-30 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '004_repuestos_stock'
down_revision: Union[str, Sequence[str], None] = '2a785d268e95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'repuesto',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('codigo', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('descripcion', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column('precio', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('stock', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('borrado_en', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('precio > 0', name='ck_repuesto_precio_positivo'),
        sa.CheckConstraint('stock >= 0', name='ck_repuesto_stock_no_negativo'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_repuesto_codigo'), 'repuesto', ['codigo'], unique=False)
    op.create_index(
        'ix_repuesto_codigo_activo',
        'repuesto',
        ['codigo'],
        unique=True,
        postgresql_where=sa.text('borrado_en IS NULL')
    )

    op.create_table(
        'movimiento_stock',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repuesto_id', sa.Integer(), nullable=False),
        sa.Column('orden_id', sa.Integer(), nullable=True),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('cantidad', sa.Integer(), nullable=False),
        sa.Column('motivo', sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column('cuando', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('cantidad > 0', name='ck_movimiento_stock_cantidad_positiva'),
        sa.ForeignKeyConstraint(['repuesto_id'], ['repuesto.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_movimiento_stock_repuesto_id'), 'movimiento_stock', ['repuesto_id'], unique=False)
    op.create_index(op.f('ix_movimiento_stock_orden_id'), 'movimiento_stock', ['orden_id'], unique=False)
    op.create_index(op.f('ix_movimiento_stock_usuario_id'), 'movimiento_stock', ['usuario_id'], unique=False)

    op.create_table(
        'historial_precio_repuesto',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repuesto_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('precio_anterior', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('precio_nuevo', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('cuando', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('precio_anterior > 0', name='ck_historial_precio_anterior_positivo'),
        sa.CheckConstraint('precio_nuevo > 0', name='ck_historial_precio_nuevo_positivo'),
        sa.CheckConstraint('precio_nuevo > precio_anterior', name='ck_historial_precio_aumento'),
        sa.ForeignKeyConstraint(['repuesto_id'], ['repuesto.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_historial_precio_repuesto_repuesto_id'), 'historial_precio_repuesto', ['repuesto_id'], unique=False)
    op.create_index(op.f('ix_historial_precio_repuesto_usuario_id'), 'historial_precio_repuesto', ['usuario_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_historial_precio_repuesto_usuario_id'), table_name='historial_precio_repuesto')
    op.drop_index(op.f('ix_historial_precio_repuesto_repuesto_id'), table_name='historial_precio_repuesto')
    op.drop_table('historial_precio_repuesto')

    op.drop_index(op.f('ix_movimiento_stock_usuario_id'), table_name='movimiento_stock')
    op.drop_index(op.f('ix_movimiento_stock_orden_id'), table_name='movimiento_stock')
    op.drop_index(op.f('ix_movimiento_stock_repuesto_id'), table_name='movimiento_stock')
    op.drop_table('movimiento_stock')

    op.drop_index('ix_repuesto_codigo_activo', table_name='repuesto', postgresql_where=sa.text('borrado_en IS NULL'))
    op.drop_index(op.f('ix_repuesto_codigo'), table_name='repuesto')
    op.drop_table('repuesto')
