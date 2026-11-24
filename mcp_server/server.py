"""OmniOps AI — MCP Server

Exposes secure, typed tools for database queries and inventory/batch
operations via the Model Context Protocol (MCP 2.x).

Agents act as MCP Clients and consume these tools to:
- Look up customers, orders and history
- Calculate predictive batch failure rates
- Identify silent customers for proactive alerting
- Block defective batches in the ERP
- Queue proactive alerts (idempotent; delivery confirmed by provider)
- Retrieve defect symptom samples for specialist dossiers
"""

import asyncio
import json
import logging
from typing import Literal, Optional, List

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from core.config import settings
from core.database import init_db
from mcp_server.database_tools import get_customer, get_order, get_customer_history
from mcp_server.inventory_tools import (
    calculate_batch_failure_rate,
    get_silent_customers,
    block_batch_in_erp,
    queue_proactive_alerts,
    get_defect_symptoms_sample,
)
from mcp_server.investigation_tools import (
    compare_factory_batches as _compare_factory_batches,
    complaint_timeline as _complaint_timeline,
    defect_rate_by as _defect_rate_by,
    sample_defect_complaints as _sample_defect_complaints,
    search_symptoms as _search_symptoms,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger("mcp_server")

# Anotações MCP: DICAS ao cliente sobre o efeito de cada ferramenta. Não são
# proteção; o menor privilégio real é a lista fechada de cada agente
# (ex.: investigation_tools.INVESTIGATOR_TOOLS) mais os testes.
READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
WRITE_IDEMPOTENT = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
WRITE_DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
)


def _dump(result) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# MCP Server Instance
# ---------------------------------------------------------------------------
mcp = MCPServer(
    name="OmniOps-MCP-Tools",
    instructions=(
        "Servidor MCP do OmniOps AI. Fornece ferramentas seguras de leitura e "
        "ação operacional sobre clientes, pedidos, lotes de fabricação e alertas "
        "proativos. Todas as queries são parametrizadas e isoladas."
    ),
)


# ---------------------------------------------------------------------------
# Database Tools
# ---------------------------------------------------------------------------
@mcp.tool(annotations=READ_ONLY)
async def lookup_customer(
    customer_id: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
) -> str:
    """Busca o perfil completo de um cliente por UUID, e-mail ou telefone.

    Retorna: tier de fidelidade, lifetime value, total de pedidos e taxa de devolução.
    Forneça ao menos um dos parâmetros de busca.
    """
    result = await get_customer(customer_id=customer_id, email=email, phone=phone)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(annotations=READ_ONLY)
async def lookup_order(order_id: str) -> str:
    """Busca detalhes de um pedido pelo ID (ex: 'ORD-10001').

    Retorna: produto, lote vinculado, valor, transportadora, status de entrega e status do alerta proativo.
    """
    result = await get_order(order_id=order_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(annotations=READ_ONLY)
async def lookup_customer_history(customer_id: str) -> str:
    """Recupera o histórico completo de um cliente: todos os pedidos e tickets anteriores.

    Usado para avaliar padrão de comportamento, taxa de devolução e reclamações prévias.
    """
    result = await get_customer_history(customer_id=customer_id)
    return json.dumps(result, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Inventory / Batch Tools
# ---------------------------------------------------------------------------
@mcp.tool(annotations=READ_ONLY)
async def check_batch_failure_rate(batch_id: str) -> str:
    """Calcula a taxa de falha de um lote por unidades distintas com defeito.

    Fórmula: seriais distintos com defeito no lote / total de unidades produzidas.
    Retorna também reclamações sem serial e com serial inconsistente (fora da taxa),
    is_critical (taxa >= limiar da política) e a contagem de pedidos silenciosos.
    """
    result = await calculate_batch_failure_rate(batch_id=batch_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(annotations=READ_ONLY)
async def find_silent_customers(batch_id: str) -> str:
    """Lista os pedidos do lote sem reclamação de defeito e sem alerta entregue.

    A elegibilidade é por pedido: um cliente que reclamou de um pedido continua
    elegível pelos outros. Usado para enfileirar alertas preventivos.
    """
    result = await get_silent_customers(batch_id=batch_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(annotations=WRITE_DESTRUCTIVE)
async def block_batch(batch_id: str) -> str:
    """Bloqueia um lote no ERP, impedindo novas vendas.

    Ação de contenção industrial executada quando a taxa de defeito >= 50%.
    Define batches.is_blocked = True.
    """
    result = await block_batch_in_erp(batch_id=batch_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(annotations=WRITE_IDEMPOTENT)
async def queue_alerts(batch_id: str, order_ids: List[str]) -> str:
    """Enfileira alertas proativos (status pending) para pedidos do lote.

    Não marca como enviado: só a confirmação do provedor gera `delivered`.
    Idempotente: repetir a chamada não duplica alertas.
    """
    result = await queue_proactive_alerts(batch_id=batch_id, order_ids=order_ids)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(annotations=READ_ONLY)
async def get_batch_defect_symptoms(batch_id: str, limit: int = 5) -> str:
    """Retorna uma amostra das mensagens de reclamação de defeito para um lote.

    Usado para compor o dossiê técnico enviado ao especialista para análise de causa raiz.
    """
    symptoms = await get_defect_symptoms_sample(batch_id=batch_id, limit=limit)
    return json.dumps({"batch_id": batch_id, "symptoms_sample": symptoms}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Investigation Tools (somente leitura, agregadas, sem PII; CLAUDE.md 8.2)
# ---------------------------------------------------------------------------
@mcp.tool(annotations=READ_ONLY)
async def defect_rate_by(
    batch_id: str,
    dimension: Literal["production_line", "manufacturing_day", "carrier", "purchase_week"],
) -> str:
    """Taxa de defeito do lote por grupo de uma dimensão (linha de produção, dia de
    fabricação, transportadora ou semana de compra).

    Cada grupo traz unidades, unidades defeituosas e defect_rate (já normalizada).
    Use para achar onde os defeitos se concentram. Compare taxas, não contagens.
    """
    return _dump(await _defect_rate_by(batch_id=batch_id, dimension=dimension))


@mcp.tool(annotations=READ_ONLY)
async def compare_factory_batches(batch_id: str) -> str:
    """Compara o lote com os outros lotes da mesma fábrica: taxa de defeito geral e
    por linha de produção, em ordem de fabricação. Use para saber se o problema é novo.
    """
    return _dump(await _compare_factory_batches(batch_id=batch_id))


@mcp.tool(annotations=READ_ONLY)
async def complaint_timeline(batch_id: str) -> str:
    """Reclamações de defeito do lote por semana e quantas unidades foram reclamadas
    pela primeira vez em cada semana. Use para saber quando o problema começou.
    """
    return _dump(await _complaint_timeline(batch_id=batch_id))


@mcp.tool(annotations=READ_ONLY)
async def search_symptoms(batch_id: str, term: str) -> str:
    """Conta reclamações e unidades do lote cujo texto cita um termo (ex.: 'estufada',
    'tela', 'pulseira'), por linha de produção, com até 3 exemplos mascarados.
    """
    return _dump(await _search_symptoms(batch_id=batch_id, term=term))


@mcp.tool(annotations=READ_ONLY)
async def sample_defect_complaints(batch_id: str, limit: int = 5) -> str:
    """Amostra das reclamações de defeito mais recentes do lote (máx. 8), com data,
    canal, linha de produção e texto mascarado. Use para conhecer os sintomas.
    """
    return _dump(await _sample_defect_complaints(batch_id=batch_id, limit=limit))


# ---------------------------------------------------------------------------
# Health check (fora do protocolo MCP)
# ---------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Endpoint HTTP simples para o healthcheck do Docker.

    Fica fora do protocolo MCP de propósito: verificar se o processo está vivo
    não deveria exigir abrir uma sessão MCP completa.
    """
    return JSONResponse({"status": "ok", "service": "omniops-mcp"})


# ---------------------------------------------------------------------------
# Server Entrypoint
# ---------------------------------------------------------------------------
async def start_server():
    """Inicializa o banco e sobe o MCP Server via streamable HTTP (D1).

    Endpoint MCP: http://<host>:<porta>/mcp · Health: http://<host>:<porta>/health
    """
    logger.info("Initializing database connection...")
    await init_db()
    logger.info(
        "OmniOps MCP Server starting (streamable HTTP) on %s:%s/mcp",
        settings.MCP_SERVER_HOST,
        settings.MCP_SERVER_PORT,
    )
    await mcp.run_streamable_http_async(
        host=settings.MCP_SERVER_HOST,
        port=settings.MCP_SERVER_PORT,
    )


def main():
    asyncio.run(start_server())


if __name__ == "__main__":
    main()
