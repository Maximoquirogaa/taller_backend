# TP Taller Mecánico — Base de Conocimiento

Base de conocimiento generada en modo **ingest** a partir de `docs/TP_Cap1a6_Consigna.pdf` (Programación III, UNIDAD 1–6: del objeto a la transacción).

## Índice de Archivos

| Archivo | Contenido |
|---------|-----------|
| [01_vision_y_objetivos.md](01_vision_y_objetivos.md) | Propósito, actores, alcance v1.0, fuera de alcance (concurrencia/colas), métricas |
| [02_descripcion_general.md](02_descripcion_general.md) | Stack (FastAPI/SQLModel/SQLAlchemy async/PG16/Alembic), arquitectura en capas, API resumen |
| [03_actores_y_roles.md](03_actores_y_roles.md) | ADMIN/RECEPCION/MECANICO/CLIENTE, matriz RBAC, rutas públicas, cambio obligatorio |
| [04_modelo_de_datos.md](04_modelo_de_datos.md) | 13 tablas, ERD, constraints/índices parciales, catálogo, seed |
| [05_reglas_de_negocio.md](05_reglas_de_negocio.md) | RN-01…RN-20 con garante esperado |
| [06_funcionalidades.md](06_funcionalidades.md) | 31 historias de usuario en 7 épicas |
| [07_flujos_principales.md](07_flujos_principales.md) | 9 flujos extremo a extremo (login, UoW de terminar orden, etc.) |
| [08_arquitectura_propuesta.md](08_arquitectura_propuesta.md) | Patrones, estructura obligatoria, seguridad, env vars |
| [09_decisiones_y_supuestos.md](09_decisiones_y_supuestos.md) | DD-01…DD-12 y SU-01…SU-05 |
| [10_preguntas_abiertas.md](10_preguntas_abiertas.md) | Dudas priorizadas (las 2 Alta ya resueltas) |
| [11_evidencias_c14_c15.md](11_evidencias_c14_c15.md) | Instrucciones para correr y capturar C-14/C-15 |

## Quick Start para Desarrolladores

1. Dominio y actores → [01](01_vision_y_objetivos.md), [03](03_actores_y_roles.md)
2. Datos → [04](04_modelo_de_datos.md)
3. Reglas → [05](05_reglas_de_negocio.md)
4. Arquitectura y estructura → [02](02_descripcion_general.md), [08](08_arquitectura_propuesta.md)
5. Implementar → [07](07_flujos_principales.md), [06](06_funcionalidades.md)
6. Antes de codificar → [10](10_preguntas_abiertas.md)

## Resumen Ejecutivo

API FastAPI asincrónica para un taller mecánico: órdenes de trabajo con máquina de estados por catálogo, stock de repuestos con movimientos de sólo agregado (disparador), clientes/vehículos con borrado lógico e índices únicos parciales, y acceso por 4 roles con vigencia en la base (cookie HttpOnly + bcrypt + JWT). Todo se agrupa en transacciones vía Unit of Work; el esquema vive solo en Alembic (una migración a mano para el disparador). Concurrencia y colas (caps. 7–8) están fuera de alcance.
