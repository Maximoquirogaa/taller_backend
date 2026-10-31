"""Repositorios del módulo repuestos (capa Repository, D5).

Define:
- `RepositorioRepuestos`: hereda de `SoftDeleteRepository[Repuesto]`, gestiona catálogo,
  búsqueda por código activo (RN-01), búsqueda con parámetros ligados (US-017, RN-18)
  y borrado lógico (`borrado_en`).
- `RepositorioMovimientosStock`: hereda de `BaseRepository[MovimientoStock]`, consulta
  movimientos por repuesto ordenados cronológicamente (US-022, RN-14).
- `RepositorioHistorialPrecios`: hereda de `BaseRepository[HistorialPrecioRepuesto]`, consulta
  variaciones de precio históricas ordenadas cronológicamente (US-022, RN-20).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, or_, select

from app.core.repository import BaseRepository, SoftDeleteRepository
from app.modules.repuestos.models import (
    HistorialPrecioRepuesto,
    MovimientoStock,
    Repuesto,
)

# Normalización de acentos para la búsqueda por texto: la comparación se hace
# sobre la columna traducida en SQL y sobre el patrón normalizado en Python, con
# la misma tabla. `translate` evita depender de la extensión `unaccent`.
_ACENTOS = "áàäâãéèëêíìïîóòöôõúùüûñç"
_SIN_ACENTOS = "aaaaaeeeeiiiiooooouuuunc"
_TABLA_ACENTOS = str.maketrans(
    _ACENTOS + _ACENTOS.upper(), _SIN_ACENTOS + _SIN_ACENTOS.upper()
)


class RepositorioRepuestos(SoftDeleteRepository[Repuesto]):
    """Acceso a la tabla `repuesto`: catálogo, unicidad de código activo y búsqueda segura."""

    modelo = Repuesto
    campo_baja = "borrado_en"

    async def get_por_codigo_activo(self, codigo: str) -> Repuesto | None:
        """Busca un repuesto por su código entre los activos (no borrados, RN-01)."""
        codigo_normalizado = codigo.strip().upper()
        consulta = select(Repuesto).where(
            Repuesto.codigo == codigo_normalizado,
            Repuesto.borrado_en.is_(None),
        )
        resultado = await self.session.execute(consulta)
        return resultado.scalars().first()

    async def buscar_catalogo(
        self,
        q: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[Sequence[Repuesto], int]:
        """Busca repuestos activos con soporte de filtro de texto y parámetros ligados (RN-18).

        Retorna una tupla `(items, total)` para construir el envoltorio paginado.
        """
        filtros = [Repuesto.borrado_en.is_(None)]
        if q and q.strip():
            patron = f"%{q.strip().translate(_TABLA_ACENTOS).lower()}%"
            filtros.append(
                or_(
                    func.lower(Repuesto.codigo).like(patron),
                    func.lower(
                        func.translate(
                            Repuesto.descripcion,
                            _ACENTOS + _ACENTOS.upper(),
                            _SIN_ACENTOS + _SIN_ACENTOS.upper(),
                        )
                    ).like(patron),
                )
            )

        consulta_items = (
            select(Repuesto)
            .where(*filtros)
            .order_by(Repuesto.id.asc())
            .offset(offset)
        )
        if limit is not None:
            consulta_items = consulta_items.limit(limit)

        consulta_total = (
            select(func.count())
            .select_from(Repuesto)
            .where(*filtros)
        )

        items_res = await self.session.execute(consulta_items)
        items = items_res.scalars().all()

        total_res = await self.session.execute(consulta_total)
        total = int(total_res.scalar_one())

        return items, total


class RepositorioMovimientosStock(BaseRepository[MovimientoStock]):
    """Acceso a la tabla `movimiento_stock`: registro y auditoría de inventario (RN-14)."""

    modelo = MovimientoStock

    async def get_por_repuesto(self, repuesto_id: int) -> Sequence[MovimientoStock]:
        """Obtiene todos los movimientos asociados a un repuesto ordenados cronológicamente."""
        consulta = (
            select(MovimientoStock)
            .where(MovimientoStock.repuesto_id == repuesto_id)
            .order_by(MovimientoStock.cuando.asc(), MovimientoStock.id.asc())
        )
        resultado = await self.session.execute(consulta)
        return resultado.scalars().all()


class RepositorioHistorialPrecios(BaseRepository[HistorialPrecioRepuesto]):
    """Acceso a la tabla `historial_precio_repuesto`: auditoría de precios (RN-20)."""

    modelo = HistorialPrecioRepuesto

    async def get_por_repuesto(self, repuesto_id: int) -> Sequence[HistorialPrecioRepuesto]:
        """Obtiene el historial de variaciones de precio ordenado cronológicamente."""
        consulta = (
            select(HistorialPrecioRepuesto)
            .where(HistorialPrecioRepuesto.repuesto_id == repuesto_id)
            .order_by(HistorialPrecioRepuesto.cuando.asc(), HistorialPrecioRepuesto.id.asc())
        )
        resultado = await self.session.execute(consulta)
        return resultado.scalars().all()
