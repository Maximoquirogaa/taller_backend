"""Paginación: envoltorio estándar y reglas de borde (spec `pagination`, D8).

Dos capas: la función pura (cálculo y rechazo de página inexistente) y el
contrato HTTP que FastAPI deriva del schema de parámetros (422 propio).
"""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.paginacion import ParametrosPagina, calcular_paginas, construir_pagina
from app.core.repository import BaseRepository
from app.modules.usuarios.models import Usuario


@pytest.mark.parametrize(
    ("total", "size", "esperado"),
    [
        (0, 20, 1),
        (1, 20, 1),
        (20, 20, 1),
        (21, 20, 2),
        (45, 20, 3),
        (100, 100, 1),
        (101, 100, 2),
    ],
)
def test_calcular_paginas(total: int, size: int, esperado: int) -> None:
    """`pages = ceil(total / size)`, con al menos 1 página aun sin resultados."""
    assert calcular_paginas(total, size) == esperado


def test_parametros_por_defecto() -> None:
    """Sin informar nada: página 1 y 20 elementos, con desplazamiento 0."""
    parametros = ParametrosPagina()

    assert parametros.page == 1
    assert parametros.size == 20
    assert parametros.desplazamiento == 0


def test_desplazamiento_de_paginas_siguientes() -> None:
    """El desplazamiento sale de la página pedida: (page - 1) * size."""
    assert ParametrosPagina(page=2, size=20).desplazamiento == 20
    assert ParametrosPagina(page=3, size=10).desplazamiento == 20


@pytest.mark.parametrize(
    "valores",
    [
        {"page": 0},
        {"page": -3},
        {"size": 0},
        {"size": -1},
        {"size": 500},
    ],
)
def test_parametros_fuera_de_rango_rechazados(valores: dict[str, int]) -> None:
    """`page` ge=1 y `size` entre 1 y 100, con mensaje propio en español."""
    with pytest.raises(ValidationError) as error:
        ParametrosPagina(**valores)

    mensaje = str(error.value)
    assert "La página debe ser 1 o mayor" in mensaje or "El tamaño de página" in mensaje


@pytest.mark.parametrize("valor", ["abc", "", "1.5"])
def test_parametros_no_numericos_rechazados(valor: str) -> None:
    """Un valor no numérico es un error de validación, no un 500."""
    with pytest.raises(ValidationError, match="número entero"):
        ParametrosPagina(page=valor)  # type: ignore[arg-type]


def test_size_maximo_es_valido() -> None:
    """`size=100` es el máximo aceptado (y sigue siendo válido)."""
    assert ParametrosPagina(size=100).size == 100


def test_construir_pagina_arma_el_envoltorio() -> None:
    """El envoltorio trae `items`, `total`, `page`, `size` y `pages` (45 elementos)."""
    parametros = ParametrosPagina(page=2, size=20)

    pagina = construir_pagina(["a", "b"], total=45, parametros=parametros)

    assert pagina.items == ["a", "b"]
    assert pagina.total == 45
    assert pagina.page == 2
    assert pagina.size == 20
    assert pagina.pages == 3


def test_coleccion_vacia_devuelve_pagina_uno() -> None:
    """Sin resultados: página 1 vacía, `pages`=1 y **sin** error (200)."""
    pagina = construir_pagina([], total=0, parametros=ParametrosPagina())

    assert pagina.items == []
    assert pagina.total == 0
    assert pagina.page == 1
    assert pagina.pages == 1


def test_pagina_mas_alla_de_la_ultima_es_422_con_mensaje_propio() -> None:
    """Pedir una página que no existe es un 422 de negocio con el total de páginas."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        construir_pagina([], total=0, parametros=ParametrosPagina(page=2))

    assert error.value.status_code == 422
    assert error.value.detail == "La página 2 no existe: hay 1"


def test_pagina_fuera_de_rango_con_datos() -> None:
    """Mismo rechazo cuando hay datos: con 45 elementos solo hay 3 páginas."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        construir_pagina([], total=45, parametros=ParametrosPagina(page=4, size=20))

    assert error.value.status_code == 422
    assert "La página 4 no existe: hay 3" in str(error.value.detail)


# ─────────────────────────────────────────────────────────────────────────────
# Contrato HTTP: FastAPI deriva el 422 del schema (sin tocar la base)
# ─────────────────────────────────────────────────────────────────────────────

app_de_prueba = FastAPI()


@app_de_prueba.get("/elementos")
async def listar_elementos(
    parametros: Annotated[ParametrosPagina, Query()],
) -> dict[str, object]:
    """Endpoint mínimo de prueba: usa el schema y arma el envoltorio."""
    pagina = construir_pagina([], total=0, parametros=parametros)
    return pagina.model_dump()


cliente = TestClient(app_de_prueba)


def test_http_page_cero_es_422() -> None:
    """`page=0` responde 422 con el mensaje propio del schema."""
    respuesta = cliente.get("/elementos", params={"page": 0})

    assert respuesta.status_code == 422
    assert "La página debe ser 1 o mayor" in respuesta.text


def test_http_size_excesivo_es_422() -> None:
    """`size=500` responde 422 con el mensaje propio del schema."""
    respuesta = cliente.get("/elementos", params={"size": 500})

    assert respuesta.status_code == 422
    assert "no puede superar 100" in respuesta.text


def test_http_parametro_no_numerico_es_422() -> None:
    """`page=abc` responde 422, nunca 500."""
    respuesta = cliente.get("/elementos", params={"page": "abc"})

    assert respuesta.status_code == 422
    assert "número entero" in respuesta.text


def test_http_sin_parametros_usa_los_defaults() -> None:
    """Sin `page`/`size`: 200 con página 1 y 20 elementos."""
    respuesta = cliente.get("/elementos")

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "size": 20,
        "pages": 1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# `total` con los mismos filtros que la página (contra la base real)
# ─────────────────────────────────────────────────────────────────────────────


async def test_total_respeta_los_filtros_de_la_pagina(sesion: AsyncSession) -> None:
    """`total` cuenta solo lo que cumple el filtro, no toda la tabla."""
    repositorio = BaseRepository(sesion, Usuario)
    for indice in range(3):
        await repositorio.add(
            Usuario(
                email=f"freno{indice}@taller.test",
                nombre="Cliente",
                password_hash="$2b$12$hashDeMentiraParaLosTests",
            )
        )
    await repositorio.add(
        Usuario(
            email="bujia@taller.test",
            nombre="Cliente",
            password_hash="$2b$12$hashDeMentiraParaLosTests",
        )
    )

    filtro = Usuario.email.like("%freno%")
    parametros = ParametrosPagina(page=1, size=2)
    total = await repositorio.count(filtro)
    items = await repositorio.get_all(
        filtro, offset=parametros.desplazamiento, limit=parametros.size
    )

    pagina = construir_pagina(list(items), total=total, parametros=parametros)

    assert pagina.total == 3
    assert pagina.pages == 2
    assert len(pagina.items) == 2
