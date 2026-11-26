"""Adaptador MCP -> ferramentas LangChain (princípio 5: MCP como fronteira de dados).

Abre uma sessão no servidor MCP (streamable HTTP), lista as ferramentas, mantém
só as PERMITIDAS e as embrulha como `StructuredTool`. O esquema JSON de cada
ferramenta (inclusive `enum`) vem do servidor e chega intacto ao modelo.

Por que próprio (D27): o `langchain-mcp-adapters` exige `mcp<2`, e o projeto
fixa `mcp>=2,<3` (D2).
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Iterable

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Tool


class MissingToolsError(RuntimeError):
    """O servidor não expõe todas as ferramentas exigidas (fail-closed)."""


def _single_leaf(group: BaseExceptionGroup) -> BaseException | None:
    """Desce por grupos de UMA exceção só; devolve a exceção real ou None se houver várias."""
    exc: BaseException = group
    while isinstance(exc, BaseExceptionGroup):
        if len(exc.exceptions) != 1:
            return None
        exc = exc.exceptions[0]
    return exc


def _result_text(result: Any) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content if getattr(c, "text", None))


def _wrap(session: ClientSession, tool: Tool) -> BaseTool:
    async def _call(**kwargs: Any) -> str:
        result = await session.call_tool(tool.name, kwargs)
        text = _result_text(result)
        if result.is_error:
            # ToolException: o agente devolve a mensagem ao modelo para ele se corrigir
            raise ToolException(text or f"Erro ao executar {tool.name}")
        return text

    return StructuredTool(
        name=tool.name,
        description=tool.description or "",
        args_schema=tool.input_schema,
        coroutine=_call,
    )


@asynccontextmanager
async def open_mcp_tools(base_url: str, allowed: Iterable[str]) -> AsyncIterator[list[BaseTool]]:
    """Sessão MCP com as ferramentas `allowed`, na ordem pedida. Fecha ao sair do bloco.

    `base_url` é a raiz do servidor (ex.: http://localhost:8001); o endpoint é `/mcp`.
    """
    allowed = list(allowed)
    try:
        async with streamable_http_client(f"{base_url.rstrip('/')}/mcp") as (read, write, *_):
            async with ClientSession(read, write) as session:
                await session.initialize()
                available = {t.name: t for t in (await session.list_tools()).tools}
                missing = [name for name in allowed if name not in available]
                if missing:
                    raise MissingToolsError(f"Servidor MCP sem as ferramentas: {', '.join(missing)}")
                yield [_wrap(session, available[name]) for name in allowed]
    except BaseExceptionGroup as group:
        # O cliente MCP roda num TaskGroup do anyio, que embrulha QUALQUER exceção do
        # bloco (inclusive as de quem usa as ferramentas) em ExceptionGroup aninhados.
        # Devolvemos a exceção real quando ela é única.
        leaf = _single_leaf(group)
        if leaf is None:
            raise
        raise leaf from None
