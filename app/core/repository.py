"""Repositorios genéricos: `BaseRepository[T]` y `SoftDeleteRepository[T]` (D5).

Contrato (regla dura del proyecto):

- Todo método de escritura termina en `flush()`: los FK se resuelven y los
  `IntegrityError` aparecen **dentro** de la transacción del UoW, que decide
  confirmar o revertir.
- Ningún método llama a `commit()`: la confirmación es del Unit of Work.
- Las relaciones que una lectura necesita se precargan acá, en el método que las
  usa (nada de carga perezosa dentro del bucle de eventos).
- Los nombres son los de la consigna: `get_by_id`, `get_all`, `count`, `add`,
  `update`, `delete`; el soft delete agrega `get_by_id_including_deleted` y
  `soft_delete`.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

T = TypeVar("T", bound=SQLModel)


class BaseRepository(Generic[T]):
    """Acceso a una tabla: lectura, alta, modificación y baja física.

    El modelo se pasa al constructor (`BaseRepository(sesion, Usuario)`) o se
    declara como atributo de clase en el repositorio de cada módulo
    (`modelo = Usuario`), que es como lo usan los módulos de dominio.
    """

    modelo: type[T]

    def __init__(self, session: AsyncSession, modelo: type[T] | None = None) -> None:
        self.session = session
        modelo_efectivo = modelo if modelo is not None else getattr(type(self), "modelo", None)
        if modelo_efectivo is None:
            raise ValueError(
                "El repositorio necesita un modelo: pasalo al constructor o "
                "declará `modelo` en la subclase."
            )
        self.modelo = modelo_efectivo

    async def get_by_id(self, id_: int) -> T | None:
        """Busca por PK; `None` si no existe."""
        return await self.session.get(self.modelo, id_)

    async def get_all(
        self,
        *filtros: ColumnElement[bool],
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[T]:
        """Lista con filtros opcionales y ventana `offset`/`limit` (paginación)."""
        consulta = select(self.modelo)
        if filtros:
            consulta = consulta.where(*filtros)
        consulta = consulta.offset(offset)
        if limit is not None:
            consulta = consulta.limit(limit)
        return (await self.session.execute(consulta)).scalars().all()

    async def count(self, *filtros: ColumnElement[bool]) -> int:
        """Cuenta con **los mismos filtros** que la página (spec `pagination`)."""
        consulta = select(func.count()).select_from(self.modelo)
        if filtros:
            consulta = consulta.where(*filtros)
        return int((await self.session.execute(consulta)).scalar_one())

    async def add(self, entidad: T) -> T:
        """Agrega y sincroniza (`flush`), sin confirmar."""
        self.session.add(entidad)
        await self.session.flush()
        return entidad

    async def update(self, entidad: T, datos: Mapping[str, Any]) -> T:
        """Aplica los campos recibidos sobre la entidad y sincroniza (`flush`)."""
        for campo, valor in datos.items():
            setattr(entidad, campo, valor)
        await self.session.flush()
        return entidad

    async def delete(self, entidad: T) -> None:
        """Baja física: borra la fila y sincroniza (`flush`), sin confirmar."""
        await self.session.delete(entidad)
        await self.session.flush()


class SoftDeleteRepository(BaseRepository[T]):
    """Repositorio con baja lógica: las lecturas esconden las filas dadas de baja.

    La columna de baja es configurable (`campo_baja`) para que cada módulo use la
    suya (`borrado_en` en vehículos y repuestos; `revocada_en` en asignaciones de
    rol). La fila **nunca** se borra: se marca y se conserva el historial.
    """

    campo_baja: str = "borrado_en"

    def _vigentes(self) -> ColumnElement[bool]:
        """Condición de fila vigente: la marca de baja en NULL."""
        return getattr(self.modelo, self.campo_baja).is_(None)

    async def get_by_id(self, id_: int) -> T | None:
        """Busca por PK entre las filas vigentes; `None` si no existe o está dada de baja."""
        entidad = await self.session.get(self.modelo, id_)
        if entidad is None or getattr(entidad, self.campo_baja) is not None:
            return None
        return entidad

    async def get_all(
        self,
        *filtros: ColumnElement[bool],
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[T]:
        """Lista solo las filas vigentes, con filtros y ventana opcionales."""
        return await super().get_all(
            self._vigentes(), *filtros, offset=offset, limit=limit
        )

    async def count(self, *filtros: ColumnElement[bool]) -> int:
        """Cuenta solo las filas vigentes, con los mismos filtros que la página."""
        return await super().count(self._vigentes(), *filtros)

    async def get_by_id_including_deleted(self, id_: int) -> T | None:
        """Busca por PK incluyendo las filas dadas de baja (auditoría)."""
        return await self.session.get(self.modelo, id_)

    async def soft_delete(self, entidad: T, cuando: datetime | None = None) -> T:
        """Marca la baja con el instante indicado (o el actual en UTC) y sincroniza."""
        setattr(entidad, self.campo_baja, cuando or datetime.now(UTC))
        await self.session.flush()
        return entidad
