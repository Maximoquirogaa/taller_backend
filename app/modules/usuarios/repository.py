"""Repositorios del módulo usuarios (capa Repository, D5).

Todos los métodos de escritura terminan en `flush()` y **nunca** en `commit()`
(la confirmación es del Unit of Work). El conteo de fallos del límite de
intentos (RN-08) hace su consulta sobre la tabla `intento_acceso` — es lo que
exige la KB ("Conteo sobre intento_acceso"); los intentos viven en sesiones
propias siempre confirmadas (DD-07), así que el conteo refleja la tabla real.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repository import BaseRepository
from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, IntentoAcceso, Usuario


class RepositorioUsuarios(BaseRepository[Usuario]):
    """Acceso a la tabla `usuario` (lectura por email/id, alta, parche)."""

    modelo = Usuario

    async def get_por_email(self, email: str) -> Usuario | None:
        """Busca por email; `None` si no existe (los inactivos sí se devuelven)."""
        respuesta = await self.session.execute(select(Usuario).where(Usuario.email == email))
        return respuesta.scalars().first()


class RepositorioRoles(BaseRepository[AsignacionRol]):
    """Acceso a `asignacion_rol`: alta, vigencias e historial (RN-03/RN-04)."""

    modelo = AsignacionRol

    async def asignar(
        self,
        usuario_id: int,
        rol: str,
        vence_en: datetime | None = None,
        otorgada_por: int | None = None,
    ) -> AsignacionRol:
        """Abre una asignación de rol (sin tocar historiales previos, RN-03).

        Args:
            usuario_id: usuario que recibe el rol.
            rol: rol del catálogo (`ADMIN/RECEPCION/MECANICO/CLIENTE`).
            vence_en: vencimiento opcional, ya normalizado a UTC y futuro (US-009).
            otorgada_por: id del ADMIN que otorga (US-009).

        Returns:
            La fila recién abierta (con `id` tras el `flush`).
        """
        return await self.add(
            AsignacionRol(
                usuario_id=usuario_id,
                rol=rol,
                vence_en=vence_en,
                otorgada_por=otorgada_por,
            )
        )

    async def existe_abierta(self, usuario_id: int, rol: str) -> bool:
        """Comprueba si ya hay una asignación abierta del rol (RN-03)."""
        return await self.get_abierta(usuario_id, rol) is not None

    async def get_abierta(self, usuario_id: int, rol: str) -> AsignacionRol | None:
        """Devuelve la asignación **abierta** del rol (`revocada_en IS NULL`, RN-03).

        Es exactamente lo que indexa `uq_asignacion_rol_abierta`: una fila abierta
        vencida sigue bloqueando el `INSERT` aunque ya no otorgue permisos.

        Args:
            usuario_id: usuario consultado.
            rol: rol del catálogo.

        Returns:
            La fila abierta o `None` si el rol fue revocado o nunca se asignó.
        """
        resultado = await self.session.execute(
            select(AsignacionRol).where(
                AsignacionRol.usuario_id == usuario_id,
                AsignacionRol.rol == rol,
                AsignacionRol.revocada_en.is_(None),
            )
        )
        return resultado.scalars().first()

    async def revocar(
        self, asignacion: AsignacionRol, cuando: datetime | None = None
    ) -> AsignacionRol:
        """Cierra la asignación escribiendo `revocada_en`: la fila **nunca** se borra (RN-04).

        Args:
            asignacion: fila abierta a cerrar.
            cuando: instante del cierre; por defecto el actual en UTC.

        Returns:
            La misma fila, ya marcada y sincronizada (`flush`, sin `commit`).
        """
        return await self.update(asignacion, {"revocada_en": cuando or datetime.now(UTC)})

    async def get_historial(self, usuario_id: int) -> Sequence[AsignacionRol]:
        """Historial completo del usuario, incluidas las filas revocadas (RN-04/RN-05).

        Args:
            usuario_id: usuario consultado.

        Returns:
            Todas sus asignaciones ordenadas por `desde` (del pasado al presente).
        """
        resultado = await self.session.execute(
            select(AsignacionRol)
            .where(AsignacionRol.usuario_id == usuario_id)
            .order_by(AsignacionRol.desde, AsignacionRol.id)
        )
        return resultado.scalars().all()


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


class RepositorioEventos(BaseRepository[EventoSeguridad]):
    """Acceso a `evento_seguridad`: registro y consulta paginada (US-011).

    El evento se escribe en la **misma transacción** del cambio de dominio
    (design.md, decisión 2): `registrar` solo hace `flush` y el UoW confirma.
    """

    modelo = EventoSeguridad

    async def registrar(self, actor: str, accion: str) -> EventoSeguridad:
        """Agrega un evento de seguridad con `flush`, sin confirmar.

        Args:
            actor: email del usuario que actuó, o `SISTEMA` (sin FK, DD-07).
            accion: operación y entidad afectada (US-011).

        Returns:
            El evento insertado (con `id` y `cuando` tras el `flush`).
        """
        return await self.add(EventoSeguridad(actor=actor, accion=accion))

    async def buscar_paginado(
        self, offset: int, limit: int | None = None
    ) -> tuple[Sequence[EventoSeguridad], int]:
        """Devuelve una página de eventos del más reciente al más antiguo (US-011).

        Args:
            offset: filas a saltear (ya validado por `ParametrosPagina`).
            limit: tamaño de la página (`None` = sin tope).

        Returns:
            Tupla `(items, total)` para armar el envoltorio con `construir_pagina`.
        """
        consulta = (
            select(EventoSeguridad)
            .order_by(EventoSeguridad.cuando.desc(), EventoSeguridad.id.desc())
            .offset(offset)
        )
        if limit is not None:
            consulta = consulta.limit(limit)
        items = (await self.session.execute(consulta)).scalars().all()

        consulta_total = select(func.count()).select_from(EventoSeguridad)
        total = int((await self.session.execute(consulta_total)).scalar_one())
        return items, total


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
