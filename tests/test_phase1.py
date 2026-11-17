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
    """Verify that LOTE-2026-DEF has exactly 49 defective tickets recorded,

    which equals 49 / 100 = 49% baseline failure rate.
    """
    tickets_path = DATA_DIR / "historic_tickets.csv"
    orders_path = DATA_DIR / "orders.csv"

    with open(orders_path, "r", encoding="utf-8") as f:
        order_to_batch = {row["order_id"]: row["batch_id"] for row in csv.DictReader(f)}

    with open(tickets_path, "r", encoding="utf-8") as f:
        tickets = list(csv.DictReader(f))

    def_batch_tickets = [
        t for t in tickets
        if order_to_batch.get(t["order_id"]) == "LOTE-2026-DEF" and t["intent"] == "defective_item"
    ]

    assert len(def_batch_tickets) == 49, f"Expected 49 baseline defect tickets, got {len(def_batch_tickets)}"


def test_silent_customers_ready_for_proactive_alert():
    """Verify that there are orders for LOTE-2026-DEF whose customers

    have not filed any complaint yet and proactive_alert_sent == False.
    """
    orders_path = DATA_DIR / "orders.csv"
    tickets_path = DATA_DIR / "historic_tickets.csv"

    with open(tickets_path, "r", encoding="utf-8") as f:
        complaining_customers = {row["customer_id"] for row in csv.DictReader(f)}

    with open(orders_path, "r", encoding="utf-8") as f:
        orders = list(csv.DictReader(f))

    silent_orders = [
        o for o in orders
        if o["batch_id"] == "LOTE-2026-DEF"
        and o["customer_id"] not in complaining_customers
        and o["proactive_alert_sent"].lower() in ("false", "0", "f")
    ]

    # Mariana (who will complain next), Lucas Silencioso, Beatriz Silenciosa, Fernanda Alergia
    assert len(silent_orders) >= 3, "Expected at least 3 silent customer orders for LOTE-2026-DEF"



def test_pydantic_v2_schemas():
    from core.schemas import (
        StandardTicket,
        BatchFailureMetrics,
        ProactiveAlertPayload,
        SpecialistDossierPayload,
    )
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

    # 2. BatchFailureMetrics
    metrics = BatchFailureMetrics(
        batch_id="LOTE-2026-DEF",
        product_id="PROD-SMART-WATCH-X",
        product_name="Smartwatch Omni Pulse V2",
        total_units_produced=100,
        defective_tickets_count=50,
        failure_rate=0.50,
        is_critical=True,
        silent_customers_count=4,
    )
    assert metrics.is_critical is True
    assert metrics.failure_rate >= 0.50

    # 3. SpecialistDossierPayload
    import datetime
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

    # Check order columns
    order_cols = {c.name for c in tables["orders"].columns}
    assert "proactive_alert_sent" in order_cols
