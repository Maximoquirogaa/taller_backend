"""Paginación de listados: parámetros validados y envoltorio estándar (D8).

Contrato público de **todos** los listados:

- `page` (entero, ge=1, por defecto 1) y `size` (entero, 1..100, por defecto 20),
  con mensajes propios en español; FastAPI los convierte en un 422 automático.
- Envoltorio `{items, total, page, size, pages}` con `pages = ceil(total / size)`.
- Borde (consigna §2.9 / C-16): sin resultados → página 1 vacía con **200**;
  pedir una página más allá de la última → **422** con mensaje propio
  («La página N no existe: hay M»).

Ninguna consulta se arma concatenando datos del usuario (RN-18): el
desplazamiento sale de un entero ya validado.
"""

from typing import Generic, TypeVar

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


class ParametrosPagina(BaseModel):
    """Parámetros de paginación de un listado (`page`/`size`).

    Los validadores corren en modo `before` para que el mensaje que ve el cliente
    sea el propio (en español) y no el genérico de Pydantic.
    """

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, description="Número de página; empieza en 1.")
    size: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Elementos por página (1 a 100, por defecto 20).",
    )

    @field_validator("page", "size", mode="before")
    @classmethod
    def _validar_entero(cls, valor: object, info: object) -> object:
        """Convierte y valida con mensaje propio: entero, y dentro del rango."""
        campo = getattr(info, "field_name", "")
        nombre = "La página" if campo == "page" else "El tamaño de página"
        if isinstance(valor, bool) or not isinstance(valor, (int, str)):
            raise ValueError(f"{nombre} debe ser un número entero.")
        try:
            numero = int(valor)
        except (TypeError, ValueError):
            raise ValueError(f"{nombre} debe ser un número entero.") from None
        if numero < 1:
            raise ValueError(f"{nombre} debe ser 1 o mayor.")
        if campo == "size" and numero > 100:
            raise ValueError(f"{nombre} no puede superar 100.")
        return numero

    @property
    def desplazamiento(self) -> int:
        """Filas a saltear para llegar a la página pedida."""
        return (self.page - 1) * self.size


class PaginaDe(BaseModel, Generic[T]):
    """Envoltorio estándar de listados: la página, el total y el marco de paginación."""

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    total: int
    page: int
    size: int
    pages: int


def calcular_paginas(total: int, size: int) -> int:
    """Cantidad de páginas: `ceil(total / size)`, nunca menos de 1 (colección vacía)."""
    return max(1, -(-total // size))


def validar_pagina(page: int, pages: int) -> None:
    """Rechaza con 422 una página que no existe, en lugar de devolver una vacía."""
    if page > pages:
        raise HTTPException(
            status_code=422,
            detail=f"La página {page} no existe: hay {pages}",
        )


def construir_pagina(
    items: list[T],
    *,
    total: int,
    parametros: ParametrosPagina,
) -> PaginaDe[T]:
    """Arma el envoltorio y valida el borde de página inexistente.

    `total` debe venir contado con **los mismos filtros** que `items` (spec
    `pagination`): así `pages` y el rechazo de `page` son coherentes.
    """
    pages = calcular_paginas(total, parametros.size)
    validar_pagina(parametros.page, pages)
    return PaginaDe[T](
        items=items,
        total=total,
        page=parametros.page,
        size=parametros.size,
        pages=pages,
    )
