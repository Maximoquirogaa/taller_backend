# data-persistence Specification

## Purpose

Define la semántica transaccional del núcleo: una operación de negocio se confirma o se revierte completa, y ningún nivel intermedio confirma por su cuenta.

## Requirements

### Requirement: Los repositorios solo sincronizan, nunca confirman
Los repositorios SHALL enviar los cambios a la base con operaciones de sincronización (`flush`) sin cerrar la transacción; la confirmación queda reservada al Unit of Work.

#### Scenario: Un repositorio no confirma por su cuenta
- **WHEN** un repositorio agrega o actualiza una entidad dentro de una transacción abierta
- **THEN** los cambios quedan pendientes de confirmación y ninguna llamada a `commit` proviene del repositorio

### Requirement: El Unit of Work confirma al completarse sin excepción
Al salir de su bloque con normalidad, el Unit of Work SHALL confirmar la transacción; si el bloque se interrumpe con una excepción, SHALL revertirla y propagar la excepción.

#### Scenario: Escrituras múltiples confirmadas juntas
- **WHEN** el bloque del Unit of Work escribe varias filas y termina sin excepción
- **THEN** todas las escrituras quedan confirmadas en la base

#### Scenario: Excepción revierte todo
- **WHEN** una excepción se produce dentro del bloque del Unit of Work después de varias escrituras
- **THEN** ninguna de esas escrituras queda en la base y la excepción sigue propagándose

### Requirement: El Unit of Work no cierra la sesión
El Unit of Work SHALL administrar únicamente la transacción, manteniendo la sesión usable por quien la abrió.

#### Scenario: Sesión seguible después del commit
- **WHEN** el Unit of Work termina con éxito
- **THEN** la sesión permanece abierta y los objetos ya confirmados siguen legibles sin refresco

### Requirement: Escrituras múltiples en un solo Unit of Work
Cualquier operación que escriba en más de una tabla SHALL ejecutarse dentro de un único Unit of Work para que quede confirmada completa o no quede en absoluto.

#### Scenario: Operación multi-tabla atómica
- **WHEN** una operación escribe en dos tablas distintas y la segunda escritura falla
- **THEN** la primera escritura también queda revertida
