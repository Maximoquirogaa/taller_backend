# service-lifespan Specification

## Purpose

Garantiza que los recursos caros (motor asincrónico y fábrica de sesiones) se creen y destruyan con el ciclo de vida del servidor, y que cada petición reciba su propia sesión sin efectos post-commit inesperados.

## Requirements

### Requirement: Recursos creados en el lifespan, no al importar
El motor y la fábrica de sesiones SHALL crearse durante el arranque (lifespan) y vivir en el estado de la aplicación; importar módulos de la aplicación SHALL crearlos únicamente si el bucle de eventos ya existe.

#### Scenario: Imports seguros sin bucle de eventos
- **WHEN** se importan módulos de la aplicación en un proceso sin bucle de eventos (p. ej. al recolectar tests)
- **THEN** no se construye ningún motor ni sesión y no se produce ningún error por bucle inexistente

### Requirement: Sesión por petición sin expiración post-commit
`get_session` SHALL entregar una sesión por petición con `expire_on_commit=False` y cerrarla al terminar la petición.

#### Scenario: Atributos legibles tras commit
- **WHEN** una operación confirma cambios y la transacción termina
- **THEN** los atributos de los objetos seguidos siguen legibles sin una consulta adicional de refresco

### Requirement: Cierre ordenado al apagar
Al apagar la aplicación, el lifespan SHALL cerrar el motor con `dispose()`, liberando el pool de conexiones.

#### Scenario: Shutdown limpio
- **WHEN** el servidor recibe la señal de apagado
- **THEN** el motor se dispone y las conexiones del pool se cierran sin errores
