"""Unit tests validating Phase 1: schema integrity, synthetic CSV data consistency, and edge cases."""

import csv
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def test_batches_csv_integrity():
    file_path = DATA_DIR / "batches.csv"
    assert file_path.exists(), "batches.csv should exist"

    with open(file_path, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    assert len(reader) >= 3, "Should have at least 3 batches"
    batch_ids = {row["batch_id"] for row in reader}
    assert "LOTE-2026-DEF" in batch_ids, "LOTE-2026-DEF must exist for testing trigger"

    def_batch = next(b for b in reader if b["batch_id"] == "LOTE-2026-DEF")
    assert int(def_batch["total_units_produced"]) == 100
    assert def_batch["is_blocked"].lower() in ("false", "0", "f")


def test_customers_csv_integrity():
    file_path = DATA_DIR / "customers.csv"
    assert file_path.exists(), "customers.csv should exist"

    with open(file_path, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    assert len(reader) >= 50, "Should have 50+ customers including historical reporters"
    emails = set()
    for row in reader:
        # Validate UUID format
        uuid.UUID(row["customer_id"])
        # Validate unique emails
        assert row["email"] not in emails, f"Duplicate email found: {row['email']}"
        emails.add(row["email"])
        # Validate tier
        assert row["tier"] in ("VIP", "Regular", "New")
        assert float(row["lifetime_value"]) >= 0
        assert 0.0 <= float(row["return_rate"]) <= 1.0


def test_orders_csv_integrity():
    batches_path = DATA_DIR / "batches.csv"
    customers_path = DATA_DIR / "customers.csv"
    orders_path = DATA_DIR / "orders.csv"

    with open(batches_path, "r", encoding="utf-8") as f:
        valid_batches = {row["batch_id"] for row in csv.DictReader(f)}
    with open(customers_path, "r", encoding="utf-8") as f:
        valid_customers = {row["customer_id"] for row in csv.DictReader(f)}

    with open(orders_path, "r", encoding="utf-8") as f:
        orders = list(csv.DictReader(f))

    assert len(orders) >= 50
    for order in orders:
        assert order["batch_id"] in valid_batches, f"Invalid batch_id in order: {order['batch_id']}"
        assert order["customer_id"] in valid_customers, f"Invalid customer_id in order: {order['customer_id']}"
        assert float(order["order_value"]) >= 0
        assert order["carrier_status"] in ("in_transit", "delivered_signed", "delayed")


def test_historic_defect_ratio_baseline():
    """LOTE-2026-DEF tem 49 UNIDADES distintas com defeito (49/100 = 49%).

    Há 51 tickets de defeito no lote (uma unidade reclamada duas vezes e uma
    reclamação sem serial): contar tickets daria 51% e dispararia o bloqueio
    por engano. A taxa correta conta seriais distintos (6.2).
    """
    with open(DATA_DIR / "orders.csv", "r", encoding="utf-8") as f:
        order_to_batch = {row["order_id"]: row["batch_id"] for row in csv.DictReader(f)}
    with open(DATA_DIR / "historic_tickets.csv", "r", encoding="utf-8") as f:
        tickets = list(csv.DictReader(f))

    def_tickets = [
        t for t in tickets
        if order_to_batch.get(t["order_id"]) == "LOTE-2026-DEF" and t["intent"] == "defective_item"
    ]
    distinct_serials = {t["serial_number"] for t in def_tickets if t["serial_number"]}

    assert len(def_tickets) == 51
    assert len(distinct_serials) == 49, f"Expected 49 distinct units, got {len(distinct_serials)}"


def test_silent_customers_ready_for_proactive_alert():
    """Há pedidos do LOTE-2026-DEF sem reclamação de defeito (candidatos ao alerta).

    Elegibilidade por pedido (6.2); nenhum alerta existe ainda no seed.
    """
    with open(DATA_DIR / "historic_tickets.csv", "r", encoding="utf-8") as f:
        complained_orders = {row["order_id"] for row in csv.DictReader(f)}
    with open(DATA_DIR / "orders.csv", "r", encoding="utf-8") as f:
        orders = list(csv.DictReader(f))

    silent_orders = [
        o for o in orders
        if o["batch_id"] == "LOTE-2026-DEF" and o["order_id"] not in complained_orders
    ]
    # Mariana (reclamará depois), Lucas, Beatriz, Fernanda e 30 compradores silenciosos
    assert len(silent_orders) == 34
    assert {"ORD-20050", "ORD-20051", "ORD-20052", "ORD-30001"} <= {o["order_id"] for o in silent_orders}


def test_pydantic_v2_schemas():
    from core.schemas import (
        StandardTicket,
        BatchFailureMetrics,
        ProactiveAlertPayload,
        SpecialistDossierPayload,
    )
    import datetime

    from core.database import ChannelType

    # 1. StandardTicket
    ticket_payload = {
        "thread_id": "thread-test-123",
        "channel": "whatsapp",
        "customer_phone": "+5511987654321",
        "raw_message": "Meu relógio não liga após recarga.",
    }
    st = StandardTicket.model_validate(ticket_payload)
    assert st.thread_id == "thread-test-123"
    assert st.channel == ChannelType.WHATSAPP
    dumped = st.model_dump()
    assert dumped["channel"] == ChannelType.WHATSAPP

    # 2. BatchFailureMetrics (taxa por unidades distintas, 6.2)
    metrics = BatchFailureMetrics(
        batch_id="LOTE-2026-DEF",
        product_id="PROD-SMART-WATCH-X",
        product_name="Smartwatch Omni Pulse V2",
        factory_code="FAC-SP-01",
        manufacturing_date=datetime.date(2026, 10, 1),
        total_units_produced=100,
        defective_units_count=50,
        defective_tickets_count=52,
        unidentified_complaints_count=1,
        inconsistent_serial_complaints_count=0,
        failure_rate=0.50,
        critical_threshold=0.50,
        is_critical=True,
        rule_id="batch.failure_rate.critical_v1",
        is_blocked=False,
        proactive_recall_triggered=False,
        silent_orders_count=33,
    )
    assert metrics.is_critical is True
    assert metrics.model_dump(mode="json")["manufacturing_date"] == "2026-10-01"

    # 3. SpecialistDossierPayload
    dossier = SpecialistDossierPayload(
        batch_id="LOTE-2026-DEF",
        factory_code="FAC-SP-01",
        manufacturing_date=datetime.date(2026, 10, 1),
        product_id="PROD-SMART-WATCH-X",
        product_name="Smartwatch Omni Pulse V2",
        total_units_produced=100,
        defective_tickets_count=50,
        failure_rate=0.50,
        reported_symptoms_sample=["Tela preta", "Bateria estufada"],
        is_blocked=True,
        silent_customers_alerted=4,
        thread_id="thread-test-123",
    )
    assert dossier.urgency == "CRÍTICA"
    assert dossier.silent_customers_alerted == 4


def test_sqlalchemy_table_metadata():
    from core.database import Base, Customer, Batch, Order, Ticket

    tables = Base.metadata.tables
    assert "customers" in tables
    assert "batches" in tables
    assert "orders" in tables
    assert "tickets" in tables

    # Check batch columns
    batch_cols = {c.name for c in tables["batches"].columns}
    assert "is_blocked" in batch_cols
    assert "proactive_recall_triggered" in batch_cols

    # O booleano de alerta foi substituído por proactive_alert_events
    order_cols = {c.name for c in tables["orders"].columns}
    assert "proactive_alert_sent" not in order_cols
    assert "carrier" in order_cols
