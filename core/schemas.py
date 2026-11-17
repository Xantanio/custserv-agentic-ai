import uuid
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field

from core.database import (
    CustomerTier,
    CarrierStatus,
    ChannelType,
    SentimentLabel,
    AutonomyStatus,
)


# -----------------------------------------------------------------------------
# Base Pydantic v2 Schema
# -----------------------------------------------------------------------------
class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# -----------------------------------------------------------------------------
# Standard Ticket (Omnichannel Normalized Input)
# -----------------------------------------------------------------------------
class StandardTicket(BaseSchema):
    ticket_id: uuid.UUID = Field(
        default_factory=uuid.uuid4, description="ID único do ticket"
    )
    thread_id: str = Field(
        ..., description="Identificador único da conversa / sessão LangGraph"
    )
    customer_id: Optional[uuid.UUID] = Field(
        default=None, description="UUID do cliente caso já identificado"
    )
    order_id: Optional[str] = Field(
        default=None, description="ID do pedido relacionado, se informado"
    )
    channel: ChannelType = Field(
        ..., description="Canal de entrada (whatsapp, email, reclame_aqui)"
    )
    customer_name: Optional[str] = Field(
        default=None, description="Nome do remetente obtido no canal"
    )
    customer_email: Optional[str] = Field(
        default=None, description="Email do cliente para lookup"
    )
    customer_phone: Optional[str] = Field(
        default=None, description="Telefone do cliente para lookup (formato E.164 ou similar)"
    )
    raw_message: str = Field(
        ..., min_length=1, description="Texto original não estruturado da mensagem"
    )
    subject: Optional[str] = Field(
        default=None, description="Assunto (usado primariamente em E-mails e Reclame Aqui)"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="Data/hora de ingestão"
    )


# -----------------------------------------------------------------------------
# Customer Schemas
# -----------------------------------------------------------------------------
class CustomerBase(BaseSchema):
    name: str = Field(..., max_length=255)
    email: str = Field(..., max_length=255)
    phone: str = Field(..., max_length=50)
    tier: CustomerTier = Field(default=CustomerTier.REGULAR)
    lifetime_value: Decimal = Field(default=Decimal("0.00"), ge=0)
    total_orders: int = Field(default=0, ge=0)
    return_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class CustomerCreate(CustomerBase):
    customer_id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4)


class CustomerRead(CustomerBase):
    customer_id: uuid.UUID


# -----------------------------------------------------------------------------
# Batch Schemas
# -----------------------------------------------------------------------------
class BatchBase(BaseSchema):
    batch_id: str = Field(..., max_length=100)
    product_id: str = Field(..., max_length=100)
    product_name: str = Field(..., max_length=255)
    manufacturing_date: date
    factory_code: str = Field(..., max_length=50)
    total_units_produced: int = Field(..., gt=0)
    is_blocked: bool = Field(default=False)
    proactive_recall_triggered: bool = Field(default=False)


class BatchCreate(BatchBase):
    pass


class BatchRead(BatchBase):
    pass


class BatchFailureMetrics(BaseSchema):
    batch_id: str
    product_id: str
    product_name: str
    total_units_produced: int
    defective_tickets_count: int
    failure_rate: float
    is_critical: bool = Field(
        description="True se taxa de defeitos >= 0.50 (50%)"
    )
    silent_customers_count: int = Field(
        default=0, description="Total de clientes que compraram o lote e ainda não reclamaram"
    )


# -----------------------------------------------------------------------------
# Order Schemas
# -----------------------------------------------------------------------------
class OrderBase(BaseSchema):
    order_id: str = Field(..., max_length=100)
    customer_id: uuid.UUID
    product_id: str = Field(..., max_length=100)
    batch_id: str = Field(..., max_length=100)
    order_value: Decimal = Field(..., ge=0)
    carrier_status: CarrierStatus = Field(default=CarrierStatus.IN_TRANSIT)
    proactive_alert_sent: bool = Field(default=False)
    purchase_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OrderCreate(OrderBase):
    pass


class OrderRead(OrderBase):
    pass


# -----------------------------------------------------------------------------
# Ticket Schemas
# -----------------------------------------------------------------------------
class TicketBase(BaseSchema):
    thread_id: str
    customer_id: uuid.UUID
    order_id: Optional[str] = None
    channel: ChannelType
    message_text: str
    intent: str
    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    sentiment_label: SentimentLabel = Field(default=SentimentLabel.NEUTRO)
    is_health_risk: bool = Field(default=False)
    batch_flagged: bool = Field(default=False)
    priority_score: int = Field(default=0, ge=0, le=100)
    autonomy_status: AutonomyStatus = Field(default=AutonomyStatus.AUTO_RESOLVED)


class TicketCreate(TicketBase):
    ticket_id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4)


class TicketRead(TicketBase):
    ticket_id: uuid.UUID
    created_at: datetime


# -----------------------------------------------------------------------------
# Proactive Alert & Liaison A2A Schemas
# -----------------------------------------------------------------------------
class ProactiveAlertPayload(BaseSchema):
    customer_id: uuid.UUID
    customer_name: str
    customer_email: str
    customer_phone: str
    order_id: str
    batch_id: str
    product_name: str
    channel: ChannelType
    alert_message: str


class SpecialistDossierPayload(BaseSchema):
    batch_id: str
    factory_code: str
    manufacturing_date: date
    product_id: str
    product_name: str
    total_units_produced: int
    defective_tickets_count: int
    failure_rate: float
    reported_symptoms_sample: List[str] = Field(default_factory=list)
    is_blocked: bool
    silent_customers_alerted: int
    thread_id: str
    urgency: str = Field(default="CRÍTICA", description="Nível de urgência para a engenharia")
    recommendation: str = Field(
        default="Investigar linha de montagem e confirmar ordem formal de recall"
    )
