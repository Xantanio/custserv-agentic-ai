"""Trilha de auditoria por interface (princípio 6).

Quem produz eventos (agentes, workflows) depende só de `AuditSink`; onde eles
são gravados é decidido na raiz de composição: em memória nos testes, na tabela
`audit_events` em execução real. O agente investigador não recebe nenhuma
ferramenta de escrita, nem para auditoria.
"""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import AuditEvent
from core.schemas import AuditEventCreate


class AuditSink(Protocol):
    async def record(self, event: AuditEventCreate) -> None: ...


class InMemoryAuditSink:
    """Guarda os eventos numa lista (testes e execuções de demonstração)."""

    def __init__(self) -> None:
        self.events: list[AuditEventCreate] = []

    async def record(self, event: AuditEventCreate) -> None:
        self.events.append(event)


class SqlAuditSink:
    """Grava cada evento em `audit_events`, uma transação curta por evento."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, event: AuditEventCreate) -> None:
        async with self._session_factory() as session:
            session.add(AuditEvent(**event.model_dump()))
            await session.commit()
