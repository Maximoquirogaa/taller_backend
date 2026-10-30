# Spec Delta

## Purpose

Fija en la base las reglas de integridad de las tablas de acceso (usuarios, roles con vigencia, intentos y eventos) para que la unicidad la garantice PostgreSQL y no la aplicación.

## ADDED Requirements

### Requirement: Email de usuario único
La base SHALL rechazar un segundo usuario con el mismo `email`, sin importar su estado.

#### Scenario: Email duplicado rechazado por la base
- **WHEN** se inserta un usuario con un `email` ya existente
- **THEN** la base rechaza la escritura con un error de integridad

### Requirement: Rol restringido al catálogo de la consigna
La columna de rol de la asignación SHALL aceptar únicamente `ADMIN`, `RECEPCION`, `MECANICO` o `CLIENTE`; cualquier otro valor será rechazado por la base.

#### Scenario: Rol fuera de catálogo rechazado
- **WHEN** se inserta una asignación con un rol distinto de los cuatro permitidos
- **THEN** la base rechaza la escritura con un error de restricción

### Requirement: A lo sumo una asignación abierta por rol
La base SHALL garantizar que un usuario tenga como máximo una asignación **no revocada** por cada rol, permitiendo re-asignar un rol que fue revocado.

#### Scenario: Segunda asignación abierta del mismo rol rechazada
- **WHEN** un usuario ya tiene una asignación de `MECANICO` sin `revocada_en` y se inserta otra igual
- **THEN** la base rechaza la escritura con un error de integridad

#### Scenario: Rol revocado permite re-asignar
- **WHEN** la asignación existente tiene `revocada_en` con valor y se inserta una nueva asignación del mismo rol
- **THEN** la base acepta la escritura y ambas filas permanecen en la tabla

### Requirement: Revocación conserva la fila
Revocar un rol SHALL escribir la marca de revocación sobre la fila existente, sin eliminarla, de modo que el historial de quién tuvo qué rol se conserve.

#### Scenario: Revocar no borra
- **WHEN** se revoca una asignación vigente
- **THEN** la fila sigue existiendo con `revocada_en` y `desde` conservados

### Requirement: Intentos de acceso consultables por email, IP y fecha
La tabla de intentos de acceso SHALL registrar cada intento con su instante, email, IP y resultado, e incluir un índice que sustente la consulta de los últimos intentos fallidos de una misma combinación email+IP.

#### Scenario: Intento registrado con sus datos
- **WHEN** se produce un intento de login fallido
- **THEN** queda una fila con instante, email, IP y resultado, localizable por el índice de (email, IP, instante)

### Requirement: Esquema creado solo por migraciones
El esquema de estas tablas SHALL provenir exclusivamente de la ejecución de migraciones; la aplicación no SHALL crear tablas al arrancar ni durante las pruebas.

#### Scenario: Arrancar contra una base ya migrada
- **WHEN** la aplicación arranca sobre una base ya migrada
- **THEN** no se crea ni modifica ningún objeto de esquema

#### Scenario: Base sin migrar no tiene las tablas
- **WHEN** se consulta una base recién creada sin ejecutar migraciones
- **THEN** las tablas de acceso no existen
