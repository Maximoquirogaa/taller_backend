"""Unit of Work base: una operación de negocio = una transacción (D4).

`UnitOfWork(session)` es un *async context manager* que:

- al salir **sin** excepción → `commit()`;
- al salir **con** excepción → `rollback()` y la propaga;
- **nunca** cierra la sesión: la dueña es `get_session` (la petición).

Los UoW por módulo componen esta clase y exponen sus repositorios (C-03 en
adelante); la confirmación nunca sale de un repositorio (D5).
"""

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession


class UnitOfWork:
    """Administra la transacción de una sesión recibida, sin cerrarla."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def __aenter__(self) -> "UnitOfWork":
        """Abre el bloque transaccional devolviendo el propio UoW."""
        return self

    async def __aexit__(
        self,
        tipo_excepcion: type[BaseException] | None,
        excepcion: BaseException | None,
        traza: TracebackType | None,
    ) -> bool:
        """Confirma si no hubo excepción; si la hubo, revierte y la propaga.

        Devuelve siempre `False`: la excepción **no** se silencia, sigue subiendo
        hasta la capa que la traduce (409 en C-03/C-04, RN-18).
        """
        if tipo_excepcion is not None:
            await self.session.rollback()
            return False
        await self.session.commit()
        return False
