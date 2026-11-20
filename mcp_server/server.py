"""MCP server: narrow, typed tools for customer, order, and batch operations."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from core.database import AsyncSessionLocal, Batch
from core.config import settings
from mcp_server.database_tools import (
    find_silent_orders,
    get_batch_failure_metrics,
    lookup_customer,
    lookup_order,
)

mcp = FastMCP("OmniOps database", host=settings.MCP_SERVER_HOST,
              port=settings.MCP_SERVER_PORT)


@mcp.tool()
async def get_customer(customer_id: str = "", email: str = "", phone: str = "") -> dict | None:
    """Look up one customer using exactly one of customer_id, email, or phone."""
    async with AsyncSessionLocal() as session:
        return await lookup_customer(session, customer_id or None, email or None, phone or None)


@mcp.tool()
async def get_order(order_id: str) -> dict | None:
    """Look up one order by its exact order ID."""
    async with AsyncSessionLocal() as session:
        return await lookup_order(session, order_id)


@mcp.tool()
async def get_batch_metrics(batch_id: str) -> dict | None:
    """Count distinct identified defective units and unidentified reports for a batch."""
    async with AsyncSessionLocal() as session:
        return await get_batch_failure_metrics(session, batch_id)


@mcp.tool()
async def get_silent_orders(batch_id: str) -> list[dict]:
    """List eligible orders in a batch without a matching defect ticket or prior alert."""
    async with AsyncSessionLocal() as session:
        return await find_silent_orders(session, batch_id)


@mcp.tool()
async def block_batch(batch_id: str) -> dict:
    """Block sales of a known batch; returns its resulting state."""
    async with AsyncSessionLocal() as session:
        batch = await session.get(Batch, batch_id, with_for_update=True)
        if batch is None:
            return {"ok": False, "error": "batch_not_found", "batch_id": batch_id}
        batch.is_blocked = True
        await session.commit()
        return {"ok": True, "batch_id": batch_id, "is_blocked": True}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
