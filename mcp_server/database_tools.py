"""Database operational tools exposed via MCP."""

import uuid
from typing import Optional, Dict, Any, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, Customer, Order, ProactiveAlertEvent, Ticket


async def get_customer(
    customer_id: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Retrieve customer profile, loyalty tier, lifetime value and return rate."""
    async def _query(s: AsyncSession) -> Dict[str, Any]:
        stmt = select(Customer)
        if customer_id:
            try:
                c_uuid = uuid.UUID(customer_id)
                stmt = stmt.where(Customer.customer_id == c_uuid)
            except ValueError:
                return {"found": False, "error": f"Invalid UUID: {customer_id}"}
        elif email:
            stmt = stmt.where(Customer.email == email.strip().lower())
        elif phone:
            stmt = stmt.where(Customer.phone == phone.strip())
        else:
            return {"found": False, "error": "Must provide customer_id, email, or phone"}

        result = await s.execute(stmt)
        customer = result.scalars().first()
        if not customer:
            return {"found": False, "error": "Customer not found"}

        return {
            "found": True,
            "customer_id": str(customer.customer_id),
            "name": customer.name,
            "email": customer.email,
            "phone": customer.phone,
            "tier": customer.tier.value if hasattr(customer.tier, "value") else str(customer.tier),
            "lifetime_value": float(customer.lifetime_value),
            "total_orders": customer.total_orders,
            "return_rate": float(customer.return_rate),
        }

    if session:
        return await _query(session)
    async with AsyncSessionLocal() as s:
        return await _query(s)


async def get_order(
    order_id: str,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Retrieve order details including batch ID, product ID, carrier status, and alert flag."""
    async def _query(s: AsyncSession) -> Dict[str, Any]:
        stmt = select(Order).where(Order.order_id == order_id.strip())
        result = await s.execute(stmt)
        order = result.scalars().first()
        if not order:
            return {"found": False, "error": f"Order {order_id} not found"}

        alert = (
            await s.execute(
                select(ProactiveAlertEvent.status).where(ProactiveAlertEvent.order_id == order.order_id)
            )
        ).scalar_one_or_none()

        return {
            "found": True,
            "order_id": order.order_id,
            "customer_id": str(order.customer_id),
            "product_id": order.product_id,
            "batch_id": order.batch_id,
            "order_value": float(order.order_value),
            "carrier_status": order.carrier_status.value if hasattr(order.carrier_status, "value") else str(order.carrier_status),
            "carrier": order.carrier,
            "proactive_alert_status": alert.value if alert else None,
            "purchase_date": order.purchase_date.isoformat(),
        }

    if session:
        return await _query(session)
    async with AsyncSessionLocal() as s:
        return await _query(s)


async def get_customer_history(
    customer_id: str,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Retrieve full customer history: orders and prior support tickets."""
    async def _query(s: AsyncSession) -> Dict[str, Any]:
        try:
            c_uuid = uuid.UUID(customer_id)
        except ValueError:
            return {"found": False, "error": f"Invalid UUID: {customer_id}"}

        # Query orders
        stmt_orders = select(Order).where(Order.customer_id == c_uuid).order_by(Order.purchase_date.desc())
        res_orders = await s.execute(stmt_orders)
        orders = res_orders.scalars().all()

        # Query tickets
        stmt_tickets = select(Ticket).where(Ticket.customer_id == c_uuid).order_by(Ticket.created_at.desc())
        res_tickets = await s.execute(stmt_tickets)
        tickets = res_tickets.scalars().all()

        return {
            "found": True,
            "customer_id": customer_id,
            "orders": [
                {
                    "order_id": o.order_id,
                    "product_id": o.product_id,
                    "batch_id": o.batch_id,
                    "order_value": float(o.order_value),
                    "carrier_status": o.carrier_status.value if hasattr(o.carrier_status, "value") else str(o.carrier_status),
                    "purchase_date": o.purchase_date.isoformat(),
                }
                for o in orders
            ],
            "tickets": [
                {
                    "ticket_id": str(t.ticket_id),
                    "thread_id": t.thread_id,
                    "order_id": t.order_id,
                    "serial_number": t.serial_number,
                    "intent": t.intent,
                    "sentiment_score": float(t.sentiment_score),
                    "sentiment_label": t.sentiment_label.value if hasattr(t.sentiment_label, "value") else str(t.sentiment_label),
                    "is_health_risk": t.is_health_risk,
                    "batch_flagged": t.batch_flagged,
                    "priority_score": t.priority_score,
                    "autonomy_status": t.autonomy_status.value if hasattr(t.autonomy_status, "value") else str(t.autonomy_status),
                    "created_at": t.created_at.isoformat(),
                }
                for t in tickets
            ],
        }

    if session:
        return await _query(session)
    async with AsyncSessionLocal() as s:
        return await _query(s)
