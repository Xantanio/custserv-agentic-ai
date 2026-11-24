"""Testes do transporte do MCP Server (D1: streamable HTTP, não stdio).

Sobe a aplicação HTTP do servidor em uma porta livre e conecta um cliente MCP
real. Não precisa de Postgres: listar ferramentas não toca no banco.
"""

import asyncio
import socket

import httpx
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mcp_server.server import mcp

EXPECTED_TOOLS = {
    "lookup_customer",
    "lookup_order",
    "lookup_customer_history",
    "check_batch_failure_rate",
    "find_silent_customers",
    "block_batch",
    "queue_alerts",
    "get_batch_defect_symptoms",
    "defect_rate_by",
    "compare_factory_batches",
    "complaint_timeline",
    "search_symptoms",
    "sample_defect_complaints",
}
WRITE_TOOLS = {"block_batch", "queue_alerts"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def mcp_base_url():
    """Servidor MCP HTTP efêmero, encerrado ao fim do teste."""
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


async def test_health_endpoint(mcp_base_url):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{mcp_base_url}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_client_lists_tools_over_streamable_http(mcp_base_url):
    async with streamable_http_client(f"{mcp_base_url}/mcp") as (read, write, *_):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
    assert {tool.name for tool in result.tools} == EXPECTED_TOOLS


async def test_tool_annotations_seen_by_client(mcp_base_url):
    """O cliente enxerga, pelo protocolo, quais ferramentas escrevem.

    Toda ferramenta do investigador é somente leitura; as de escrita não se
    declaram como leitura. (Anotação é dica, não proteção: ver INVESTIGATOR_TOOLS.)
    """
    from mcp_server.investigation_tools import INVESTIGATOR_TOOLS

    async with streamable_http_client(f"{mcp_base_url}/mcp") as (read, write, *_):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}

    assert all(t.annotations is not None for t in tools.values()), "Toda ferramenta declara seu efeito"
    assert set(INVESTIGATOR_TOOLS) <= set(tools)
    for name in INVESTIGATOR_TOOLS:
        assert tools[name].annotations.read_only_hint is True, name
    for name in WRITE_TOOLS:
        assert tools[name].annotations.read_only_hint is False, name
    assert tools["block_batch"].annotations.destructive_hint is True


async def test_dimension_is_an_enum_in_the_tool_schema(mcp_base_url):
    """O LLM recebe as opções válidas no próprio esquema JSON da ferramenta."""
    async with streamable_http_client(f"{mcp_base_url}/mcp") as (read, write, *_):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}

    schema = tools["defect_rate_by"].input_schema["properties"]["dimension"]
    assert set(schema["enum"]) == {"production_line", "manufacturing_day", "carrier", "purchase_week"}
