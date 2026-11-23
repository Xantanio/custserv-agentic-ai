import uuid
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import AsyncGenerator
import enum

from sqlalchemy import (
    String,
    Boolean,
    Integer,
    Float,
    Numeric,
    Text,
    Date,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from core.config import settings


# -----------------------------------------------------------------------------
# Database Engine and Session Factory
# -----------------------------------------------------------------------------
engine = create_async_engine(
    settings.get_database_url(),
    echo=False,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------
class CustomerTier(str, enum.Enum):
    VIP = "VIP"
    REGULAR = "Regular"
    NEW = "New"


class CarrierStatus(str, enum.Enum):
    IN_TRANSIT = "in_transit"
    DELIVERED_SIGNED = "delivered_signed"
    DELAYED = "delayed"


class ChannelType(str, enum.Enum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    RECLAME_AQUI = "reclame_aqui"


class SentimentLabel(str, enum.Enum):
    POSITIVO = "Positivo"
    NEUTRO = "Neutro"
    NEGATIVO = "Negativo"
    EXTREMAMENTE_NEGATIVO = "Extremamente Negativo"


class AutonomyStatus(str, enum.Enum):
    AUTO_RESOLVED = "auto_resolved"
    HUMAN_IN_THE_LOOP = "human_in_the_loop"
    ESCALATED_SPECIALIST = "escalated_specialist"


class AlertStatus(str, enum.Enum):
    """Ciclo de vida de um alerta proativo. Só `delivered` conta como enviado."""

    PENDING = "pending"
    ATTEMPTED = "attempted"
    FAILED = "failed"
    DELIVERED = "delivered"


class AuditKind(str, enum.Enum):
    """Natureza do evento de auditoria (princípio 6 do CLAUDE.md)."""

    MODEL_INTERPRETATION = "model_interpretation"
    TOOL_RESULT = "tool_result"
    RULE_APPLIED = "rule_applied"
    DECISION = "decision"
    ACTION = "action"


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    tier: Mapped[CustomerTier] = mapped_column(
        SQLEnum(CustomerTier, native_enum=False), nullable=False, default=CustomerTier.REGULAR
    )
    lifetime_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    total_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    return_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Relationships
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="customer")
    tickets: Mapped[list["Ticket"]] = relationship("Ticket", back_populates="customer")


class Batch(Base):
    __tablename__ = "batches"

    batch_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    manufacturing_date: Mapped[date] = mapped_column(Date, nullable=False)
    factory_code: Mapped[str] = mapped_column(String(50), nullable=False)
    total_units_produced: Mapped[int] = mapped_column(Integer, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    proactive_recall_triggered: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Relationships
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="batch")
    units: Mapped[list["Unit"]] = relationship("Unit", back_populates="batch")


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.customer_id"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    batch_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("batches.batch_id"), nullable=False, index=True
    )
    order_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    carrier_status: Mapped[CarrierStatus] = mapped_column(
        SQLEnum(CarrierStatus, native_enum=False), nullable=False, default=CarrierStatus.IN_TRANSIT
    )
    carrier: Mapped[str] = mapped_column(String(50), nullable=False)
    purchase_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    customer: Mapped["Customer"] = relationship("Customer", back_populates="orders")
    batch: Mapped["Batch"] = relationship("Batch", back_populates="orders")
    tickets: Mapped[list["Ticket"]] = relationship("Ticket", back_populates="order")
    units: Mapped[list["Unit"]] = relationship("Unit", back_populates="order")
    alert_events: Mapped[list["ProactiveAlertEvent"]] = relationship(
        "ProactiveAlertEvent", back_populates="order"
    )


class Unit(Base):
    """Unidade física produzida, identificada pelo número de série (D6, D10).

    A taxa de falha conta unidades distintas, não tickets; `production_line` e
    `manufactured_at` existem para a investigação de causa raiz.
    """

    __tablename__ = "units"

    serial_number: Mapped[str] = mapped_column(String(20), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("batches.batch_id"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    order_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("orders.order_id"), nullable=True, index=True
    )
    production_line: Mapped[str] = mapped_column(String(10), nullable=False)
    manufactured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    batch: Mapped["Batch"] = relationship("Batch", back_populates="units")
    order: Mapped[Order | None] = relationship("Order", back_populates="units")


class Ticket(Base):
    __tablename__ = "tickets"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.customer_id"), nullable=False, index=True
    )
    order_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("orders.order_id"), nullable=True, index=True
    )
    # NULL = unidade não identificada (fica fora do numerador da taxa de falha)
    serial_number: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("units.serial_number"), nullable=True, index=True
    )
    channel: Mapped[ChannelType] = mapped_column(
        SQLEnum(ChannelType, native_enum=False), nullable=False
    )
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(100), nullable=False)
    sentiment_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sentiment_label: Mapped[SentimentLabel] = mapped_column(
        SQLEnum(SentimentLabel, native_enum=False),
        nullable=False,
        default=SentimentLabel.NEUTRO,
    )
    is_health_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    batch_flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    autonomy_status: Mapped[AutonomyStatus] = mapped_column(
        SQLEnum(AutonomyStatus, native_enum=False),
        nullable=False,
        default=AutonomyStatus.AUTO_RESOLVED,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    customer: Mapped["Customer"] = relationship("Customer", back_populates="tickets")
    order: Mapped[Order | None] = relationship("Order", back_populates="tickets")


class ProactiveAlertEvent(Base):
    """Registro de um alerta proativo de recall a um pedido (substitui o booleano).

    Idempotência no banco: `UNIQUE(order_id)` garante no máximo um alerta por
    pedido; novas tentativas atualizam `attempts` em vez de criar linhas.
    Só conta como enviado com `status == delivered` (confirmação do provedor).
    """

    __tablename__ = "proactive_alert_events"
    __table_args__ = (UniqueConstraint("order_id", name="uq_alert_per_order"),)

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("orders.order_id"), nullable=False, index=True
    )
    status: Mapped[AlertStatus] = mapped_column(
        SQLEnum(AlertStatus, native_enum=False), nullable=False, default=AlertStatus.PENDING
    )
    template_id: Mapped[str] = mapped_column(
        String(100), nullable=False, doc="Template aprovado usado na mensagem (D11)"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    order: Mapped["Order"] = relationship("Order", back_populates="alert_events")


class AuditEvent(Base):
    """Trilha de auditoria por `thread_id` (princípio 6).

    Distingue interpretação do modelo, resultado de ferramenta, regra aplicada,
    decisão do código e ação executada. O payload não deve conter dados
    pessoais desnecessários.
    """

    __tablename__ = "audit_events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    kind: Mapped[AuditKind] = mapped_column(SQLEnum(AuditKind, native_enum=False), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
