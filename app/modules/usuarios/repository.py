"""Repositorios del módulo usuarios (capa Repository, D5).

Todos los métodos de escritura terminan en `flush()` y **nunca** en `commit()`
(la confirmación es del Unit of Work). El conteo de fallos del límite de
intentos (RN-08) hace su consulta sobre la tabla `intento_acceso` — es lo que
exige la KB ("Conteo sobre intento_acceso"); los intentos viven en sesiones
propias siempre confirmadas (DD-07), así que el conteo refleja la tabla real.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repository import BaseRepository
from app.modules.usuarios.models import AsignacionRol, IntentoAcceso, Usuario


class RepositorioUsuarios(BaseRepository[Usuario]):
    """Acceso a la tabla `usuario` (lectura por email/id, alta, parche)."""

    modelo = Usuario

    async def get_por_email(self, email: str) -> Usuario | None:
        """Busca por email; `None` si no existe (los inactivos sí se devuelven)."""
        respuesta = await self.session.execute(select(Usuario).where(Usuario.email == email))
        return respuesta.scalars().first()


class RepositorioRoles(BaseRepository[AsignacionRol]):
    """Acceso a `asignacion_rol`: alta y consulta de vigencias (RN-03/RN-04)."""

    modelo = AsignacionRol

    async def asignar(self, usuario_id: int, rol: str) -> AsignacionRol:
        """Abre una asignación de rol (sin revocar historiales previos, RN-03)."""
        return await self.add(AsignacionRol(usuario_id=usuario_id, rol=rol))

    async def existe_abierta(self, usuario_id: int, rol: str) -> bool:
        """Comprueba si ya hay una asignación abierta del rol (RN-03)."""
        resultado = await self.session.execute(
            select(AsignacionRol).where(
                AsignacionRol.usuario_id == usuario_id,
                AsignacionRol.rol == rol,
                AsignacionRol.revocada_en.is_(None),
            )
        )
        return resultado.scalars().first() is not None


class RepositorioIntentos(BaseRepository[IntentoAcceso]):
    """Acceso a `intento_acceso`: el registro del intento y su conteo (RN-08)."""

    modelo = IntentoAcceso

    async def contar_fallos_recientes(self, email: str, ip: str, ventana_segundos: int) -> int:
        """Cuenta los fallos del par (email, ip) **posteriores al último éxito** (RN-08).

        Un login correcto "reinicia la cuenta": en lugar de borrar filas (la
        tabla es de auditoría), el conteo se acota a los fallos posteriores al
        último éxito registrado para el mismo par. Un par sin éxito alguno
        cuenta desde el arranque de la ventana (60 s).

        Args:
            email: email del intento (o del fantasma, DD-06).
            ip: IP de origen del intento.
            ventana_segundos: ventana del limite (60 s de RN-08).

        Returns:
            Cantidad de fallos que van **inline** a la ventana y posteriores
            al último éxito del par (0 si no hay).
        """
        instante_limite = datetime.now(UTC).timestamp() - ventana_segundos
        subconsulta_ultimo_exito = (
            select(func.max(IntentoAcceso.cuando))
            .where(
                IntentoAcceso.email == email,
                IntentoAcceso.ip == ip,
                IntentoAcceso.exito.is_(True),
            )
            .scalar_subquery()
        )
        resultado = await self.session.execute(
            select(func.count())
            .select_from(IntentoAcceso)
            .where(
                IntentoAcceso.email == email,
                IntentoAcceso.ip == ip,
                IntentoAcceso.exito.is_(False),
                IntentoAcceso.cuando >= datetime.fromtimestamp(instante_limite, tz=UTC),
                or_(
                    subconsulta_ultimo_exito.is_(None),
                    IntentoAcceso.cuando > subconsulta_ultimo_exito,
                ),
            )
        )
        return int(resultado.scalar_one())

    async def register_intento(self, email: str, ip: str, exito: bool) -> None:
        """Inserta una fila de intento (éxito o fallo) con flush, sin commit."""
        await self.add(IntentoAcceso(email=email, ip=ip, exito=exito))


async def roles_vigentes_de(sesion: AsyncSession, usuario_id: int) -> list[str]:
    """Roles vigentes de un usuario: asignación abierta y sin vencer (RN-04).

    Args:
        sesion: sesión de la petición (solo lectura, junto al resto de consultas).
        usuario_id: identificador del usuario.

    Returns:
        Lista de roles con asignación `revocada_en IS NULL` y `vence_en` nulo
        o futuro, en el orden del catálogo (`rol` alfabético).
    """
    respuesta = await sesion.execute(
        select(AsignacionRol.rol)
        .where(
            AsignacionRol.usuario_id == usuario_id,
            AsignacionRol.revocada_en.is_(None),
            or_(AsignacionRol.vence_en.is_(None), AsignacionRol.vence_en > datetime.now(UTC)),
        )
        .order_by(AsignacionRol.rol)
    )
    return list(respuesta.scalars().all())
