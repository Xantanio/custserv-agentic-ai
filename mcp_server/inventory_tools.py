"""Inventory & batch health tools exposed via MCP.

Handles predictive batch failure rate calculation, ERP lot blocking,
silent customer identification and proactive alert queue management.
"""

import logging
from typing import Optional, Dict, Any, List

from decimal import Decimal

from sqlalchemy import and_, case, exists, false, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    AlertStatus,
    AsyncSessionLocal,
    Batch,
    Customer,
    Order,
    ProactiveAlertEvent,
    Ticket,
    Unit,
)
from core.policy_config import BATCH_FAILURE_RATE_CRITICAL, RULE_BATCH_CRITICAL
from core.schemas import BatchFailureMetrics

DEFECT_INTENT = "defective_item"

# Template aprovado do alerta proativo (D11): nada de texto livre gerado por LLM.
RECALL_ALERT_TEMPLATE_ID = "recall_alert_v1"


def _no_delivered_alert():
    """Condição SQL: o pedido ainda não tem alerta com status `delivered`."""
    return ~exists().where(
        ProactiveAlertEvent.order_id == Order.order_id,
        ProactiveAlertEvent.status == AlertStatus.DELIVERED,
    )

logger = logging.getLogger("mcp.inventory_tools")


def _valid_unit_for_batch(batch_id: str):
    """Ticket com serial que conta no numerador do lote.

    A unidade pertence ao lote e, se o ticket cita um pedido, é a unidade desse
    pedido. `is_not_distinct_from` trata NULL como valor (em SQL, `x = NULL` é
    NULL, não false); o `coalesce` garante um booleano de verdade.
    """
    return func.coalesce(
        and_(
            Unit.batch_id == batch_id,
            or_(Ticket.order_id.is_(None), Ticket.order_id.is_not_distinct_from(Unit.order_id)),
        ),
        false(),
    )


async def calculate_batch_failure_rate(
    batch_id: str,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Taxa de falha do lote por UNIDADES distintas (CLAUDE.md 6.2).

    taxa = seriais distintos com defeito identificados no lote / total produzido.
    Várias reclamações da mesma unidade contam uma; reclamações sem serial e com
    serial inconsistente (de outro pedido ou lote) ficam fora do numerador e são
    devolvidas à parte.
    """

    async def _query(s: AsyncSession) -> Dict[str, Any]:
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return {"found": False, "error": f"Batch {batch_id} not found"}

        valid = _valid_unit_for_batch(batch.batch_id)
        # Tickets de defeito ligados ao lote pelo pedido OU pelo serial informado
        stmt = (
            select(
                func.count(func.distinct(case((valid, Ticket.serial_number)))),
                func.count(func.distinct(Ticket.ticket_id)),
                func.count(func.distinct(case((Ticket.serial_number.is_(None), Ticket.ticket_id)))),
                func.count(func.distinct(case(
                    (and_(Ticket.serial_number.is_not(None), ~valid), Ticket.ticket_id)
                ))),
            )
            .select_from(Ticket)
            .outerjoin(Order, Ticket.order_id == Order.order_id)
            .outerjoin(Unit, Ticket.serial_number == Unit.serial_number)
            .where(Ticket.intent == DEFECT_INTENT)
            .where(or_(Order.batch_id == batch.batch_id, Unit.batch_id == batch.batch_id))
        )
        units, tickets, unidentified, inconsistent = (await s.execute(stmt)).one()

        rate = Decimal(units) / Decimal(batch.total_units_produced)
        metrics = BatchFailureMetrics(
            batch_id=batch.batch_id,
            product_id=batch.product_id,
            product_name=batch.product_name,
            factory_code=batch.factory_code,
            manufacturing_date=batch.manufacturing_date,
            total_units_produced=batch.total_units_produced,
            defective_units_count=units,
            defective_tickets_count=tickets,
            unidentified_complaints_count=unidentified,
            inconsistent_serial_complaints_count=inconsistent,
            failure_rate=round(float(rate), 4),
            critical_threshold=float(BATCH_FAILURE_RATE_CRITICAL),
            is_critical=rate >= BATCH_FAILURE_RATE_CRITICAL,  # comparação exata, sem arredondar antes
            rule_id=RULE_BATCH_CRITICAL,
            is_blocked=batch.is_blocked,
            proactive_recall_triggered=batch.proactive_recall_triggered,
            silent_orders_count=await _count_silent_orders(s, batch.batch_id),
        )
        return metrics.model_dump(mode="json")

    if session:
        return await _query(session)
    async with AsyncSessionLocal() as s:
        return await _query(s)


def _silent_order_conditions(batch_id: str) -> list:
    """Pedido do lote elegível ao alerta proativo (elegibilidade POR PEDIDO, 6.2).

    Não há reclamação de defeito referente a ESTE pedido (pelo `order_id` do
    ticket ou pelo serial de uma unidade dele) e não há alerta `delivered`.
    Outros pedidos do mesmo cliente não interferem.
    """
    # `.correlate(Order)` é essencial: sem ele, a subconsulta aninhada traz o
    # próprio `orders` no FROM (produto cartesiano) e todo pedido parece reclamado.
    units_of_order = (
        select(Unit.serial_number).where(Unit.order_id == Order.order_id).correlate(Order)
    )
    complained = (
        exists()
        .where(
            Ticket.intent == DEFECT_INTENT,
            or_(Ticket.order_id == Order.order_id, Ticket.serial_number.in_(units_of_order)),
        )
        .correlate(Order)
    )
    return [Order.batch_id == batch_id, ~complained, _no_delivered_alert()]


async def _count_silent_orders(s: AsyncSession, batch_id: str) -> int:
    stmt = select(func.count()).select_from(Order).where(*_silent_order_conditions(batch_id))
    return (await s.execute(stmt)).scalar_one()


async def get_silent_customers(
    batch_id: str,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Lista os pedidos do lote elegíveis ao alerta proativo, com o contato do cliente.

    Usado pela contenção do lote para enfileirar alertas por template (D11).
    """

    async def _query(s: AsyncSession) -> Dict[str, Any]:
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return {"found": False, "error": f"Batch {batch_id} not found"}

        stmt = (
            select(Order, Customer)
            .join(Customer, Order.customer_id == Customer.customer_id)
            .where(*_silent_order_conditions(batch.batch_id))
            .order_by(Order.order_id)
        )
        rows = (await s.execute(stmt)).all()
        silent_orders = [
            {
                "order_id": order.order_id,
                "customer_id": str(customer.customer_id),
                "customer_name": customer.name,
                "customer_email": customer.email,
                "customer_phone": customer.phone,
                "customer_tier": customer.tier.value,
                "order_value": float(order.order_value),
                "product_id": order.product_id,
            }
            for order, customer in rows
        ]
        return {
            "found": True,
            "batch_id": batch.batch_id,
            "product_name": batch.product_name,
            "silent_orders_count": len(silent_orders),
            "silent_orders": silent_orders,
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


async def queue_proactive_alerts(
    batch_id: str,
    order_ids: List[str],
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Enfileira alertas proativos (status `pending`) para pedidos do lote.

    Não marca nada como enviado: só a confirmação do provedor muda o status
    para `delivered`. Idempotente: `ON CONFLICT DO NOTHING` sobre a restrição
    `uq_alert_per_order`, então repetir a chamada não duplica alertas.
    """

    async def _query(s: AsyncSession) -> Dict[str, Any]:
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return {"success": False, "error": f"Batch {batch_id} not found"}

        # Só pedidos que de fato pertencem ao lote
        valid = (
            await s.execute(
                select(Order.order_id)
                .where(Order.order_id.in_(order_ids))
                .where(Order.batch_id == batch_id)
            )
        ).scalars().all() if order_ids else []

        queued = 0
        if valid:
            stmt = (
                insert(ProactiveAlertEvent)
                .values([
                    {"order_id": oid, "status": AlertStatus.PENDING,
                     "template_id": RECALL_ALERT_TEMPLATE_ID, "attempts": 0}
                    for oid in valid
                ])
                .on_conflict_do_nothing(constraint="uq_alert_per_order")
                .returning(ProactiveAlertEvent.order_id)
            )
            queued = len((await s.execute(stmt)).all())

        if not batch.proactive_recall_triggered:
            batch.proactive_recall_triggered = True

        await s.commit()
        logger.info("Proactive alerts queued for batch %s: %d new.", batch_id, queued)

        return {
            "success": True,
            "batch_id": batch_id,
            "alerts_queued": queued,
            "already_queued": len(valid) - queued,
            "ignored_order_ids": sorted(set(order_ids) - set(valid)),
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
            .outerjoin(Order, Ticket.order_id == Order.order_id)
            .outerjoin(Unit, Ticket.serial_number == Unit.serial_number)
            .where(or_(Order.batch_id == batch_id, Unit.batch_id == batch_id))
            .where(Ticket.intent == DEFECT_INTENT)
            .order_by(Ticket.created_at.desc())
            .limit(limit)
        )
        result = await s.execute(stmt)
        return [row[0] for row in result.all()]

    if session:
        return await _query(session)
    async with AsyncSessionLocal() as s:
        return await _query(s)
