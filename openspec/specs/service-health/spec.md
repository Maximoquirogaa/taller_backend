# service-health Specification

## Purpose

Expone la salud del proceso de la API: un chequeo de vida que nunca toca la base y uno de disponibilidad que verifica que PostgreSQL responda, para que un orquestador pueda distinguir "proceso vivo" de "servicio listo".

## Requirements

### Requirement: Liveness sin dependencia de la base
El endpoint `GET /health/live` SHALL responder 200 sin ejecutar ninguna consulta contra la base de datos.

#### Scenario: Proceso vivo con la base caída
- **WHEN** se envía `GET /health/live` y PostgreSQL no está accesible
- **THEN** la respuesta es 200 con estado del proceso, sin intentar conexión a la base

### Requirement: Readiness con verificación de conectividad
El endpoint `GET /health/ready` SHALL ejecutar `SELECT 1` contra la base y responder 200 si la consulta responde, o 503 si la base no contesta.

#### Scenario: Base disponible
- **WHEN** se envía `GET /health/ready` y la base ejecuta `SELECT 1`
- **THEN** la respuesta es 200

#### Scenario: Base no disponible
- **WHEN** se envía `GET /health/ready` y la base no responde o rechaza la conexión
- **THEN** la respuesta es 503, distinguiendo proceso vivo de servicio listo (reiniciar el proceso no arregla una base caída)
