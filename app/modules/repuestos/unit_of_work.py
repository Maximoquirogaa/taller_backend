"""UoW del módulo repuestos: una operación de negocio = una transacción (D4).

Compone el Unit of Work base y expone los repositorios `repuestos`,
`movimientos` e `historial_precios`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.unit_of_work import UnitOfWork
from app.modules.repuestos.repository import (
    RepositorioHistorialPrecios,
    RepositorioMovimientosStock,
    RepositorioRepuestos,
)


class UoWRepuestos(UnitOfWork):
    """Transacción para repuestos, movimientos e historial de precios."""

    repuestos: RepositorioRepuestos
    movimientos: RepositorioMovimientosStock
    historial_precios: RepositorioHistorialPrecios

    def __init__(self, session: AsyncSession) -> None:
        """Inicializa UoW con la sesión y vincula los repositorios correspondientes."""
        super().__init__(session)
        self.repuestos = RepositorioRepuestos(session)
        self.movimientos = RepositorioMovimientosStock(session)
        self.historial_precios = RepositorioHistorialPrecios(session)
