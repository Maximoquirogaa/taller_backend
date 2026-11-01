"""Repositorios del módulo órdenes (capa Repository, D5).

- `RepositorioEstadosOrden`: catálogo de estados de **sólo lectura**; no hereda
  de `BaseRepository` y no expone `add`, `update` ni `delete` (RN-19).
- `RepositorioOrdenes`: alta con `flush`, detalle con precargas fijas (sin
  carga perezosa ni N+1), listado paginado filtrado por estado y órdenes
  propias de un usuario.
- `RepositorioItemsOrden` / `RepositorioHistorialOrden`: alta con `flush`.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.repository import BaseRepository
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import (
    EstadoOrden,
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)
from app.modules.repuestos.models import Repuesto


class RepositorioEstadosOrden:
    """Catálogo de estados de orden: acceso de **sólo lectura** (RN-19).

    La migración 005 crea la tabla vacía (DD-01); C-10 la puebla. No se
    expone escritura para que ningún endpoint pueda modificar el catálogo.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def listar(self) -> Sequence[EstadoOrden]:
        """Devuelve todos los estados ordenados por `posicion` ascendente.

        Returns:
            Lista de `EstadoOrden` ordenada por `posicion` de menor a mayor.
        """
        consulta = select(EstadoOrden).order_by(EstadoOrden.posicion.asc())
        resultado = await self.session.execute(consulta)
        return list(resultado.scalars().all())

    async def get_por_codigo(self, codigo: str) -> EstadoOrden | None:
        """Busca un estado por su código PK.

        Args:
            codigo: código textual del estado (clave primaria).

        Returns:
            La fila de `EstadoOrden` o `None` si no existe.
        """
        resultado = await self.session.execute(
            select(EstadoOrden).where(EstadoOrden.codigo == codigo)
        )
        return resultado.scalars().first()

    async def existe_catalogo(self) -> bool:
        """Indica si el catálogo tiene al menos una fila.

        Returns:
            `True` si hay estados cargados, `False` si la tabla está vacía.
        """
        consulta = select(func.count()).select_from(EstadoOrden)
        total = int((await self.session.execute(consulta)).scalar_one())
        return total > 0


class RepositorioOrdenes(BaseRepository[OrdenTrabajo]):
    """Acceso a `orden_trabajo`: alta, detalle precargado y listados."""

    modelo = OrdenTrabajo

    async def get_detalle(self, orden_id: int) -> OrdenTrabajo | None:
        """Devuelve la orden con vehículo, cliente, estado, ítems (con repuesto)
        e historial precargados en un número fijo de consultas (sin N+1).

        Las relaciones muchos-a-uno se resuelven con `joinedload` en la misma
        sentencia y las colecciones con `selectinload` (una sentencia cada una),
        así el número de consultas no crece con la cantidad de ítems (C-15).

        Args:
            orden_id: identificador de la orden.

        Returns:
            La `OrdenTrabajo` cargada con sus relaciones o `None` si no existe.
        """
        consulta = (
            select(OrdenTrabajo)
            .where(OrdenTrabajo.id == orden_id)
            .options(
                joinedload(OrdenTrabajo.vehiculo).joinedload(Vehiculo.cliente),
                joinedload(OrdenTrabajo.estado_catalogo),
                selectinload(OrdenTrabajo.items).joinedload(ItemOrden.repuesto),
                selectinload(OrdenTrabajo.historial).joinedload(
                    HistorialEstadoOrden.desde_estado_catalogo
                ),
                selectinload(OrdenTrabajo.historial).joinedload(
                    HistorialEstadoOrden.hasta_estado_catalogo
                ),
            )
            # Refresca atributos y colecciones ya cargadas en la sesión: tras una
            # transición dentro del mismo UoW, el detalle devuelto refleja el
            # estado/Historial recién escritos (sin datos obsoletos en memoria).
            .execution_options(populate_existing=True)
        )
        resultado = await self.session.execute(consulta)
        return resultado.scalars().first()

    async def buscar_paginado(
        self, estado: str | None, offset: int, limit: int
    ) -> tuple[Sequence[OrdenTrabajo], int]:
        """Devuelve `(items, total)` filtrado por estado, ordenado
        `creada_en DESC, id DESC`, con el vehículo precargado (D6).

        Args:
            estado: código de estado para filtrar, o `None` sin filtro.
            offset: filas a saltear (validado por `ParametrosPagina`).
            limit: tamaño de la página (validado por `ParametrosPagina`).

        Returns:
            Tupla con las órdenes de la página y el total coincidente.
        """
        filtros: list = []
        if estado is not None:
            filtros.append(OrdenTrabajo.estado == estado)

        consulta_items = (
            select(OrdenTrabajo)
            .options(joinedload(OrdenTrabajo.vehiculo))
            .where(*filtros)
            .order_by(OrdenTrabajo.creada_en.desc(), OrdenTrabajo.id.desc())
            .offset(offset)
            .limit(limit)
        )
        consulta_total = select(func.count()).select_from(OrdenTrabajo).where(*filtros)

        items = list((await self.session.execute(consulta_items)).scalars().all())
        total = int((await self.session.execute(consulta_total)).scalar_one())
        return items, total

    async def buscar_por_usuario(
        self, usuario_id: int, offset: int, limit: int
    ) -> tuple[Sequence[OrdenTrabajo], int]:
        """Sólo las órdenes de vehículos de la ficha de cliente del usuario.

        Excluye los vehículos dados de baja lógica (RN-17, D9).

        Args:
            usuario_id: identificador del usuario dueño de la ficha de cliente.
            offset: filas a saltear (validado por `ParametrosPagina`).
            limit: tamaño de la página (validado por `ParametrosPagina`).

        Returns:
            Tupla con las órdenes propias de la página y el total coincidente.
        """
        consulta_items = (
            select(OrdenTrabajo)
            .options(joinedload(OrdenTrabajo.vehiculo))
            .join(Vehiculo, OrdenTrabajo.vehiculo_id == Vehiculo.id)
            .join(Cliente, Vehiculo.cliente_id == Cliente.id)
            .where(
                Vehiculo.borrado_en.is_(None),
                Cliente.usuario_id == usuario_id,
            )
            .order_by(OrdenTrabajo.creada_en.desc(), OrdenTrabajo.id.desc())
            .offset(offset)
            .limit(limit)
        )
        consulta_total = (
            select(func.count())
            .select_from(OrdenTrabajo)
            .join(Vehiculo, OrdenTrabajo.vehiculo_id == Vehiculo.id)
            .join(Cliente, Vehiculo.cliente_id == Cliente.id)
            .where(
                Vehiculo.borrado_en.is_(None),
                Cliente.usuario_id == usuario_id,
            )
        )

        items = list((await self.session.execute(consulta_items)).scalars().all())
        total = int((await self.session.execute(consulta_total)).scalar_one())
        return items, total


class RepositorioItemsOrden(BaseRepository[ItemOrden]):
    """Acceso a `item_orden`: alta de ítems con `flush`, sin `commit`."""

    modelo = ItemOrden


class RepositorioHistorialOrden(BaseRepository[HistorialEstadoOrden]):
    """Acceso a `historial_estado_orden`: alta de líneas con `flush`, sin `commit`."""

    modelo = HistorialEstadoOrden
