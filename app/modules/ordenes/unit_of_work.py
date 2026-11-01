"""UoW del módulo órdenes: una operación de negocio = una transacción (D10).

Expone `ordenes`, `items`, `historial`, `estados` (sólo lectura), `repuestos` y
`movimientos` (salidas de stock de C-08) y reutiliza `vehiculos` (clientes) para
las validaciones de referencia. Ningún repositorio llama a `commit()`: sólo
`flush`; la confirmación es del Unit of Work al salir del bloque.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.unit_of_work import UnitOfWork
from app.modules.clientes.repository import RepositorioClientes, RepositorioVehiculos
from app.modules.ordenes.repository import (
    RepositorioEstadosOrden,
    RepositorioHistorialOrden,
    RepositorioItemsOrden,
    RepositorioOrdenes,
)
from app.modules.repuestos.repository import (
    RepositorioMovimientosStock,
    RepositorioRepuestos,
)


class UoWOrdenes(UnitOfWork):
    """Transacción para órdenes, ítems, historial y catálogo de estados."""

    def __init__(self, session: AsyncSession) -> None:
        """Inicializa el UoW con la sesión y vincula los repositorios.

        Args:
            sesión: sesión async de la petición (dueña del ciclo de vida).
        """
        super().__init__(session)
        self.ordenes: RepositorioOrdenes = RepositorioOrdenes(session)
        self.items: RepositorioItemsOrden = RepositorioItemsOrden(session)
        self.historial: RepositorioHistorialOrden = RepositorioHistorialOrden(session)
        self.estados: RepositorioEstadosOrden = RepositorioEstadosOrden(session)
        self.vehiculos: RepositorioVehiculos = RepositorioVehiculos(session)
        self.repuestos: RepositorioRepuestos = RepositorioRepuestos(session)
        self.movimientos: RepositorioMovimientosStock = RepositorioMovimientosStock(
            session
        )
        self.clientes: RepositorioClientes = RepositorioClientes(session)
