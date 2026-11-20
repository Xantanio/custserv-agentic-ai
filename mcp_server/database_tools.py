"""Safe, parameterized database operations exposed to the MCP server."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import Batch, Customer, Order, Ticket


async def lookup_customer(session: AsyncSession, customer_id: str | None = None,
                          email: str | None = None, phone: str | None = None) -> dict | None:
    """Find a customer by one exact identifier; never returns an unrestricted list."""
    filters = []
    if customer_id:
        try:
            parsed_id = uuid.UUID(customer_id)
        except ValueError as exc:
            raise ValueError("customer_id deve ser um UUID válido.") from exc
        filters.append(Customer.customer_id == parsed_id)
    if email:
        filters.append(Customer.email == email)
    if phone:
        filters.append(Customer.phone == phone)
    if len(filters) != 1:
        raise ValueError("Informe exatamente um entre customer_id, email ou phone.")
    customer = await session.scalar(select(Customer).where(filters[0]))
    if customer is None:
        return None
    return {
        "customer_id": str(customer.customer_id), "name": customer.name,
        "email": customer.email, "phone": customer.phone,
        "tier": customer.tier.value, "lifetime_value": str(customer.lifetime_value),
        "total_orders": customer.total_orders, "return_rate": customer.return_rate,
    }


async def lookup_order(session: AsyncSession, order_id: str) -> dict | None:
    order = await session.scalar(select(Order).where(Order.order_id == order_id))
    if order is None:
        return None
    return {"order_id": order.order_id, "customer_id": str(order.customer_id),
            "product_id": order.product_id, "batch_id": order.batch_id,
            "order_value": str(order.order_value), "carrier_status": order.carrier_status.value,
            "purchase_date": order.purchase_date.isoformat()}


async def get_batch_failure_metrics(session: AsyncSession, batch_id: str) -> dict | None:
    batch = await session.get(Batch, batch_id)
    if batch is None:
        return None
    defective = Ticket.intent == "defective_item"
    batch_tickets = select(Ticket).join(Order, Ticket.order_id == Order.order_id).where(
        Order.batch_id == batch_id, Order.product_id == batch.product_id, defective
    ).subquery()
    identified = await session.scalar(
        select(func.count(func.distinct(Ticket.unit_identifier))).select_from(Ticket)
        .join(Order, Ticket.order_id == Order.order_id)
        .where(Order.batch_id == batch_id, Order.product_id == batch.product_id,
               defective, Ticket.unit_identifier.is_not(None))
    )
    unidentified = await session.scalar(
        select(func.count()).select_from(batch_tickets)
        .where(batch_tickets.c.unit_identifier.is_(None))
    )
    identified = int(identified or 0)
    unidentified = int(unidentified or 0)
    rate = identified / batch.total_units_produced
    return {"batch_id": batch.batch_id, "product_id": batch.product_id,
            "product_name": batch.product_name, "factory_code": batch.factory_code,
            "manufacturing_date": batch.manufacturing_date.isoformat(),
            "total_units_produced": batch.total_units_produced,
            "identified_affected_units": identified,
            "unidentified_defect_reports": unidentified, "failure_rate": rate,
            "is_critical": rate >= 0.5, "is_blocked": batch.is_blocked}


async def find_silent_orders(session: AsyncSession, batch_id: str) -> list[dict]:
    """Return orders without a matching defect report or confirmed delivered alert."""
    has_defect = select(Ticket.ticket_id).where(
        Ticket.order_id == Order.order_id, Ticket.intent == "defective_item"
    ).exists()
    rows = (await session.execute(
        select(Order, Customer).join(Customer, Customer.customer_id == Order.customer_id)
        .where(Order.batch_id == batch_id, ~has_defect, Order.proactive_alert_sent.is_(False))
        .order_by(Order.purchase_date)
    )).all()
    return [{"order_id": order.order_id, "customer_id": str(customer.customer_id),
             "customer_name": customer.name, "email": customer.email,
             "phone": customer.phone, "product_id": order.product_id,
             "batch_id": order.batch_id} for order, customer in rows]
