"""Populates PostgreSQL with initial synthetic datasets from data/*.csv."""

import asyncio
import csv
import logging
import uuid
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, delete
from core.database import (
    Base,
    engine,
    AsyncSessionLocal,
    Customer,
    Batch,
    Order,
    Ticket,
    CustomerTier,
    CarrierStatus,
    ChannelType,
    SentimentLabel,
    AutonomyStatus,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_db")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


async def seed_batches(session) -> None:
    file_path = DATA_DIR / "batches.csv"
    if not file_path.exists():
        logger.warning("batches.csv not found, skipping.")
        return

    logger.info("Seeding batches from %s...", file_path)
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing = await session.get(Batch, row["batch_id"])
            if not existing:
                batch = Batch(
                    batch_id=row["batch_id"],
                    product_id=row["product_id"],
                    product_name=row["product_name"],
                    manufacturing_date=datetime.strptime(row["manufacturing_date"], "%Y-%m-%d").date(),
                    factory_code=row["factory_code"],
                    total_units_produced=int(row["total_units_produced"]),
                    is_blocked=row["is_blocked"].lower() in ("true", "1", "t"),
                    proactive_recall_triggered=row["proactive_recall_triggered"].lower() in ("true", "1", "t"),
                )
                session.add(batch)
    await session.commit()
    logger.info("Batches seeded successfully.")


async def seed_customers(session) -> None:
    file_path = DATA_DIR / "customers.csv"
    if not file_path.exists():
        logger.warning("customers.csv not found, skipping.")
        return

    logger.info("Seeding customers from %s...", file_path)
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cust_id = uuid.UUID(row["customer_id"])
            existing = await session.get(Customer, cust_id)
            if not existing:
                customer = Customer(
                    customer_id=cust_id,
                    name=row["name"],
                    email=row["email"],
                    phone=row["phone"],
                    tier=CustomerTier(row["tier"]),
                    lifetime_value=Decimal(row["lifetime_value"]),
                    total_orders=int(row["total_orders"]),
                    return_rate=float(row["return_rate"]),
                )
                session.add(customer)
    await session.commit()
    logger.info("Customers seeded successfully.")


async def seed_orders(session) -> None:
    file_path = DATA_DIR / "orders.csv"
    if not file_path.exists():
        logger.warning("orders.csv not found, skipping.")
        return

    logger.info("Seeding orders from %s...", file_path)
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing = await session.get(Order, row["order_id"])
            if not existing:
                order = Order(
                    order_id=row["order_id"],
                    customer_id=uuid.UUID(row["customer_id"]),
                    product_id=row["product_id"],
                    batch_id=row["batch_id"],
                    order_value=Decimal(row["order_value"]),
                    carrier_status=CarrierStatus(row["carrier_status"]),
                    proactive_alert_sent=row["proactive_alert_sent"].lower() in ("true", "1", "t"),
                    purchase_date=datetime.strptime(row["purchase_date"], "%Y-%m-%d %H:%M:%S"),
                )
                session.add(order)
    await session.commit()
    logger.info("Orders seeded successfully.")


async def seed_historic_tickets(session) -> None:
    file_path = DATA_DIR / "historic_tickets.csv"
    if not file_path.exists():
        logger.warning("historic_tickets.csv not found, skipping.")
        return

    logger.info("Seeding historic tickets from %s...", file_path)
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticket_id = uuid.UUID(row["ticket_id"])
            existing = await session.get(Ticket, ticket_id)
            if not existing:
                ticket = Ticket(
                    ticket_id=ticket_id,
                    thread_id=row["thread_id"],
                    customer_id=uuid.UUID(row["customer_id"]),
                    order_id=row["order_id"] if row["order_id"] else None,
                    unit_identifier=row.get("unit_identifier") or None,
                    channel=ChannelType(row["channel"]),
                    message_text=row["message_text"],
                    intent=row["intent"],
                    sentiment_score=float(row["sentiment_score"]),
                    sentiment_label=SentimentLabel(row["sentiment_label"]),
                    is_health_risk=row["is_health_risk"].lower() in ("true", "1", "t"),
                    batch_flagged=row["batch_flagged"].lower() in ("true", "1", "t"),
                    priority_score=int(row["priority_score"]),
                    autonomy_status=AutonomyStatus(row["autonomy_status"]),
                    created_at=datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S"),
                )
                session.add(ticket)
    await session.commit()
    logger.info("Historic tickets seeded successfully.")


async def main() -> None:
    logger.info("Initializing database schema...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await seed_batches(session)
        await seed_customers(session)
        await seed_orders(session)
        await seed_historic_tickets(session)

    logger.info("Database seeding completed.")


if __name__ == "__main__":
    asyncio.run(main())
