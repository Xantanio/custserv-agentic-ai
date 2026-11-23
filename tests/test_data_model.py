"""Etapa 1: modelo de dados, dados sintéticos reprodutíveis e cenário plantado.

Duas camadas:
* testes sobre os CSVs (rápidos, sem banco);
* testes de integração no Postgres (`-m integration`), pulados se o banco não responder.
"""

import csv
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from scripts.generate_synthetic_data import generate

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SERIAL_RE = re.compile(r"^SN-[A-Z]{2,4}-\d{6}$")
CSV_FILES = ["batches.csv", "customers.csv", "orders.csv", "units.csv", "historic_tickets.csv"]


def _read(name: str) -> list[dict]:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def data():
    return {
        "batches": {b["batch_id"]: b for b in _read("batches.csv")},
        "orders": {o["order_id"]: o for o in _read("orders.csv")},
        "units": {u["serial_number"]: u for u in _read("units.csv")},
        "tickets": _read("historic_tickets.csv"),
    }


def _defect_tickets(data, batch_id):
    return [
        t for t in data["tickets"]
        if data["orders"][t["order_id"]]["batch_id"] == batch_id and t["intent"] == "defective_item"
    ]


# ---------------------------------------------------------------- reprodutibilidade
def test_generator_is_deterministic(tmp_path):
    """Regerar produz arquivos idênticos aos versionados (semente fixa + uuid5)."""
    generate(tmp_path)
    for name in CSV_FILES:
        assert (tmp_path / name).read_bytes() == (DATA_DIR / name).read_bytes(), (
            f"{name} diverge do gerador: rode scripts/generate_synthetic_data.py"
        )


def test_all_timestamps_are_timezone_aware(data):
    for o in data["orders"].values():
        assert datetime.fromisoformat(o["purchase_date"]).tzinfo is not None
    for u in data["units"].values():
        assert datetime.fromisoformat(u["manufactured_at"]).tzinfo is not None
    for t in data["tickets"]:
        assert datetime.fromisoformat(t["created_at"]).tzinfo is not None


# ---------------------------------------------------------------- integridade
def test_units_match_batches(data):
    per_batch = Counter(u["batch_id"] for u in data["units"].values())
    for batch_id, batch in data["batches"].items():
        assert per_batch[batch_id] == int(batch["total_units_produced"])
    for u in data["units"].values():
        assert SERIAL_RE.match(u["serial_number"])
        assert u["product_id"] == data["batches"][u["batch_id"]]["product_id"]


def test_units_belong_to_their_order_batch(data):
    for u in data["units"].values():
        if u["order_id"]:
            assert data["orders"][u["order_id"]]["batch_id"] == u["batch_id"]
    units_per_order = Counter(u["order_id"] for u in data["units"].values() if u["order_id"])
    assert set(units_per_order) == set(data["orders"]), "Todo pedido tem ao menos uma unidade"
    assert units_per_order["ORD-20052"] == 2, "Pedido com duas unidades (D6)"


def test_ticket_serial_is_the_customer_unit(data):
    """Serial informado existe e pertence ao pedido do próprio ticket."""
    for t in data["tickets"]:
        if t["serial_number"]:
            unit = data["units"][t["serial_number"]]
            assert unit["order_id"] == t["order_id"]


# ---------------------------------------------------------------- cenário 6.2
def test_baseline_counts_units_not_tickets(data):
    tickets = _defect_tickets(data, "LOTE-2026-DEF")
    serials = [t["serial_number"] for t in tickets if t["serial_number"]]
    assert len(set(serials)) == 49, "49 unidades distintas -> 49%"
    assert len(serials) - len(set(serials)) == 1, "Uma unidade reclamada duas vezes"
    assert sum(1 for t in tickets if not t["serial_number"]) == 1, "Uma reclamação sem serial"


def test_mariana_unit_is_reserved_and_uncomplained(data):
    mariana_units = [u for u in data["units"].values() if u["order_id"] == "ORD-20050"]
    assert len(mariana_units) == 1
    assert mariana_units[0]["production_line"] == "L2"
    assert not any(t["order_id"] == "ORD-20050" for t in data["tickets"])


# ---------------------------------------------------------------- causa plantada (8.2)
def test_planted_root_cause_is_line_l2(data):
    serials = {t["serial_number"] for t in _defect_tickets(data, "LOTE-2026-DEF") if t["serial_number"]}
    lines = Counter(data["units"][s]["production_line"] for s in serials)
    assert lines["L2"] / sum(lines.values()) >= 0.90


def test_l2_symptom_is_swollen_battery(data):
    for t in _defect_tickets(data, "LOTE-2026-DEF"):
        if t["serial_number"] and data["units"][t["serial_number"]]["production_line"] == "L2":
            assert "estufada" in t["message_text"] or "inchou" in t["message_text"]


def test_previous_batch_from_same_factory_is_healthy(data):
    sep, dfx = data["batches"]["LOTE-2026-SEP"], data["batches"]["LOTE-2026-DEF"]
    assert sep["factory_code"] == dfx["factory_code"] and sep["product_id"] == dfx["product_id"]
    serials = {t["serial_number"] for t in _defect_tickets(data, "LOTE-2026-SEP")}
    assert len(serials) / int(sep["total_units_produced"]) <= 0.05


def test_carrier_is_a_base_rate_distractor(data):
    """RotaSul aparece muito nas reclamações, mas na mesma proporção do volume.

    Um agente que olhe só a contagem bruta conclui errado; normalizando pela
    taxa-base, a transportadora não explica o defeito.
    """
    orders = [o for o in data["orders"].values() if o["batch_id"] == "LOTE-2026-DEF"]
    share_all = sum(o["carrier"] == "RotaSul" for o in orders) / len(orders)
    complaints = _defect_tickets(data, "LOTE-2026-DEF")
    share_complaints = sum(
        data["orders"][t["order_id"]]["carrier"] == "RotaSul" for t in complaints
    ) / len(complaints)
    assert Counter(data["orders"][t["order_id"]]["carrier"] for t in complaints).most_common(1)[0][0] == "RotaSul"
    assert abs(share_all - share_complaints) < 0.10


# ---------------------------------------------------------------- contratos
def test_ticket_schema_rejects_malformed_serial():
    from core.schemas import TicketBase

    base = {"thread_id": "t", "customer_id": uuid.uuid4(), "channel": "email",
            "message_text": "x", "intent": "defective_item"}
    assert TicketBase.model_validate({**base, "serial_number": "SN-SW-000123"}).serial_number
    assert TicketBase.model_validate(base).serial_number is None
    with pytest.raises(ValidationError):
        TicketBase.model_validate({**base, "serial_number": "SW-123"})


def test_new_tables_metadata():
    from core.database import Base

    tables = Base.metadata.tables
    assert {"units", "proactive_alert_events", "audit_events"} <= set(tables)
    assert "serial_number" in tables["tickets"].columns
    assert tables["tickets"].columns["serial_number"].nullable
    constraints = {c.name for c in tables["proactive_alert_events"].constraints}
    assert "uq_alert_per_order" in constraints


# ---------------------------------------------------------------- integração (Postgres)
async def _minimal_batch(s):
    from core.database import Batch, Customer, Order, Unit

    cid = uuid.uuid4()
    s.add(Batch(batch_id="LOTE-T", product_id="P", product_name="Produto",
                manufacturing_date=datetime(2026, 10, 1).date(), factory_code="F",
                total_units_produced=3))
    s.add(Batch(batch_id="LOTE-OUTRO", product_id="P", product_name="Produto",
                manufacturing_date=datetime(2026, 10, 1).date(), factory_code="F",
                total_units_produced=1))
    s.add(Customer(customer_id=cid, name="Teste", email="t@example.com", phone="+5511900000000"))
    await s.flush()
    now = datetime.now(timezone.utc)
    for oid, bid in [("O-1", "LOTE-T"), ("O-2", "LOTE-T"), ("O-X", "LOTE-OUTRO")]:
        s.add(Order(order_id=oid, customer_id=cid, product_id="P", batch_id=bid,
                    order_value=Decimal("10.00"), carrier="RotaSul", purchase_date=now))
    await s.flush()
    s.add(Unit(serial_number="SN-TT-000001", batch_id="LOTE-T", product_id="P",
               order_id="O-1", production_line="L1", manufactured_at=now))
    await s.commit()
    return cid


@pytest.mark.integration
async def test_queue_alerts_is_idempotent(db_session):
    from core.database import AlertStatus, ProactiveAlertEvent
    from mcp_server.inventory_tools import queue_proactive_alerts

    await _minimal_batch(db_session)
    first = await queue_proactive_alerts("LOTE-T", ["O-1", "O-2", "O-X"], session=db_session)
    second = await queue_proactive_alerts("LOTE-T", ["O-1", "O-2"], session=db_session)

    assert first["alerts_queued"] == 2
    assert first["ignored_order_ids"] == ["O-X"], "Pedido de outro lote é ignorado"
    assert second["alerts_queued"] == 0 and second["already_queued"] == 2
    events = (await db_session.execute(select(ProactiveAlertEvent))).scalars().all()
    assert len(events) == 2
    assert all(e.status == AlertStatus.PENDING for e in events), "Enfileirar não é enviar"


@pytest.mark.integration
async def test_only_delivered_alert_removes_order_from_silent_list(db_session):
    from core.database import AlertStatus, ProactiveAlertEvent
    from mcp_server.inventory_tools import get_silent_customers, queue_proactive_alerts

    await _minimal_batch(db_session)
    await queue_proactive_alerts("LOTE-T", ["O-1", "O-2"], session=db_session)
    pending = await get_silent_customers("LOTE-T", session=db_session)
    assert pending["silent_orders_count"] == 2, "pending ainda não conta como enviado"

    event = (await db_session.execute(
        select(ProactiveAlertEvent).where(ProactiveAlertEvent.order_id == "O-1")
    )).scalar_one()
    event.status = AlertStatus.DELIVERED
    await db_session.commit()
    after = await get_silent_customers("LOTE-T", session=db_session)
    assert [c["order_id"] for c in after["silent_orders"]] == ["O-2"]


@pytest.mark.integration
async def test_ticket_with_unknown_serial_is_rejected_by_fk(db_session):
    from core.database import ChannelType, Ticket

    cid = await _minimal_batch(db_session)
    db_session.add(Ticket(thread_id="t", customer_id=cid, order_id="O-1",
                          serial_number="SN-TT-999999", channel=ChannelType.EMAIL,
                          message_text="x", intent="defective_item"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
