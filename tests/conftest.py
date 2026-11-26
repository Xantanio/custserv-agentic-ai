"""Fixtures compartilhadas.

`db_session` usa um banco **separado** (`<POSTGRES_DB>_test`), nunca o de
desenvolvimento. O esquema é recriado uma vez por execução (D3: sem migrações
ainda) e cada teste roda dentro de uma transação externa desfeita ao final:
os `commit()` do código testado viram SAVEPOINTs, então nada persiste.
Se o Postgres não estiver acessível, os testes marcados com `integration` são pulados.
"""

import asyncio
import socket

import pytest
import uvicorn
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.config import settings
from core.database import Base

_schema_ready = False
# Indisponibilidade descoberta UMA vez por execução: os demais testes pulam na hora,
# em vez de cada um esperar o tempo limite de conexão (CLAUDE.md 9, item 9).
_db_unavailable: str | None = None
_CONNECT_TIMEOUT = {"timeout": 3}


def _test_db_url():
    url = make_url(settings.get_database_url())
    return url.set(database=f"{url.database}_test")


async def _ensure_test_database(url) -> None:
    """Cria o banco de teste se ainda não existir (CREATE DATABASE exige AUTOCOMMIT)."""
    admin = create_async_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args=_CONNECT_TIMEOUT
    )
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await admin.dispose()


@pytest.fixture
async def db_session():
    global _schema_ready, _db_unavailable
    if _db_unavailable:
        pytest.skip(_db_unavailable)
    url = _test_db_url()
    try:
        await _ensure_test_database(url)
    except (OSError, ConnectionError, TimeoutError) as exc:
        _db_unavailable = f"Postgres indisponível para testes de integração: {exc!r}"
        pytest.skip(_db_unavailable)

    engine = create_async_engine(url)
    try:
        if not _schema_ready:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
            _schema_ready = True

        async with engine.connect() as conn:
            outer = await conn.begin()
            session = AsyncSession(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            try:
                yield session
            finally:
                await session.close()
                await outer.rollback()
    finally:
        await engine.dispose()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def mcp_base_url():
    """Servidor MCP HTTP efêmero (o mesmo app do serviço real), encerrado ao fim do teste."""
    from mcp_server.server import mcp

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(mcp.streamable_http_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task
