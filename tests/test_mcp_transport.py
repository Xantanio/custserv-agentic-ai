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
}


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
