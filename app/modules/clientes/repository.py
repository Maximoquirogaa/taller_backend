"""Repositorios del módulo clientes (capa Repository, D5).

Define:
- `RepositorioClientes`: acceso a la tabla `cliente`, búsqueda por documento, por `usuario_id`,
  y consulta de detalle con precarga de vehículos activos (`selectinload`) sin incurrir en N+1 (US-016).
- `RepositorioVehiculos`: hereda de `SoftDeleteRepository[Vehiculo]`, gestionando borrado lógico
  mediante `borrado_en`, búsqueda de patente activa (RN-01) y listado por cliente.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.repository import BaseRepository, SoftDeleteRepository
from app.modules.clientes.models import Cliente, Vehiculo


class RepositorioClientes(BaseRepository[Cliente]):
    """Acceso a la tabla `cliente`: alta, búsqueda por documento/usuario y precarga."""

    modelo = Cliente

    async def get_por_documento(self, documento: str) -> Cliente | None:
        """Busca un cliente por su número de documento."""
        consulta = select(Cliente).where(Cliente.documento == documento)
        resultado = await self.session.execute(consulta)
        return resultado.scalars().first()

    async def get_por_usuario_id(self, usuario_id: int) -> Cliente | None:
        """Busca la ficha de cliente asociada a un usuario web (1:1 opcional)."""
        consulta = select(Cliente).where(Cliente.usuario_id == usuario_id)
        resultado = await self.session.execute(consulta)
        return resultado.scalars().first()

    async def get_con_vehiculos(self, cliente_id: int) -> Cliente | None:
        """Obtiene la ficha de cliente con sus vehículos vigentes precargados.

        Usa `selectinload` para garantizar exactamente 2 consultas fijas (sin N+1),
        filtrando los vehículos dados de baja lógica.
        """
        consulta = (
            select(Cliente)
            .where(Cliente.id == cliente_id)
            .options(
                selectinload(Cliente.vehiculos.and_(Vehiculo.borrado_en.is_(None)))
            )
        )
        resultado = await self.session.execute(consulta)
        return resultado.scalars().first()


class RepositorioVehiculos(SoftDeleteRepository[Vehiculo]):
    """Acceso a la tabla `vehiculo`: borrado lógico y búsqueda de patentes vigentes."""

    modelo = Vehiculo
    campo_baja = "borrado_en"

    async def get_por_patente_activa(self, patente: str) -> Vehiculo | None:
        """Busca un vehículo por patente que no haya sido borrado lógicamente (RN-01)."""
        patente_normalizada = patente.strip().upper()
        consulta = select(Vehiculo).where(
            Vehiculo.patente == patente_normalizada,
            Vehiculo.borrado_en.is_(None),
        )
        resultado = await self.session.execute(consulta)
        return resultado.scalars().first()

    async def get_por_cliente(self, cliente_id: int) -> Sequence[Vehiculo]:
        """Lista los vehículos activos pertenecientes a un cliente."""
        consulta = select(Vehiculo).where(
            Vehiculo.cliente_id == cliente_id,
            Vehiculo.borrado_en.is_(None),
        )
        resultado = await self.session.execute(consulta)
        return resultado.scalars().all()
