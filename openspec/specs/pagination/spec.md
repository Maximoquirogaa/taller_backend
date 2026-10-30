# pagination Specification

## Purpose

Unifica la respuesta de los listados en un envoltorio predecible, con paginación acotada, para que todos los endpoints de colección respondan igual y no se consulten cantidades ilimitadas de filas.

## Requirements

### Requirement: Envoltorio estándar de listados
Todo listado SHALL responder con un objeto que incluya `items` (la página), `total` (elementos totales), `page`, `size` y `pages` (cantidad de páginas).

#### Scenario: Respuesta completa
- **WHEN** se pide una página válida de una colección con 45 elementos
- **THEN** la respuesta trae `items`, `total`=45, `page`, `size` y `pages` calculado a partir de total y size

### Requirement: Página inicial en 1
Los números de página SHALL comenzar en 1; la primera página es la 1.

#### Scenario: Primera página explícita
- **WHEN** se pide `page=1`
- **THEN** la respuesta devuelve los primeros `size` elementos con `page`=1

### Requirement: Tamaño de página acotado con valor por defecto
`size` SHALL admitir valores entre 1 y 100, con 20 cuando no se informa.

#### Scenario: Tamaño por defecto
- **WHEN** la petición no informa `size`
- **THEN** la respuesta usa `size`=20

#### Scenario: Tamaño máximo aceptado
- **WHEN** se pide `size`=100
- **THEN** la petición es válida y la página contiene hasta 100 elementos

### Requirement: Valores fuera de rango rechazados con 422
Un `page` menor que 1, un `size` menor que 1 o mayor que 100, o no numéricos, SHALL responder con un error de validación 422 y un mensaje propio, sin tocar la base.

#### Scenario: Page menor que 1
- **WHEN** se pide `page`=0
- **THEN** la respuesta es 422 con un mensaje de validación propio

#### Scenario: Size mayor que 100
- **WHEN** se pide `size`=500
- **THEN** la respuesta es 422 con un mensaje de validación propio

### Requirement: Página más allá de la última rechazada con 422
Pedir una página mayor que la última existente SHALL responder 422 con un mensaje propio (por ejemplo «La página 3 no existe: hay 2»), sin devolver una lista vacía.

#### Scenario: Página fuera del rango existente
- **WHEN** se pide `page`=2 cuando la colección tiene 1 sola página
- **THEN** la respuesta es 422 con un mensaje propio que indica cuántas páginas hay

### Requirement: Colección vacía tiene una página
Con cero resultados, el listado SHALL responder 200 con `items` vacío, `total`=0, `page`=1 y `pages`=1.

#### Scenario: Sin resultados
- **WHEN** se lista una colección que no tiene elementos
- **THEN** la respuesta es 200 con `items` vacío, `total`=0 y `pages`=1 (no 422)

### Requirement: Total con los mismos filtros que la página
`total` SHALL contar los elementos que cumplen los mismos filtros que la página, no el total de la tabla.

#### Scenario: Filtro aplicado al total
- **WHEN** se pide una página con un filtro (por ejemplo `q=freno`)
- **THEN** `total` cuenta solo los elementos que cumplen ese filtro
