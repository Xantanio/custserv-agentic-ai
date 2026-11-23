"""Etapa 2: regras determinísticas do lote (CLAUDE.md 6.2), sobre os dados do seed.

Taxa de falha = unidades DISTINTAS com defeito identificadas no lote / total produzido.
Clientes silenciosos = elegibilidade POR PEDIDO.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from core.database import (
    AlertStatus,
    ChannelType,
    Order,
    ProactiveAlertEvent,
    Ticket,
    Unit,
)
from mcp_server.inventory_tools import calculate_batch_failure_rate, get_silent_customers
from scripts.seed_db import seed

pytestmark = pytest.mark.integration

DEF = "LOTE-2026-DEF"
SEP = "LOTE-2026-SEP"


@pytest.fixture
async def s(db_session):
    """Sessão de teste já populada com os CSVs (desfeita ao fim do teste)."""
    await seed(db_session)
    return db_session


async def _unit_of(s, order_id: str) -> Unit:
    return (await s.execute(select(Unit).where(Unit.order_id == order_id))).scalars().first()


async def _complaint(s, order_id: str | None, serial: str | None, intent: str = "defective_item"):
    order = await s.get(Order, order_id) if order_id else None
    customer_id = order.customer_id if order else (
        await s.execute(select(Order.customer_id).limit(1))
    ).scalar_one()
    s.add(Ticket(
        thread_id=f"test-{uuid.uuid4()}", customer_id=customer_id, order_id=order_id,
        serial_number=serial, channel=ChannelType.WHATSAPP,
        message_text="Meu relógio está com defeito.", intent=intent,
    ))
    await s.commit()


# ------------------------------------------------------------------ taxa de falha
async def test_baseline_is_49_percent_counting_distinct_units(s):
    r = await calculate_batch_failure_rate(DEF, session=s)
    assert r["defective_units_count"] == 49
    assert r["defective_tickets_count"] == 51, "Tickets brutos continuam visíveis"
    assert r["unidentified_complaints_count"] == 1
    assert r["failure_rate"] == 0.49
    assert r["is_critical"] is False


async def test_marianas_complaint_is_the_50th_unit_and_triggers_critical(s):
    unit = await _unit_of(s, "ORD-20050")
    await _complaint(s, "ORD-20050", unit.serial_number)

    r = await calculate_batch_failure_rate(DEF, session=s)
    assert r["defective_units_count"] == 50
    assert r["failure_rate"] == 0.50
    assert r["is_critical"] is True


async def test_repeated_complaint_about_same_unit_counts_once(s):
    unit = await _unit_of(s, "ORD-20001")
    await _complaint(s, "ORD-20001", unit.serial_number)

    r = await calculate_batch_failure_rate(DEF, session=s)
    assert r["defective_units_count"] == 49
    assert r["is_critical"] is False


async def test_complaint_without_serial_is_counted_apart(s):
    await _complaint(s, "ORD-20051", None)

    r = await calculate_batch_failure_rate(DEF, session=s)
    assert r["defective_units_count"] == 49
    assert r["unidentified_complaints_count"] == 2


async def test_serial_from_another_batch_is_not_counted_anywhere(s):
    """Pedido do lote DEF citando serial do lote SEP: inconsistente, vai para HITL."""
    foreign = (await s.execute(
        select(Unit).where(Unit.batch_id == SEP, Unit.order_id.is_(None)).limit(1)
    )).scalar_one()
    await _complaint(s, "ORD-20051", foreign.serial_number)

    r_def = await calculate_batch_failure_rate(DEF, session=s)
    r_sep = await calculate_batch_failure_rate(SEP, session=s)
    assert r_def["defective_units_count"] == 49
    assert r_def["inconsistent_serial_complaints_count"] == 1
    assert r_sep["defective_units_count"] == 2, "Também não infla o lote do serial"


async def test_serial_without_order_counts_if_unit_is_in_batch(s):
    """Serial válido do lote, sem pedido informado: o serial identifica a unidade (D21)."""
    unit = await _unit_of(s, "ORD-20050")
    await _complaint(s, None, unit.serial_number)

    r = await calculate_batch_failure_rate(DEF, session=s)
    assert r["defective_units_count"] == 50


async def test_non_defect_intents_are_ignored(s):
    unit = await _unit_of(s, "ORD-20050")
    await _complaint(s, "ORD-20050", unit.serial_number, intent="tracking_inquiry")

    r = await calculate_batch_failure_rate(DEF, session=s)
    assert r["defective_units_count"] == 49


async def test_previous_batch_rate(s):
    r = await calculate_batch_failure_rate(SEP, session=s)
    assert r["defective_units_count"] == 2
    assert r["failure_rate"] == 0.02


async def test_unknown_batch(s):
    r = await calculate_batch_failure_rate("LOTE-INEXISTENTE", session=s)
    assert r["found"] is False


# ------------------------------------------------------------------ silenciosos por pedido
async def test_silent_orders_baseline(s):
    r = await get_silent_customers(DEF, session=s)
    ids = {o["order_id"] for o in r["silent_orders"]}
    assert r["silent_orders_count"] == 34
    assert {"ORD-20050", "ORD-20051", "ORD-20052", "ORD-30001"} <= ids
    assert "ORD-20053" not in ids, "Reclamou sem serial: não é silencioso"
    assert "ORD-20001" not in ids


async def test_complaint_removes_only_that_order(s):
    unit = await _unit_of(s, "ORD-20050")
    await _complaint(s, "ORD-20050", unit.serial_number)

    r = await get_silent_customers(DEF, session=s)
    assert r["silent_orders_count"] == 33
    assert "ORD-20050" not in {o["order_id"] for o in r["silent_orders"]}


async def test_eligibility_is_per_order_not_per_customer(s):
    """Quem reclamou de um pedido continua elegível ao alerta pelo OUTRO pedido do lote."""
    complainer = await s.get(Order, "ORD-20001")
    s.add(Order(order_id="ORD-29999", customer_id=complainer.customer_id,
                product_id="PROD-SMART-WATCH-X", batch_id=DEF, order_value=Decimal("349.90"),
                carrier="TransVale", purchase_date=datetime.now(timezone.utc)))
    await s.flush()
    stock = (await s.execute(
        select(Unit).where(Unit.batch_id == DEF, Unit.order_id.is_(None)).limit(1)
    )).scalar_one()
    stock.order_id = "ORD-29999"
    await s.commit()

    ids = {o["order_id"] for o in (await get_silent_customers(DEF, session=s))["silent_orders"]}
    assert "ORD-29999" in ids
    assert "ORD-20001" not in ids


async def test_complaint_by_serial_only_removes_the_owning_order(s):
    unit = await _unit_of(s, "ORD-20051")
    await _complaint(s, None, unit.serial_number)

    ids = {o["order_id"] for o in (await get_silent_customers(DEF, session=s))["silent_orders"]}
    assert "ORD-20051" not in ids


async def test_delivered_alert_removes_order_but_pending_does_not(s):
    s.add(ProactiveAlertEvent(order_id="ORD-20051", status=AlertStatus.DELIVERED,
                              template_id="recall_alert_v1", attempts=1))
    s.add(ProactiveAlertEvent(order_id="ORD-20052", status=AlertStatus.PENDING,
                              template_id="recall_alert_v1"))
    await s.commit()

    r = await get_silent_customers(DEF, session=s)
    ids = {o["order_id"] for o in r["silent_orders"]}
    assert "ORD-20051" not in ids and "ORD-20052" in ids
    rate = await calculate_batch_failure_rate(DEF, session=s)
    assert rate["silent_orders_count"] == 33


async def test_order_citing_unsold_unit_is_inconsistent_not_lost(s):
    """Armadilha de NULL: o serial é do lote, mas a unidade está em estoque (order_id NULL).

    `ticket.order_id = unit.order_id` daria NULL em SQL; o ticket sumiria das
    duas contagens. Ele precisa aparecer como inconsistente (HITL).
    """
    stock = (await s.execute(
        select(Unit).where(Unit.batch_id == DEF, Unit.order_id.is_(None)).limit(1)
    )).scalar_one()
    await _complaint(s, "ORD-20051", stock.serial_number)

    r = await calculate_batch_failure_rate(DEF, session=s)
    assert r["defective_units_count"] == 49
    assert r["inconsistent_serial_complaints_count"] == 1
