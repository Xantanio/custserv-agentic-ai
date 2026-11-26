"""Etapa 5: laço do agente investigador, com dublê de modelo e ferramentas falsas.

Sem GPU, sem banco, sem MCP. Verifica o CÓDIGO do agente (laço, limites,
menor privilégio, saída estruturada, auditoria), não a qualidade do modelo:
essa é medida pela avaliação da Etapa 6, com o LLM real.
"""

import asyncio
import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool, ToolException

from agents.investigator import PROMPT_VERSION, Investigator
from core.audit import InMemoryAuditSink
from core.database import AuditKind
from core.schemas import InvestigationDraft
from llm.testing import ScriptedChatModel, ScriptExhaustedError, structured_reply, tool_call
from mcp_server.investigation_tools import INVESTIGATOR_TOOLS

BATCH = "LOTE-2026-DEF"

GOOD_DRAFT = {
    "root_cause_identified": True,
    "hypotheses": [{
        "description": "Defeito concentrado na linha de produção L2 (bateria estufada)",
        "evidence": ["L2: taxa 0,90 contra 0,08 na L1", "No lote de setembro a L2 tinha 0,02"],
        "confidence": "alta",
    }],
    "unknowns": ["Qual etapa da linha L2 mudou entre setembro e outubro"],
    "recommended_checks": ["Inspecionar o processo de montagem da bateria na L2"],
}
# Inválido: diz que identificou a causa mas não traz hipótese (model_validator recusa)
BAD_DRAFT = {"root_cause_identified": True, "hypotheses": []}

FAKE_RESULTS = {
    "check_batch_failure_rate": {"failure_rate": 0.49, "defective_units_count": 49},
    "defect_rate_by": {"groups": [{"group": "L2", "defect_rate": 0.9}, {"group": "L1", "defect_rate": 0.08}]},
    "compare_factory_batches": {"batches": []},
    "complaint_timeline": {"weeks": []},
    "search_symptoms": {"matching_units": 34},
    "sample_defect_complaints": {"complaints": []},
}
_SCHEMA = {
    "type": "object",
    "properties": {
        "batch_id": {"type": "string"},
        "dimension": {"type": "string"},
        "term": {"type": "string"},
        "limit": {"type": "integer"},
    },
    "required": ["batch_id"],
}


class FakeTools:
    """Ferramentas falsas com os nomes reais; registram cada EXECUÇÃO."""

    def __init__(self, names=INVESTIGATOR_TOOLS, overrides: dict[str, Any] | None = None):
        self.executed: list[tuple[str, dict]] = []
        self.tools = [self._make(n, (overrides or {}).get(n, FAKE_RESULTS.get(n, {}))) for n in names]

    def _make(self, name: str, behavior: Any) -> StructuredTool:
        async def _run(**kwargs):
            self.executed.append((name, kwargs))
            if isinstance(behavior, Exception):
                raise behavior
            if callable(behavior):
                return await behavior(**kwargs)
            return json.dumps(behavior, ensure_ascii=False)

        return StructuredTool(name=name, description=f"{name} (teste)", args_schema=_SCHEMA, coroutine=_run)


def _agent(responses: list[AIMessage], tools: FakeTools | None = None, **kwargs):
    fake = ScriptedChatModel(responses=responses)
    tools = tools or FakeTools()
    audit = InMemoryAuditSink()
    agent = Investigator(fake, tools.tools, audit=audit, model_version="fake:scripted", **kwargs)
    return agent, fake, tools, audit


# ------------------------------------------------------------------ caminho feliz
async def test_happy_path_investigates_and_reports():
    agent, fake, tools, _ = _agent([
        tool_call("check_batch_failure_rate", {"batch_id": BATCH}, "c1"),
        tool_call("defect_rate_by", {"batch_id": BATCH, "dimension": "production_line"}, "c2"),
        AIMessage(content="A linha L2 concentra os defeitos: 0,90 contra 0,08."),
        structured_reply(InvestigationDraft, GOOD_DRAFT),
    ])
    report = await agent.investigate(BATCH)

    assert report.stop_reason == "final_answer"
    assert report.root_cause_identified and "L2" in report.hypotheses[0].description
    assert report.steps == 3, "Três chamadas ao modelo no laço"
    assert [(t.name, t.status) for t in report.tools_called] == [
        ("check_batch_failure_rate", "ok"), ("defect_rate_by", "ok"),
    ]
    assert len(tools.executed) == 2
    assert report.finalize_attempts == 1
    assert report.model_version == "fake:scripted" and report.batch_id == BATCH


async def test_tool_results_are_fed_back_to_the_model():
    agent, fake, _, _ = _agent([
        tool_call("defect_rate_by", {"batch_id": BATCH, "dimension": "production_line"}, "c1"),
        AIMessage(content="Conclusão."),
        structured_reply(InvestigationDraft, GOOD_DRAFT),
    ])
    await agent.investigate(BATCH)

    second_call = fake.calls[1]
    tool_messages = [m for m in second_call if isinstance(m, ToolMessage)]
    assert tool_messages and '"L2"' in tool_messages[0].content
    assert tool_messages[0].tool_call_id == "c1"


# ------------------------------------------------------------------ menor privilégio
async def test_only_investigator_tools_are_bound_to_the_model():
    agent, fake, _, _ = _agent([AIMessage(content="ok"), structured_reply(InvestigationDraft, GOOD_DRAFT)])
    await agent.investigate(BATCH)
    assert fake.binding_history[0] == list(INVESTIGATOR_TOOLS)
    assert fake.all_bound_tool_names <= set(INVESTIGATOR_TOOLS) | {"InvestigationDraft"}


def test_agent_refuses_to_start_with_a_write_tool():
    tools = FakeTools(names=[*INVESTIGATOR_TOOLS, "block_batch"])
    with pytest.raises(ValueError, match="block_batch"):
        Investigator(ScriptedChatModel(responses=[]), tools.tools)
    with pytest.raises(ValueError):
        Investigator(ScriptedChatModel(responses=[]), [])


async def test_unknown_tool_requested_by_model_is_never_executed():
    """Ex.: prompt injection num resultado induz o modelo a pedir 'block_batch'."""
    agent, _, tools, _ = _agent([
        tool_call("block_batch", {"batch_id": BATCH}, "c1"),
        AIMessage(content="Sem conclusão."),
        structured_reply(InvestigationDraft, GOOD_DRAFT),
    ])
    report = await agent.investigate(BATCH)
    assert tools.executed == []
    assert report.tools_called[0].status == "rejected"


# ------------------------------------------------------------------ limites de autonomia
async def test_repeated_calls_are_not_executed_and_stop_the_loop():
    same = {"batch_id": BATCH, "dimension": "carrier"}
    agent, _, tools, _ = _agent(
        [tool_call("defect_rate_by", same, f"c{i}") for i in range(3)]
        + [structured_reply(InvestigationDraft, GOOD_DRAFT)],
        max_repeats=2,
    )
    report = await agent.investigate(BATCH)
    assert report.stop_reason == "repeated_calls"
    assert len(tools.executed) == 1, "Só a primeira foi executada"
    assert [t.status for t in report.tools_called] == ["ok", "repeated", "repeated"]


async def test_step_limit_forces_finalize():
    dims = ["production_line", "carrier", "purchase_week"]
    agent, fake, _, _ = _agent(
        [tool_call("defect_rate_by", {"batch_id": BATCH, "dimension": d}, f"c{i}") for i, d in enumerate(dims)]
        + [structured_reply(InvestigationDraft, GOOD_DRAFT)],
        max_steps=3,
    )
    report = await agent.investigate(BATCH)
    assert report.stop_reason == "max_steps"
    assert report.steps == 3
    assert len(fake.calls) == 4, "3 no laço + 1 no finalize; a 4ª volta ao laço não chama o modelo"


async def test_context_budget_stops_before_overflow():
    near_limit = AIMessage(
        content="",
        tool_calls=[{"name": "defect_rate_by", "args": {"batch_id": BATCH, "dimension": "carrier"},
                     "id": "c1", "type": "tool_call"}],
        usage_metadata={"input_tokens": 3900, "output_tokens": 20, "total_tokens": 3920},
    )
    agent, _, tools, _ = _agent([near_limit, structured_reply(InvestigationDraft, GOOD_DRAFT)])
    report = await agent.investigate(BATCH)
    assert report.stop_reason == "context_budget"
    assert tools.executed == [], "Com o contexto no limite, a chamada pendente é descartada"


async def test_timeout_returns_indeterminate_report():
    async def slow(**_):
        await asyncio.sleep(2)
        return "{}"

    tools = FakeTools(overrides={"defect_rate_by": slow})
    agent, _, _, _ = _agent(
        [tool_call("check_batch_failure_rate", {"batch_id": BATCH}, "c1"),
         tool_call("defect_rate_by", {"batch_id": BATCH, "dimension": "carrier"}, "c2")],
        tools=tools, timeout_seconds=0.3,
    )
    report = await agent.investigate(BATCH)
    assert report.stop_reason == "timeout"
    assert report.is_indeterminate
    assert [t.name for t in report.tools_called] == ["check_batch_failure_rate"], "O que terminou fica registrado"


# ------------------------------------------------------------------ erros
async def test_tool_error_is_returned_to_the_model_and_loop_continues():
    tools = FakeTools(overrides={"defect_rate_by": ToolException("dimension inválida. Use production_line, carrier...")})
    agent, fake, _, _ = _agent(
        [tool_call("defect_rate_by", {"batch_id": BATCH, "dimension": "fabrica"}, "c1"),
         AIMessage(content="Conclusão."),
         structured_reply(InvestigationDraft, GOOD_DRAFT)],
        tools=tools,
    )
    report = await agent.investigate(BATCH)
    assert report.tools_called[0].status == "error"
    error_msg = [m for m in fake.calls[1] if isinstance(m, ToolMessage)][0].content
    assert error_msg.startswith("ERRO") and "production_line" in error_msg
    assert report.stop_reason == "final_answer"


async def test_model_failure_gives_indeterminate_report_without_crashing():
    agent, _, _, _ = _agent([])  # o 1º invoke levanta ScriptExhaustedError, como uma falha de rede
    report = await agent.investigate(BATCH)
    assert report.stop_reason == "model_error"
    assert report.is_indeterminate and report.steps == 0


# ------------------------------------------------------------------ saída estruturada
async def test_invalid_report_is_retried_once():
    agent, _, _, _ = _agent([
        AIMessage(content="Conclusão."),
        structured_reply(InvestigationDraft, BAD_DRAFT),
        structured_reply(InvestigationDraft, GOOD_DRAFT),
    ])
    report = await agent.investigate(BATCH)
    assert report.finalize_attempts == 2
    assert report.root_cause_identified and report.stop_reason == "final_answer"


async def test_invalid_report_twice_gives_indeterminate_instead_of_inventing():
    agent, _, _, _ = _agent([
        AIMessage(content="Conclusão."),
        structured_reply(InvestigationDraft, BAD_DRAFT),
        structured_reply(InvestigationDraft, BAD_DRAFT),
    ])
    report = await agent.investigate(BATCH)
    assert report.stop_reason == "invalid_output"
    assert report.is_indeterminate and report.hypotheses == []
    assert "indeterminada" in report.unknowns[0].lower()


# ------------------------------------------------------------------ auditoria
async def test_every_tool_call_and_the_report_are_audited():
    agent, _, _, audit = _agent([
        tool_call("check_batch_failure_rate", {"batch_id": BATCH}, "c1"),
        tool_call("block_batch", {"batch_id": BATCH}, "c2"),
        AIMessage(content="Conclusão."),
        structured_reply(InvestigationDraft, GOOD_DRAFT),
    ])
    report = await agent.investigate(BATCH, thread_id="thread-xyz")

    kinds = [e.kind for e in audit.events]
    assert kinds == [AuditKind.TOOL_RESULT, AuditKind.TOOL_RESULT, AuditKind.MODEL_INTERPRETATION]
    assert {e.thread_id for e in audit.events} == {"thread-xyz"} == {report.thread_id}
    assert all(e.model_version == "fake:scripted" for e in audit.events)
    assert audit.events[1].payload["status"] == "rejected", "Tentativas recusadas também ficam registradas"
    assert audit.events[-1].payload["prompt_version"] == PROMPT_VERSION


def test_script_exhausted_is_a_loud_failure_in_the_double():
    with pytest.raises(ScriptExhaustedError):
        ScriptedChatModel(responses=[]).invoke("x")
