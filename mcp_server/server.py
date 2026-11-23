"""OmniOps AI — MCP Server

Exposes secure, typed tools for database queries and inventory/batch
operations via the Model Context Protocol (MCP 2.x).

Agents act as MCP Clients and consume these tools to:
- Look up customers, orders and history
- Calculate predictive batch failure rates
- Identify silent customers for proactive alerting
- Block defective batches in the ERP
- Mark proactive alerts as sent
- Retrieve defect symptom samples for specialist dossiers
"""

import asyncio
import json
import logging
from typing import Optional, List

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from core.config import settings
from core.database import init_db
from mcp_server.database_tools import get_customer, get_order, get_customer_history
from mcp_server.inventory_tools import (
    calculate_batch_failure_rate,
    get_silent_customers,
    block_batch_in_erp,
    mark_proactive_alerts_sent,
    get_defect_symptoms_sample,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger("mcp_server")

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
@mcp.tool()
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


@mcp.tool()
async def lookup_order(order_id: str) -> str:
    """Busca detalhes de um pedido pelo ID (ex: 'ORD-10001').

    Retorna: produto, lote vinculado, valor, status da transportadora e flag de alerta proativo.
    """
    result = await get_order(order_id=order_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
async def lookup_customer_history(customer_id: str) -> str:
    """Recupera o histórico completo de um cliente: todos os pedidos e tickets anteriores.

    Usado para avaliar padrão de comportamento, taxa de devolução e reclamações prévias.
    """
    result = await get_customer_history(customer_id=customer_id)
    return json.dumps(result, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Inventory / Batch Tools
# ---------------------------------------------------------------------------
@mcp.tool()
async def check_batch_failure_rate(batch_id: str) -> str:
    """Calcula a taxa de falha preditiva de um lote de fabricação.

    Fórmula: tickets_defeito / total_unidades_produzidas
    Retorna métricas incluindo: failure_rate, is_critical (>= 50%),
    contagem de clientes silenciosos e status de bloqueio.
    """
    result = await calculate_batch_failure_rate(batch_id=batch_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
async def find_silent_customers(batch_id: str) -> str:
    """Lista clientes que compraram de um lote mas NÃO abriram reclamação
    de defeito e NÃO receberam alerta proativo ainda.

    Usado para disparar notificações preventivas quando um lote atinge o limiar crítico.
    """
    result = await get_silent_customers(batch_id=batch_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
async def block_batch(batch_id: str) -> str:
    """Bloqueia um lote no ERP, impedindo novas vendas.

    Ação de contenção industrial executada quando a taxa de defeito >= 50%.
    Define batches.is_blocked = True.
    """
    result = await block_batch_in_erp(batch_id=batch_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
async def mark_alerts_sent(batch_id: str, order_ids: List[str]) -> str:
    """Marca pedidos específicos como tendo recebido o alerta proativo de defeito.

    Define orders.proactive_alert_sent = True para os order_ids fornecidos
    e batches.proactive_recall_triggered = True no lote.
    """
    result = await mark_proactive_alerts_sent(batch_id=batch_id, order_ids=order_ids)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
async def get_batch_defect_symptoms(batch_id: str, limit: int = 5) -> str:
    """Retorna uma amostra das mensagens de reclamação de defeito para um lote.

    Usado para compor o dossiê técnico enviado ao especialista para análise de causa raiz.
    """
    symptoms = await get_defect_symptoms_sample(batch_id=batch_id, limit=limit)
    return json.dumps({"batch_id": batch_id, "symptoms_sample": symptoms}, ensure_ascii=False)


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
