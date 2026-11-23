"""Fixtures compartilhadas.

`db_session` usa um banco **separado** (`<POSTGRES_DB>_test`), nunca o de
desenvolvimento. O esquema é recriado uma vez por execução (D3: sem migrações
ainda) e cada teste roda dentro de uma transação externa desfeita ao final:
os `commit()` do código testado viram SAVEPOINTs, então nada persiste.
Se o Postgres não estiver acessível, os testes marcados com `integration` são pulados.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.config import settings
from core.database import Base

_schema_ready = False


def _test_db_url():
    url = make_url(settings.get_database_url())
    return url.set(database=f"{url.database}_test")


async def _ensure_test_database(url) -> None:
    """Cria o banco de teste se ainda não existir (CREATE DATABASE exige AUTOCOMMIT)."""
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
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
    global _schema_ready
    url = _test_db_url()
    try:
        await _ensure_test_database(url)
    except (OSError, ConnectionError) as exc:
        pytest.skip(f"Postgres indisponível para testes de integração: {exc}")

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
