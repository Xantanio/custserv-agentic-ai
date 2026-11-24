"""Etapa 4: ferramentas de investigação (CLAUDE.md 8.2, D24) sobre os dados do seed.

Verifica: o sinal plantado (L2) aparece; os distratores são mais fracos que ele;
as respostas cabem no orçamento de contexto; não há PII; nada é escrito no banco.
"""

import json

import pytest
from sqlalchemy import select, text

from core.database import ChannelType, Order, Ticket
from mcp_server import investigation_tools as it
from mcp_server.inventory_tools import calculate_batch_failure_rate
from scripts.seed_db import seed

pytestmark = pytest.mark.integration

DEF = "LOTE-2026-DEF"
SEP = "LOTE-2026-SEP"
# Orçamento por resposta: ~1.500 caracteres ≈ 400 tokens (contexto de 4.096, D20).
MAX_RESPONSE_CHARS = 1500


@pytest.fixture
async def s(db_session):
    await seed(db_session)
    return db_session


def _by_group(result: dict) -> dict[str, dict]:
    return {g["group"]: g for g in result["groups"]}


async def _all_investigator_calls(s) -> dict[str, dict]:
    """Uma chamada de cada ferramenta do investigador (e todas as dimensões)."""
    calls = {"check_batch_failure_rate": await calculate_batch_failure_rate(DEF, session=s)}
    for d in it.DIMENSIONS:
        calls[f"defect_rate_by:{d}"] = await it.defect_rate_by(DEF, d, session=s)
    calls["compare_factory_batches"] = await it.compare_factory_batches(DEF, session=s)
    calls["complaint_timeline"] = await it.complaint_timeline(DEF, session=s)
    calls["search_symptoms"] = await it.search_symptoms(DEF, "estufada", session=s)
    calls["sample_defect_complaints"] = await it.sample_defect_complaints(DEF, limit=10, session=s)
    return calls


# ------------------------------------------------------------------ sinal plantado
async def test_production_line_reveals_planted_cause(s):
    r = await it.defect_rate_by(DEF, "production_line", session=s)
    lines = _by_group(r)
    assert r["groups"][0]["group"] == "L2", "Grupo de maior taxa vem primeiro"
    assert lines["L2"]["defect_rate"] >= 0.85 and lines["L1"]["defect_rate"] <= 0.10
    assert lines["L2"]["units"] == lines["L1"]["units"] == 50
    assert r["unattributed_complaints"] == 1, "Reclamação sem serial é sinalizada, não escondida"


async def test_distractors_are_much_weaker_than_the_cause(s):
    """Transportadora e semana de compra variam por ruído de amostra pequena, muito menos que a linha."""
    lines = _by_group(await it.defect_rate_by(DEF, "production_line", session=s))
    line_gap = lines["L2"]["defect_rate"] - lines["L1"]["defect_rate"]
    for dimension in ("carrier", "purchase_week", "manufacturing_day"):
        rates = [g["defect_rate"] for g in (await it.defect_rate_by(DEF, dimension, session=s))["groups"]]
        assert max(rates) - min(rates) < line_gap / 1.2, dimension

    carriers = _by_group(await it.defect_rate_by(DEF, "carrier", session=s))
    most_defects = max(carriers.values(), key=lambda g: g["defective_units"])
    highest_rate = max(carriers.values(), key=lambda g: g["defect_rate"])
    assert most_defects["group"] == "RotaSul", "Maior contagem bruta: armadilha de taxa-base"
    assert highest_rate["group"] != "RotaSul", "...mas não a maior taxa"


async def test_sales_dimensions_use_sold_units_as_base(s):
    r = await it.defect_rate_by(DEF, "carrier", session=s)
    assert r["base"] == "unidades vendidas"
    assert sum(g["units"] for g in r["groups"]) == 85, "Só as 85 unidades vendidas do lote"


async def test_compare_factory_batches_shows_l2_was_healthy_before(s):
    r = await it.compare_factory_batches(DEF, session=s)
    batches = {b["batch_id"]: b for b in r["batches"]}
    assert [b["batch_id"] for b in r["batches"]] == [SEP, DEF], "Ordem de fabricação"
    assert batches[DEF]["is_target"] and not batches[SEP]["is_target"]
    assert batches[SEP]["defect_rate_by_line"]["L2"] <= 0.05
    assert batches[DEF]["defect_rate_by_line"]["L2"] >= 0.85
    assert batches[DEF]["defective_units"] == 49, "Coerente com a taxa oficial do lote"


async def test_complaint_timeline_is_consistent_with_batch_rate(s):
    r = await it.complaint_timeline(DEF, session=s)
    weeks = [w["week"] for w in r["weeks"]]
    assert weeks == sorted(weeks)
    assert sum(w["complaints"] for w in r["weeks"]) == 51, "Todos os tickets, inclusive repetidos"
    assert sum(w["new_defective_units"] for w in r["weeks"]) == 49, "Cada unidade conta na 1ª semana"


async def test_search_symptoms_points_to_l2(s):
    r = await it.search_symptoms(DEF, "ESTUFADA", session=s)
    assert r["matching_units"] >= 30
    assert set(r["matching_units_by_line"]) == {"L2"}
    assert r["matching_complaints"] >= r["matching_units"], "Repetições contam como reclamação, não como unidade"
    assert len(r["examples"]) <= 3


async def test_search_treats_wildcards_literally(s):
    assert (await it.search_symptoms(DEF, "a%b", session=s))["matching_complaints"] == 0
    assert (await it.search_symptoms(DEF, "%", session=s))["found"] is False, "Termo curto demais"


# ------------------------------------------------------------------ erros úteis ao modelo
async def test_invalid_dimension_lists_valid_options(s):
    r = await it.defect_rate_by(DEF, "factory", session=s)
    assert r["found"] is False
    assert all(d in r["error"] for d in it.DIMENSIONS)


async def test_unknown_batch_is_reported_not_raised(s):
    for coro in (
        it.defect_rate_by("LOTE-X", "carrier", session=s),
        it.compare_factory_batches("LOTE-X", session=s),
        it.complaint_timeline("LOTE-X", session=s),
        it.search_symptoms("LOTE-X", "tela", session=s),
        it.sample_defect_complaints("LOTE-X", session=s),
    ):
        r = await coro
        assert r["found"] is False and "LOTE-X" in r["error"]


async def test_sample_limit_is_capped(s):
    r = await it.sample_defect_complaints(DEF, limit=500, session=s)
    assert len(r["complaints"]) == it.MAX_SAMPLE


# ------------------------------------------------------------------ orçamento e privacidade
async def test_every_response_fits_the_context_budget(s):
    for name, result in (await _all_investigator_calls(s)).items():
        size = len(json.dumps(result, ensure_ascii=False))
        assert size <= MAX_RESPONSE_CHARS, f"{name}: {size} caracteres"


async def test_customer_free_text_is_masked(s):
    order = await s.get(Order, "ORD-20051")
    s.add(Ticket(
        thread_id="pii-test", customer_id=order.customer_id, order_id="ORD-20051",
        channel=ChannelType.EMAIL, intent="defective_item",
        message_text="A tela apagou. Me liguem no (11) 98765-4321 ou ana.souza@example.com, CPF 123.456.789-09",
    ))
    await s.commit()

    newest = (await it.sample_defect_complaints(DEF, limit=1, session=s))["complaints"][0]["text"]
    assert "[TELEFONE]" in newest and "[EMAIL]" in newest and "[CPF]" in newest
    found = await it.search_symptoms(DEF, "apagou", session=s)
    assert "@" not in json.dumps(found)
    for name, result in (await _all_investigator_calls(s)).items():
        dumped = json.dumps(result, ensure_ascii=False)
        assert "@" not in dumped and "98765" not in dumped, name


# ------------------------------------------------------------------ somente leitura
async def _snapshot(s) -> dict[str, str]:
    tables = ["batches", "customers", "orders", "units", "tickets", "proactive_alert_events", "audit_events"]
    out = {}
    for t in tables:
        out[t] = (await s.execute(text(
            f"SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {t} x"
        ))).scalar_one()
    return out


async def test_investigator_tools_never_write(s):
    before = await _snapshot(s)
    await _all_investigator_calls(s)
    assert await _snapshot(s) == before


def test_investigator_toolset_is_closed_and_small():
    assert len(it.INVESTIGATOR_TOOLS) <= 6
    assert "find_silent_customers" not in it.INVESTIGATOR_TOOLS, "Devolve contato de cliente"
    assert not {"block_batch", "queue_alerts"} & set(it.INVESTIGATOR_TOOLS)
