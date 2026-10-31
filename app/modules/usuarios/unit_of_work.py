"""UoW del módulo usuarios: una operación de negocio = una transacción (D4).

Compone el Unit of Work base (que confirma o revierte la sesión recibida) y
expone los repositorios del módulo: `usuarios`, `roles` e `intentos`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.unit_of_work import UnitOfWork
from app.modules.usuarios.repository import (
    RepositorioEventos,
    RepositorioIntentos,
    RepositorioRoles,
    RepositorioUsuarios,
)


class UoWUsuarios(UnitOfWork):
    """Transacción de las operaciones de usuarios con sus repositorios listos."""

    usuarios: RepositorioUsuarios
    roles: RepositorioRoles
    intentos: RepositorioIntentos
    eventos: RepositorioEventos

    def __init__(self, session: AsyncSession) -> None:
        """Recibe la sesión de la petición y arma los repositorios sobre ella."""
        super().__init__(session)
        self.usuarios = RepositorioUsuarios(session)
        self.roles = RepositorioRoles(session)
        self.intentos = RepositorioIntentos(session)
        self.eventos = RepositorioEventos(session)
