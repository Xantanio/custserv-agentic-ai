"""Etapa 5: adaptador MCP -> ferramentas LangChain (integrations/mcp_tools.py).

Usa o servidor MCP real em processo (fixture `mcp_base_url`). Os casos aqui não
chegam ao banco: listar ferramentas e argumentos inválidos são resolvidos pelo
próprio protocolo, antes de qualquer consulta.
"""

import pytest
from langchain_core.tools import ToolException
from langchain_core.utils.function_calling import convert_to_openai_tool

from integrations.mcp_tools import MissingToolsError, open_mcp_tools
from mcp_server.investigation_tools import INVESTIGATOR_TOOLS


async def test_loads_only_the_allowed_tools_in_order(mcp_base_url):
    async with open_mcp_tools(mcp_base_url, INVESTIGATOR_TOOLS) as tools:
        assert [t.name for t in tools] == list(INVESTIGATOR_TOOLS)
        names = {t.name for t in tools}
    assert "block_batch" not in names and "find_silent_customers" not in names


async def test_tool_schema_reaches_the_model_intact(mcp_base_url):
    """O enum de `dimension`, definido no servidor, chega ao formato que o LLM recebe."""
    async with open_mcp_tools(mcp_base_url, ["defect_rate_by"]) as (tool,):
        params = convert_to_openai_tool(tool)["function"]["parameters"]
        assert "taxa de defeito" in tool.description.lower()
    assert set(params["properties"]["dimension"]["enum"]) == {
        "production_line", "manufacturing_day", "carrier", "purchase_week",
    }
    assert set(params["required"]) == {"batch_id", "dimension"}


async def test_missing_tool_fails_closed(mcp_base_url):
    with pytest.raises(MissingToolsError, match="ferramenta_inexistente"):
        async with open_mcp_tools(mcp_base_url, ["defect_rate_by", "ferramenta_inexistente"]):
            pass


async def test_server_side_error_becomes_tool_exception_with_guidance(mcp_base_url):
    """Argumento fora do enum: o servidor recusa e a mensagem lista as opções (o agente a repassa ao modelo)."""
    async with open_mcp_tools(mcp_base_url, ["defect_rate_by"]) as (tool,):
        with pytest.raises(ToolException) as exc:
            await tool.coroutine(batch_id="LOTE-2026-DEF", dimension="fabrica")
    assert "production_line" in str(exc.value)


async def test_errors_inside_the_block_are_not_wrapped_in_exception_groups(mcp_base_url):
    """Um erro de quem usa as ferramentas chega como ele mesmo, não como ExceptionGroup do anyio."""
    with pytest.raises(ZeroDivisionError):
        async with open_mcp_tools(mcp_base_url, ["defect_rate_by"]):
            1 / 0
