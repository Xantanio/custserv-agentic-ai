"""Inventory & batch health tools exposed via MCP.

Handles predictive batch failure rate calculation, ERP lot blocking,
silent customer identification and proactive alert queue management.
"""

import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, Batch, Order, Ticket, Customer

logger = logging.getLogger("mcp.inventory_tools")


async def calculate_batch_failure_rate(
    batch_id: str,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Calculate the defective ticket ratio for a given manufacturing batch.

    Formula: failure_rate = defective_tickets_count / total_units_produced
    Critical threshold: >= 0.50 (50%)
    """

    async def _query(s: AsyncSession) -> Dict[str, Any]:
        # 1. Fetch batch metadata
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return {"found": False, "error": f"Batch {batch_id} not found"}

        # 2. Count defective tickets linked to orders of this batch
        stmt = (
            select(func.count(Ticket.ticket_id))
            .join(Order, Ticket.order_id == Order.order_id)
            .where(Order.batch_id == batch_id)
            .where(Ticket.intent == "defective_item")
        )
        result = await s.execute(stmt)
        defective_count = result.scalar() or 0

        # 3. Calculate failure rate
        failure_rate = defective_count / batch.total_units_produced if batch.total_units_produced > 0 else 0.0
        is_critical = failure_rate >= 0.50

        # 4. Count silent customers (bought from this batch, no defect ticket, no alert sent yet)
        silent_count = await _count_silent_customers(s, batch_id)

        return {
            "found": True,
            "batch_id": batch.batch_id,
            "product_id": batch.product_id,
            "product_name": batch.product_name,
            "factory_code": batch.factory_code,
            "manufacturing_date": batch.manufacturing_date.isoformat(),
            "total_units_produced": batch.total_units_produced,
            "defective_tickets_count": defective_count,
            "failure_rate": round(failure_rate, 4),
            "is_critical": is_critical,
            "is_blocked": batch.is_blocked,
            "proactive_recall_triggered": batch.proactive_recall_triggered,
            "silent_customers_count": silent_count,
        }

    if session:
        return await _query(session)
    async with AsyncSessionLocal() as s:
        return await _query(s)


async def _count_silent_customers(s: AsyncSession, batch_id: str) -> int:
    """Count customers who purchased from the batch but have NOT filed a defect ticket
    and have NOT received a proactive alert yet.
    """
    # Subquery: customer_ids who already have a defective ticket for this batch
    complaining_subq = (
        select(Order.customer_id)
        .join(Ticket, Ticket.order_id == Order.order_id)
        .where(Order.batch_id == batch_id)
        .where(Ticket.intent == "defective_item")
        .distinct()
        .subquery()
    )

    stmt = (
        select(func.count(Order.order_id.distinct()))
        .where(Order.batch_id == batch_id)
        .where(Order.proactive_alert_sent == False)  # noqa: E712
        .where(Order.customer_id.notin_(select(complaining_subq.c.customer_id)))
    )
    result = await s.execute(stmt)
    return result.scalar() or 0


async def get_silent_customers(
    batch_id: str,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Return the list of customers who bought from a batch but have NOT filed
    a defect complaint and have NOT been proactively alerted yet.

    Used by the Predictive Batch Agent to dispatch proactive alerts.
    """

    async def _query(s: AsyncSession) -> Dict[str, Any]:
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return {"found": False, "error": f"Batch {batch_id} not found"}

        # Subquery: customers who already complained about defect in this batch
        complaining_subq = (
            select(Order.customer_id)
            .join(Ticket, Ticket.order_id == Order.order_id)
            .where(Order.batch_id == batch_id)
            .where(Ticket.intent == "defective_item")
            .distinct()
            .subquery()
        )

        # Orders from this batch where customer hasn't complained and alert not sent
        stmt = (
            select(Order, Customer)
            .join(Customer, Order.customer_id == Customer.customer_id)
            .where(Order.batch_id == batch_id)
            .where(Order.proactive_alert_sent == False)  # noqa: E712
            .where(Order.customer_id.notin_(select(complaining_subq.c.customer_id)))
        )
        result = await s.execute(stmt)
        rows = result.all()

        silent_customers = []
        for order, customer in rows:
            silent_customers.append({
                "customer_id": str(customer.customer_id),
                "customer_name": customer.name,
                "customer_email": customer.email,
                "customer_phone": customer.phone,
                "customer_tier": customer.tier.value if hasattr(customer.tier, "value") else str(customer.tier),
                "order_id": order.order_id,
                "order_value": float(order.order_value),
                "product_id": order.product_id,
            })

        return {
            "found": True,
            "batch_id": batch_id,
            "product_name": batch.product_name,
            "silent_customers_count": len(silent_customers),
            "silent_customers": silent_customers,
        }

    if session:
        return await _query(session)
    async with AsyncSessionLocal() as s:
        return await _query(s)


async def block_batch_in_erp(
    batch_id: str,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Block a manufacturing batch in the ERP, preventing new sales.

    Sets batches.is_blocked = True.
    """

    async def _query(s: AsyncSession) -> Dict[str, Any]:
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return {"success": False, "error": f"Batch {batch_id} not found"}

        if batch.is_blocked:
            return {
                "success": True,
                "already_blocked": True,
                "batch_id": batch_id,
                "message": f"Batch {batch_id} was already blocked.",
            }

        batch.is_blocked = True
        await s.commit()
        logger.warning("BATCH BLOCKED in ERP: %s (product: %s)", batch_id, batch.product_name)

        return {
            "success": True,
            "already_blocked": False,
            "batch_id": batch_id,
            "product_name": batch.product_name,
            "message": f"Batch {batch_id} has been blocked. No new sales allowed.",
        }

    if session:
        return await _query(session)
    async with AsyncSessionLocal() as s:
        return await _query(s)


async def mark_proactive_alerts_sent(
    batch_id: str,
    order_ids: List[str],
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Mark specific orders as having received the proactive defect alert.

    Sets orders.proactive_alert_sent = True for the given order_ids
    and batches.proactive_recall_triggered = True on the batch.
    """

    async def _query(s: AsyncSession) -> Dict[str, Any]:
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return {"success": False, "error": f"Batch {batch_id} not found"}

        # Mark orders
        if order_ids:
            stmt = (
                update(Order)
                .where(Order.order_id.in_(order_ids))
                .where(Order.batch_id == batch_id)
                .values(proactive_alert_sent=True)
            )
            result = await s.execute(stmt)
            updated_count = result.rowcount
        else:
            updated_count = 0

        # Mark batch recall triggered
        if not batch.proactive_recall_triggered:
            batch.proactive_recall_triggered = True

        await s.commit()
        logger.info(
            "Proactive alerts marked for batch %s: %d orders updated.",
            batch_id,
            updated_count,
        )

        return {
            "success": True,
            "batch_id": batch_id,
            "orders_updated": updated_count,
            "proactive_recall_triggered": True,
        }

    if session:
        return await _query(session)
    async with AsyncSessionLocal() as s:
        return await _query(s)


async def get_defect_symptoms_sample(
    batch_id: str,
    limit: int = 5,
    session: Optional[AsyncSession] = None,
) -> List[str]:
    """Return a sample of defect complaint messages for a batch,
    used in the specialist dossier for root-cause analysis.
    """

    async def _query(s: AsyncSession) -> List[str]:
        stmt = (
            select(Ticket.message_text)
            .join(Order, Ticket.order_id == Order.order_id)
            .where(Order.batch_id == batch_id)
            .where(Ticket.intent == "defective_item")
            .order_by(Ticket.created_at.desc())
            .limit(limit)
        )
        result = await s.execute(stmt)
        return [row[0] for row in result.all()]

    if session:
        return await _query(session)
    async with AsyncSessionLocal() as s:
        return await _query(s)
