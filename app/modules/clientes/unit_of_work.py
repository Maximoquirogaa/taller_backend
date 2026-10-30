"""UoW del módulo clientes: una operación de negocio = una transacción (D4).

Compone el Unit of Work base y expone los repositorios `clientes` y `vehiculos`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.unit_of_work import UnitOfWork
from app.modules.clientes.repository import RepositorioClientes, RepositorioVehiculos


class UoWClientes(UnitOfWork):
    """Transacción para clientes y vehículos con sus repositorios asociados."""

    clientes: RepositorioClientes
    vehiculos: RepositorioVehiculos

    def __init__(self, session: AsyncSession) -> None:
        """Inicializa UoW con la sesión y vincula los repositorios."""
        super().__init__(session)
        self.clientes = RepositorioClientes(session)
        self.vehiculos = RepositorioVehiculos(session)
