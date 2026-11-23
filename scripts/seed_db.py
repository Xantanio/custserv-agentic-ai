"""Popula o PostgreSQL a partir de data/*.csv.

Idempotente: para cada tabela, busca as chaves já existentes em UMA consulta e
insere só as linhas novas. Datas vêm em ISO 8601 com fuso (UTC). A ordem de
carga respeita as FKs: lotes, clientes, pedidos, unidades e, por fim, tickets
(que referenciam unidades pelo serial).

`seed(session, data_dir)` também é usado pelos testes de integração.
"""

import asyncio
import csv
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    AsyncSessionLocal,
    AutonomyStatus,
    Base,
    Batch,
    CarrierStatus,
    ChannelType,
    Customer,
    CustomerTier,
    Order,
    SentimentLabel,
    Ticket,
    Unit,
    engine,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_db")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "t")


def _batch(r: dict) -> Batch:
    return Batch(
        batch_id=r["batch_id"],
        product_id=r["product_id"],
        product_name=r["product_name"],
        manufacturing_date=datetime.strptime(r["manufacturing_date"], "%Y-%m-%d").date(),
        factory_code=r["factory_code"],
        total_units_produced=int(r["total_units_produced"]),
        is_blocked=_bool(r["is_blocked"]),
        proactive_recall_triggered=_bool(r["proactive_recall_triggered"]),
    )


def _customer(r: dict) -> Customer:
    return Customer(
        customer_id=uuid.UUID(r["customer_id"]),
        name=r["name"],
        email=r["email"],
        phone=r["phone"],
        tier=CustomerTier(r["tier"]),
        lifetime_value=Decimal(r["lifetime_value"]),
        total_orders=int(r["total_orders"]),
        return_rate=float(r["return_rate"]),
    )


def _order(r: dict) -> Order:
    return Order(
        order_id=r["order_id"],
        customer_id=uuid.UUID(r["customer_id"]),
        product_id=r["product_id"],
        batch_id=r["batch_id"],
        order_value=Decimal(r["order_value"]),
        carrier_status=CarrierStatus(r["carrier_status"]),
        carrier=r["carrier"],
        purchase_date=datetime.fromisoformat(r["purchase_date"]),
    )


def _unit(r: dict) -> Unit:
    return Unit(
        serial_number=r["serial_number"],
        batch_id=r["batch_id"],
        product_id=r["product_id"],
        order_id=r["order_id"] or None,
        production_line=r["production_line"],
        manufactured_at=datetime.fromisoformat(r["manufactured_at"]),
    )


def _ticket(r: dict) -> Ticket:
    return Ticket(
        ticket_id=uuid.UUID(r["ticket_id"]),
        thread_id=r["thread_id"],
        customer_id=uuid.UUID(r["customer_id"]),
        order_id=r["order_id"] or None,
        serial_number=r["serial_number"] or None,
        channel=ChannelType(r["channel"]),
        message_text=r["message_text"],
        intent=r["intent"],
        sentiment_score=float(r["sentiment_score"]),
        sentiment_label=SentimentLabel(r["sentiment_label"]),
        is_health_risk=_bool(r["is_health_risk"]),
        batch_flagged=_bool(r["batch_flagged"]),
        priority_score=int(r["priority_score"]),
        autonomy_status=AutonomyStatus(r["autonomy_status"]),
        created_at=datetime.fromisoformat(r["created_at"]),
    )


# (arquivo, modelo, coluna de chave primária, conversor) na ordem das FKs
LOAD_ORDER: list[tuple[str, type[Base], str, Callable[[dict], Base]]] = [
    ("batches.csv", Batch, "batch_id", _batch),
    ("customers.csv", Customer, "customer_id", _customer),
    ("orders.csv", Order, "order_id", _order),
    ("units.csv", Unit, "serial_number", _unit),
    ("historic_tickets.csv", Ticket, "ticket_id", _ticket),
]


async def seed(session: AsyncSession, data_dir: Path = DATA_DIR) -> dict[str, int]:
    """Insere as linhas ausentes de cada CSV. Devolve quantas foram inseridas por arquivo."""
    inserted: dict[str, int] = {}
    for filename, model, pk, convert in LOAD_ORDER:
        path = data_dir / filename
        if not path.exists():
            logger.warning("%s not found, skipping.", filename)
            continue
        existing = set((await session.execute(select(getattr(model, pk)))).scalars().all())
        with open(path, encoding="utf-8") as f:
            new = [obj for obj in map(convert, csv.DictReader(f)) if getattr(obj, pk) not in existing]
        session.add_all(new)
        await session.flush()
        inserted[filename] = len(new)
        logger.info("%s: %d new rows.", filename, len(new))
    await session.commit()
    return inserted


async def main() -> None:
    logger.info("Initializing database schema...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await seed(session)

    logger.info("Database seeding completed.")


if __name__ == "__main__":
    asyncio.run(main())
