# service-configuration Specification

## Purpose

Define cómo se configura la aplicación: todos los valores salen del entorno, los secretos no tienen valor por defecto en el código y la aplicación no arranca si faltan, evitando claves inventadas o filtradas en el repositorio.

## Requirements

### Requirement: Secretos sin valor por defecto
`SECRET_KEY` y `POSTGRES_PASSWORD` SHALL carecer de valor por defecto en el código; si faltan en el entorno, la aplicación SHALL fallar al arrancar.

#### Scenario: Falta SECRET_KEY
- **WHEN** se inicia la aplicación sin `SECRET_KEY` en el entorno
- **THEN** el arranque falla antes de servir peticiones, sin usar una clave inventada

#### Scenario: Falta POSTGRES_PASSWORD
- **WHEN** se inicia la aplicación sin `POSTGRES_PASSWORD` en el entorno
- **THEN** el arranque falla antes de servir peticiones

### Requirement: URL de base asincrónica armada desde el entorno
La dirección de la base SHALL construirse con `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST` y `POSTGRES_PORT`, usando el esquema `postgresql+asyncpg://`.

#### Scenario: Variables completas
- **WHEN** están definidas las cinco variables `POSTGRES_*` con un driver asincrónico seleccionado
- **THEN** la URL resultante es `postgresql+asyncpg://<user>:<password>@<host>:<port>/<db>` sin exponer la contraseña en logs

### Requirement: Configuración fuera del código versionado
La configuración SHALL leerse con pydantic-settings desde variables de entorno o un archivo `.env` no versionado; el repositorio SHALL incluir `env.example` con todas las variables y ningún secreto real.

#### Scenario: Arranque con .env local
- **WHEN** existe un `.env` local completo y no hay variables en el proceso
- **THEN** la configuración se carga desde `.env` y el servidor arranca

#### Scenario: Repo limpio de secretos
- **WHEN** se inspecciona el repositorio versionado
- **THEN** solo existe `env.example` (sin valores sensibles) y no hay `.env` ni claves reales en el código
