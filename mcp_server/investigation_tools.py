"""Ferramentas de investigação de causa raiz (CLAUDE.md 8.2): só leitura, agregadas, sem PII.

Desenho voltado a modelos pequenos (D19, D24):
* poucas ferramentas, nomes claros, argumentos simples (`dimension` é enumerada);
* respostas COMPACTAS (agregados, números com 3 casas, trechos truncados);
* taxas já normalizadas pela base de cada grupo: o LLM interpreta, não calcula;
* texto livre de cliente sempre passa por `mask_pii`;
* erros devolvem mensagem útil para o modelo se corrigir (ex.: valores válidos).

Uma unidade conta como defeituosa pela mesma regra da taxa do lote (D22):
ticket `defective_item` com o serial dela e pedido compatível (ou sem pedido).
"""

from typing import Any, Awaitable, Callable, Literal, Optional, get_args

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, Batch, Order, Ticket, Unit
from core.privacy import mask_pii
from mcp_server.inventory_tools import DEFECT_INTENT, calculate_batch_failure_rate

# Lista FECHADA de ferramentas do investigador (menor privilégio). Nenhuma escreve
# no banco nem devolve contato de cliente; `find_silent_customers` fica de fora.
INVESTIGATOR_TOOLS: tuple[str, ...] = (
    "check_batch_failure_rate",
    "defect_rate_by",
    "compare_factory_batches",
    "complaint_timeline",
    "search_symptoms",
    "sample_defect_complaints",
)

Dimension = Literal["production_line", "manufacturing_day", "carrier", "purchase_week"]
DIMENSIONS: tuple[str, ...] = get_args(Dimension)
# Transportadora e semana de compra só existem para unidades vendidas.
_SALES_DIMENSIONS = {"carrier", "purchase_week"}

MAX_SNIPPET_CHARS = 160
MAX_SAMPLE = 8  # 10 amostras estouravam o orçamento de ~1.500 caracteres (teste de orçamento)


async def _with_session(session: Optional[AsyncSession], fn: Callable[[AsyncSession], Awaitable[Any]]):
    if session:
        return await fn(session)
    async with AsyncSessionLocal() as s:
        return await fn(s)


def _not_found(batch_id: str) -> dict[str, Any]:
    return {"found": False, "error": f"Lote {batch_id!r} não encontrado. Confira o batch_id (ex.: LOTE-2026-DEF)."}


def _unit_is_defective():
    """EXISTS correlacionado: a unidade tem reclamação de defeito válida (regra D22)."""
    return (
        exists()
        .where(
            Ticket.serial_number == Unit.serial_number,
            Ticket.intent == DEFECT_INTENT,
            or_(Ticket.order_id.is_(None), Ticket.order_id.is_not_distinct_from(Unit.order_id)),
        )
        .correlate(Unit)
    )


def _group_key(dimension: str):
    return {
        "production_line": Unit.production_line,
        "manufacturing_day": func.to_char(func.timezone("UTC", Unit.manufactured_at), "YYYY-MM-DD"),
        "carrier": Order.carrier,
        "purchase_week": func.to_char(func.timezone("UTC", Order.purchase_date), 'IYYY-"W"IW'),
    }[dimension]


def _week(column):
    return func.to_char(func.timezone("UTC", column), 'IYYY-"W"IW')


def _related_defect_tickets(batch_id: str):
    """Tickets de defeito ligados ao lote pelo pedido OU pelo serial."""
    return (
        select(Ticket)
        .outerjoin(Order, Ticket.order_id == Order.order_id)
        .outerjoin(Unit, Ticket.serial_number == Unit.serial_number)
        .where(Ticket.intent == DEFECT_INTENT)
        .where(or_(Order.batch_id == batch_id, Unit.batch_id == batch_id))
    )


def _snippet(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    text = mask_pii(" ".join(text.split()))
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _rates(s: AsyncSession, batch_id: str, dimension: str) -> list[dict[str, Any]]:
    key = _group_key(dimension).label("group")
    defective = func.count().filter(_unit_is_defective())
    stmt = (
        select(key, func.count().label("units"), defective.label("defective"))
        .select_from(Unit)
        .outerjoin(Order, Unit.order_id == Order.order_id)
        .where(Unit.batch_id == batch_id)
        .group_by(key)
    )
    if dimension in _SALES_DIMENSIONS:
        stmt = stmt.where(Unit.order_id.is_not(None))
    rows = (await s.execute(stmt)).all()
    groups = [
        {"group": g, "units": u, "defective_units": d, "defect_rate": round(d / u, 3) if u else 0.0}
        for g, u, d in rows
    ]
    return sorted(groups, key=lambda x: (-x["defect_rate"], x["group"]))


async def defect_rate_by(
    batch_id: str, dimension: str, session: Optional[AsyncSession] = None
) -> dict[str, Any]:
    """Taxa de defeito do lote quebrada por uma dimensão, normalizada pela base de cada grupo."""

    async def _q(s: AsyncSession) -> dict[str, Any]:
        if dimension not in DIMENSIONS:
            return {"found": False, "error": f"dimension inválida: {dimension!r}. Use uma de: {', '.join(DIMENSIONS)}."}
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return _not_found(batch_id)
        totals = await calculate_batch_failure_rate(batch.batch_id, session=s)
        base = "unidades vendidas" if dimension in _SALES_DIMENSIONS else "unidades produzidas"
        return {
            "found": True,
            "batch_id": batch.batch_id,
            "dimension": dimension,
            "base": base,
            "groups": await _rates(s, batch.batch_id, dimension),
            "unattributed_complaints": totals["unidentified_complaints_count"]
            + totals["inconsistent_serial_complaints_count"],
            "note": f"defect_rate = unidades defeituosas / {base} do grupo. Compare taxas, não contagens.",
        }

    return await _with_session(session, _q)


async def compare_factory_batches(batch_id: str, session: Optional[AsyncSession] = None) -> dict[str, Any]:
    """Lotes da mesma fábrica, em ordem de fabricação: taxa geral e por linha de produção."""

    async def _q(s: AsyncSession) -> dict[str, Any]:
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return _not_found(batch_id)
        siblings = (
            await s.execute(
                select(Batch)
                .where(Batch.factory_code == batch.factory_code)
                .order_by(Batch.manufacturing_date, Batch.batch_id)
            )
        ).scalars().all()
        result = []
        for b in siblings:
            lines = await _rates(s, b.batch_id, "production_line")
            defective = sum(g["defective_units"] for g in lines)
            result.append({
                "batch_id": b.batch_id,
                "is_target": b.batch_id == batch.batch_id,
                "product_id": b.product_id,
                "manufacturing_date": b.manufacturing_date.isoformat(),
                "units": b.total_units_produced,
                "defective_units": defective,
                "defect_rate": round(defective / b.total_units_produced, 3),
                "defect_rate_by_line": {g["group"]: g["defect_rate"] for g in sorted(lines, key=lambda g: g["group"])},
            })
        return {"found": True, "factory_code": batch.factory_code, "batches": result}

    return await _with_session(session, _q)


async def complaint_timeline(batch_id: str, session: Optional[AsyncSession] = None) -> dict[str, Any]:
    """Reclamações de defeito por semana ISO e quantas unidades foram reclamadas pela 1ª vez."""

    async def _q(s: AsyncSession) -> dict[str, Any]:
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return _not_found(batch_id)
        related = _related_defect_tickets(batch.batch_id).subquery()
        week = _week(related.c.created_at).label("week")
        complaints = dict(
            (await s.execute(select(week, func.count()).group_by(week))).all()
        )
        first_report = (
            select(Ticket.serial_number, func.min(Ticket.created_at).label("first_at"))
            .join(Unit, Ticket.serial_number == Unit.serial_number)
            .where(Unit.batch_id == batch.batch_id, Ticket.intent == DEFECT_INTENT)
            .where(or_(Ticket.order_id.is_(None), Ticket.order_id.is_not_distinct_from(Unit.order_id)))
            .group_by(Ticket.serial_number)
            .subquery()
        )
        fweek = _week(first_report.c.first_at).label("week")
        new_units = dict((await s.execute(select(fweek, func.count()).group_by(fweek))).all())
        weeks = sorted(set(complaints) | set(new_units))
        return {
            "found": True,
            "batch_id": batch.batch_id,
            "weeks": [
                {"week": w, "complaints": complaints.get(w, 0), "new_defective_units": new_units.get(w, 0)}
                for w in weeks
            ],
        }

    return await _with_session(session, _q)


async def search_symptoms(batch_id: str, term: str, session: Optional[AsyncSession] = None) -> dict[str, Any]:
    """Quantas reclamações/unidades do lote citam um termo, por linha, com até 3 trechos mascarados."""

    async def _q(s: AsyncSession) -> dict[str, Any]:
        clean = " ".join(term.split())
        if not 2 <= len(clean) <= 40:
            return {"found": False, "error": "term deve ter entre 2 e 40 caracteres (ex.: 'estufada')."}
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return _not_found(batch_id)
        escaped = clean.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        matches = (
            await s.execute(
                _related_defect_tickets(batch.batch_id)
                .add_columns(Unit.production_line, Unit.batch_id.label("unit_batch"))
                .where(Ticket.message_text.ilike(f"%{escaped}%", escape="\\"))
                .order_by(Ticket.created_at)
            )
        ).all()
        units_by_line: dict[str, set[str]] = {}
        for ticket, line, unit_batch in matches:
            if ticket.serial_number and unit_batch == batch.batch_id:
                units_by_line.setdefault(line, set()).add(ticket.serial_number)
        return {
            "found": True,
            "batch_id": batch.batch_id,
            "term": clean,
            "matching_complaints": len(matches),
            "matching_units": sum(len(v) for v in units_by_line.values()),
            "matching_units_by_line": {k: len(v) for k, v in sorted(units_by_line.items())},
            "examples": [
                {"line": line, "text": _snippet(ticket.message_text)} for ticket, line, _ in matches[:3]
            ],
            "note": "Busca literal, sem diferenciar maiúsculas; não ignora acentos.",
        }

    return await _with_session(session, _q)


async def sample_defect_complaints(
    batch_id: str, limit: int = 5, session: Optional[AsyncSession] = None
) -> dict[str, Any]:
    """Amostra das reclamações de defeito mais recentes do lote (texto mascarado e truncado)."""

    async def _q(s: AsyncSession) -> dict[str, Any]:
        batch = await s.get(Batch, batch_id.strip())
        if not batch:
            return _not_found(batch_id)
        n = max(1, min(int(limit), MAX_SAMPLE))
        rows = (
            await s.execute(
                _related_defect_tickets(batch.batch_id)
                .add_columns(Unit.production_line)
                .order_by(Ticket.created_at.desc(), Ticket.ticket_id)
                .limit(n)
            )
        ).all()
        return {
            "found": True,
            "batch_id": batch.batch_id,
            "complaints": [
                {
                    "date": t.created_at.date().isoformat(),
                    "channel": t.channel.value,
                    "line": line,
                    "text": _snippet(t.message_text),
                }
                for t, line in rows
            ],
        }

    return await _with_session(session, _q)
