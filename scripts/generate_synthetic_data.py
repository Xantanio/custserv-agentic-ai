"""Script to generate realistic synthetic CSV datasets for OmniOps AI testing and seeding."""

import csv
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# 1. Batches
# -----------------------------------------------------------------------------
batches = [
    {
        "batch_id": "LOTE-2026-DEF",
        "product_id": "PROD-SMART-WATCH-X",
        "product_name": "Smartwatch Omni Pulse V2",
        "manufacturing_date": "2026-10-01",
        "factory_code": "FAC-SP-01",
        "total_units_produced": 100,
        "is_blocked": False,
        "proactive_recall_triggered": False,
    },
    {
        "batch_id": "LOTE-2026-OK",
        "product_id": "PROD-EARBUDS-PRO",
        "product_name": "Fone de Ouvido Noise Cancel Pro",
        "manufacturing_date": "2026-09-15",
        "factory_code": "FAC-AM-02",
        "total_units_produced": 500,
        "is_blocked": False,
        "proactive_recall_triggered": False,
    },
    {
        "batch_id": "LOTE-2026-BLOCKED",
        "product_id": "PROD-POWERBANK-MAX",
        "product_name": "Carregador Portátil 20000mAh Ultra",
        "manufacturing_date": "2026-08-10",
        "factory_code": "FAC-SC-03",
        "total_units_produced": 200,
        "is_blocked": True,
        "proactive_recall_triggered": True,
    },
]

with open(DATA_DIR / "batches.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=batches[0].keys())
    writer.writeheader()
    writer.writerows(batches)

print("batches.csv generated.")

# -----------------------------------------------------------------------------
# 2. Customers
# -----------------------------------------------------------------------------
key_customers = [
    {
        "customer_id": "a1111111-1111-1111-1111-111111111111",
        "name": "Carlos Alberto VIP",
        "email": "carlos.vip@example.com",
        "phone": "+5511987654321",
        "tier": "VIP",
        "lifetime_value": "2500.00",
        "total_orders": 12,
        "return_rate": 0.04,
    },
    {
        "customer_id": "b2222222-2222-2222-2222-222222222222",
        "name": "Mariana Souza",
        "email": "mariana.souza@example.com",
        "phone": "+5511976543210",
        "tier": "Regular",
        "lifetime_value": "450.00",
        "total_orders": 2,
        "return_rate": 0.0,
    },
    {
        "customer_id": "c3333333-3333-3333-3333-333333333333",
        "name": "Lucas Silencioso",
        "email": "lucas.silva@example.com",
        "phone": "+5511912345678",
        "tier": "Regular",
        "lifetime_value": "320.00",
        "total_orders": 1,
        "return_rate": 0.0,
    },
    {
        "customer_id": "d4444444-4444-4444-4444-444444444444",
        "name": "Beatriz Silenciosa",
        "email": "beatriz.oliveira@example.com",
        "phone": "+5521998877665",
        "tier": "VIP",
        "lifetime_value": "1800.00",
        "total_orders": 6,
        "return_rate": 0.0,
    },
    {
        "customer_id": "e5555555-5555-5555-5555-555555555555",
        "name": "Fernanda Alergia",
        "email": "fernanda.alergia@example.com",
        "phone": "+5531988771122",
        "tier": "New",
        "lifetime_value": "89.00",
        "total_orders": 1,
        "return_rate": 0.0,
    },
    {
        "customer_id": "f6666666-6666-6666-6666-666666666666",
        "name": "Marcos Suspeito",
        "email": "marcos.suspeito@example.com",
        "phone": "+5541991122334",
        "tier": "New",
        "lifetime_value": "150.00",
        "total_orders": 3,
        "return_rate": 0.67,
    },
]

# Generate 49 historical customer accounts for the 49 defect tickets in LOTE-2026-DEF
customers = list(key_customers)
for i in range(1, 50):
    cust_id = f"10000000-0000-0000-0000-{i:012d}"
    customers.append({
        "customer_id": cust_id,
        "name": f"Consumidor Historico {i:02d}",
        "email": f"historico{i:02d}@example.com",
        "phone": f"+551199000{i:04d}",
        "tier": "Regular",
        "lifetime_value": "399.00",
        "total_orders": 1,
        "return_rate": 0.0,
    })

with open(DATA_DIR / "customers.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=customers[0].keys())
    writer.writeheader()
    writer.writerows(customers)

print(f"customers.csv generated ({len(customers)} rows).")

# -----------------------------------------------------------------------------
# 3. Orders
# -----------------------------------------------------------------------------
orders = []

# Order for Carlos VIP (tracking query)
orders.append({
    "order_id": "ORD-10001",
    "customer_id": "a1111111-1111-1111-1111-111111111111",
    "product_id": "PROD-EARBUDS-PRO",
    "batch_id": "LOTE-2026-OK",
    "order_value": "89.90",
    "carrier_status": "in_transit",
    "proactive_alert_sent": False,
    "purchase_date": "2026-11-10 14:30:00",
})

# Order for Mariana Souza (she bought LOTE-2026-DEF and will report the 50th defect)
orders.append({
    "order_id": "ORD-20050",
    "customer_id": "b2222222-2222-2222-2222-222222222222",
    "product_id": "PROD-SMART-WATCH-X",
    "batch_id": "LOTE-2026-DEF",
    "order_value": "349.90",
    "carrier_status": "delivered_signed",
    "proactive_alert_sent": False,
    "purchase_date": "2026-11-05 10:15:00",
})

# Order for Lucas Silencioso (Silent customer of LOTE-2026-DEF, to be proactively alerted)
orders.append({
    "order_id": "ORD-20051",
    "customer_id": "c3333333-3333-3333-3333-333333333333",
    "product_id": "PROD-SMART-WATCH-X",
    "batch_id": "LOTE-2026-DEF",
    "order_value": "349.90",
    "carrier_status": "delivered_signed",
    "proactive_alert_sent": False,
    "purchase_date": "2026-11-06 16:45:00",
})

# Order for Beatriz Silenciosa (Silent VIP customer of LOTE-2026-DEF, to be proactively alerted)
orders.append({
    "order_id": "ORD-20052",
    "customer_id": "d4444444-4444-4444-4444-444444444444",
    "product_id": "PROD-SMART-WATCH-X",
    "batch_id": "LOTE-2026-DEF",
    "order_value": "349.90",
    "carrier_status": "delivered_signed",
    "proactive_alert_sent": False,
    "purchase_date": "2026-11-07 11:20:00",
})

# Order for Fernanda Alergia (health issue test)
orders.append({
    "order_id": "ORD-30001",
    "customer_id": "e5555555-5555-5555-5555-555555555555",
    "product_id": "PROD-SMART-WATCH-X",
    "batch_id": "LOTE-2026-DEF",
    "order_value": "349.90",
    "carrier_status": "delivered_signed",
    "proactive_alert_sent": False,
    "purchase_date": "2026-11-08 09:00:00",
})

# Order for Marcos Suspeito (fraud test - claiming box was empty)
orders.append({
    "order_id": "ORD-40001",
    "customer_id": "f6666666-6666-6666-6666-666666666666",
    "product_id": "PROD-POWERBANK-MAX",
    "batch_id": "LOTE-2026-BLOCKED",
    "order_value": "599.00",
    "carrier_status": "delivered_signed",
    "proactive_alert_sent": False,
    "purchase_date": "2026-11-09 18:30:00",
})

# 49 orders for the 49 defect tickets already logged for LOTE-2026-DEF
for i in range(1, 50):
    cust_id = f"10000000-0000-0000-0000-{i:012d}"
    orders.append({
        "order_id": f"ORD-200{i:02d}",
        "customer_id": cust_id,
        "product_id": "PROD-SMART-WATCH-X",
        "batch_id": "LOTE-2026-DEF",
        "order_value": "349.90",
        "carrier_status": "delivered_signed",
        "proactive_alert_sent": False,
        "purchase_date": f"2026-10-15 12:00:00",
    })

with open(DATA_DIR / "orders.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=orders[0].keys())
    writer.writeheader()
    writer.writerows(orders)

print(f"orders.csv generated ({len(orders)} rows).")

# -----------------------------------------------------------------------------
# 4. Historic Tickets (49 defect tickets on LOTE-2026-DEF -> 49 / 100 = 49%)
# -----------------------------------------------------------------------------
historic_tickets = []
for i in range(1, 50):
    cust_id = f"10000000-0000-0000-0000-{i:012d}"
    order_id = f"ORD-200{i:02d}"
    historic_tickets.append({
        "ticket_id": str(uuid.uuid4()),
        "thread_id": f"hist-thread-{i:03d}",
        "customer_id": cust_id,
        "order_id": order_id,
        "unit_identifier": f"UNIT-DEF-{i:03d}",
        "channel": "email" if i % 2 == 0 else "whatsapp",
        "message_text": f"O relogio do lote LOTE-2026-DEF apresentou tela preta e parou de carregar apos 2 dias de uso (caso {i}).",
        "intent": "defective_item",
        "sentiment_score": -0.75,
        "sentiment_label": "Extremamente Negativo",
        "is_health_risk": False,
        "batch_flagged": False,
        "priority_score": 60,
        "autonomy_status": "human_in_the_loop",
        "created_at": f"2026-11-0{min(i, 9)} 10:00:00" if i <= 9 else f"2026-11-12 10:{i%60:02d}:00",
    })

with open(DATA_DIR / "historic_tickets.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=historic_tickets[0].keys())
    writer.writeheader()
    writer.writerows(historic_tickets)

print(f"historic_tickets.csv generated ({len(historic_tickets)} rows).")
