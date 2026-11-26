import uuid
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Any, Dict, Literal, Optional, List
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.database import (
    AlertStatus,
    AuditKind,
    CustomerTier,
    CarrierStatus,
    ChannelType,
    SentimentLabel,
    AutonomyStatus,
)

# Formato do número de série (D10): SN-<SIGLA>-<6 dígitos>, ex.: SN-SW-000123.
SERIAL_PATTERN = r"^SN-[A-Z]{2,4}-\d{6}$"


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
    """Saída de `calculate_batch_failure_rate` (CLAUDE.md 6.2).

    A taxa conta UNIDADES distintas identificadas; reclamações sem serial e com
    serial inconsistente aparecem à parte (a taxa pode subestimar a incidência real).
    """

    found: bool = True
    batch_id: str
    product_id: str
    product_name: str
    factory_code: str
    manufacturing_date: date
    total_units_produced: int = Field(..., gt=0)
    defective_units_count: int = Field(..., ge=0, description="Numerador: seriais distintos do lote")
    defective_tickets_count: int = Field(..., ge=0, description="Tickets de defeito brutos (transparência)")
    unidentified_complaints_count: int = Field(
        ..., ge=0, description="Reclamações do lote sem serial: fora do numerador"
    )
    inconsistent_serial_complaints_count: int = Field(
        ..., ge=0, description="Serial de outro pedido/lote: fora do numerador, vai para HITL"
    )
    failure_rate: float = Field(..., ge=0.0, le=1.0)
    critical_threshold: float
    is_critical: bool = Field(description="True se taxa >= limiar (policy_config)")
    rule_id: str
    is_blocked: bool
    proactive_recall_triggered: bool
    silent_orders_count: int = Field(
        default=0, ge=0, description="Pedidos do lote elegíveis ao alerta proativo (por pedido)"
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
    carrier: str = Field(..., max_length=50, description="Transportadora responsável pela entrega")
    purchase_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OrderCreate(OrderBase):
    pass


class OrderRead(OrderBase):
    pass


# -----------------------------------------------------------------------------
# Unit Schemas (D6)
# -----------------------------------------------------------------------------
class UnitBase(BaseSchema):
    serial_number: str = Field(..., pattern=SERIAL_PATTERN)
    batch_id: str = Field(..., max_length=100)
    product_id: str = Field(..., max_length=100)
    order_id: Optional[str] = Field(default=None, description="NULL = unidade ainda em estoque")
    production_line: str = Field(..., max_length=10)
    manufactured_at: datetime


class UnitRead(UnitBase):
    pass


# -----------------------------------------------------------------------------
# Ticket Schemas
# -----------------------------------------------------------------------------
class TicketBase(BaseSchema):
    thread_id: str
    customer_id: uuid.UUID
    order_id: Optional[str] = None
    serial_number: Optional[str] = Field(
        default=None,
        pattern=SERIAL_PATTERN,
        description="NULL = unidade não identificada (fora do numerador da taxa)",
    )
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
class ProactiveAlertEventRead(BaseSchema):
    event_id: uuid.UUID
    order_id: str
    status: AlertStatus
    template_id: str
    attempts: int = Field(..., ge=0)
    provider_message_id: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    delivered_at: Optional[datetime] = None


class AuditEventCreate(BaseSchema):
    thread_id: str = Field(..., min_length=1, max_length=100)
    kind: AuditKind
    payload: Dict[str, Any] = Field(default_factory=dict)
    model_version: Optional[str] = None
    rule_id: Optional[str] = None


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


# -----------------------------------------------------------------------------
# Investigação de causa raiz (CLAUDE.md 8.2; D26-D28)
# -----------------------------------------------------------------------------
Confidence = Literal["baixa", "media", "alta"]
StopReason = Literal[
    "final_answer",      # o modelo concluiu sozinho
    "max_steps",         # limite de chamadas ao modelo no laço
    "repeated_calls",    # insistiu em repetir chamadas idênticas
    "context_budget",    # entrada perto do num_ctx (o Ollama cortaria o começo em silêncio)
    "timeout",           # tempo total esgotado
    "invalid_output",    # relatório fora do esquema mesmo após 1 nova tentativa
    "model_error",       # falha ao chamar o modelo (rede, servidor)
]


class Hypothesis(BaseSchema):
    """Uma hipótese de causa, com as evidências que a sustentam (escrita pelo modelo)."""

    description: str = Field(..., min_length=5, max_length=400)
    evidence: List[str] = Field(
        ..., min_length=1, max_length=5, description="Números e fatos vindos das ferramentas"
    )
    confidence: Confidence


class InvestigationDraft(BaseSchema):
    """O que o MODELO escreve no fim da investigação. Metadados ficam com o código."""

    root_cause_identified: bool = Field(
        ..., description="true só se as evidências apontam uma causa com clareza"
    )
    hypotheses: List[Hypothesis] = Field(
        default_factory=list, max_length=3, description="Da mais para a menos provável"
    )
    unknowns: List[str] = Field(default_factory=list, max_length=5)
    recommended_checks: List[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _identified_needs_hypothesis(self) -> "InvestigationDraft":
        if self.root_cause_identified and not self.hypotheses:
            raise ValueError("root_cause_identified=true exige ao menos uma hipótese")
        return self


class ToolCallRecord(BaseSchema):
    """Registro de uma chamada de ferramenta, feito pelo CÓDIGO (não pelo modelo)."""

    name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "error", "rejected", "repeated"]


class InvestigationReport(InvestigationDraft):
    """Relatório final: conteúdo do modelo + metadados confiáveis do código.

    Tudo aqui é HIPÓTESE para o especialista validar; nunca dispara recall.
    """

    batch_id: str
    thread_id: str
    stop_reason: StopReason
    steps: int = Field(..., ge=0, description="Chamadas ao modelo no laço de investigação")
    tools_called: List[ToolCallRecord] = Field(default_factory=list)
    finalize_attempts: int = Field(default=0, ge=0, le=2)
    model_version: str
    duration_seconds: float = Field(..., ge=0)

    @property
    def is_indeterminate(self) -> bool:
        return not self.root_cause_identified
