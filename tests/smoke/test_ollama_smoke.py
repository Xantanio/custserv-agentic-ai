"""Smoke test opcional contra o Ollama real (D13, D19). Rode com: pytest -m ollama -s

Não faz parte da suíte padrão (lento, depende de GPU/rede). Usa a configuração
real da máquina (.env), papel `investigator`.
"""

import time

import httpx
import pytest
from langchain_core.tools import tool

from core.config import Settings
from llm import get_chat_model, resolve_llm_spec
from llm.factory import build_chat_model

pytestmark = pytest.mark.ollama


@tool
def check_batch_failure_rate(batch_id: str) -> str:
    """Calcula a taxa de falha de um lote de fabricação pelo ID do lote (ex.: LOTE-2026-DEF)."""
    return "{}"


QUESTION = "Qual é a taxa de falha do lote LOTE-2026-DEF? Use a ferramenta."


@pytest.fixture(scope="module")
def settings():
    s = Settings()
    spec = resolve_llm_spec(s, "investigator")
    if spec.provider == "ollama":
        try:
            httpx.get(f"{spec.base_url}/api/tags", timeout=5).raise_for_status()
        except httpx.HTTPError as exc:
            pytest.skip(f"Ollama indisponível em {spec.base_url}: {exc}")
    return s


def _timed(callable_):
    start = time.perf_counter()
    result = callable_()
    return result, time.perf_counter() - start


def test_plain_answer_without_reasoning_leak(settings):
    model = get_chat_model(settings, "investigator")
    reply, seconds = _timed(lambda: model.invoke("Responda só com a palavra: ok"))
    print(f"\n[texto] {seconds:.1f}s -> {reply.content!r}")
    assert "ok" in reply.content.lower()
    assert "<think>" not in reply.content, "Raciocínio vazando no conteúdo (ver D20)"


def test_native_ollama_tool_calling(settings):
    model = get_chat_model(settings, "investigator").bind_tools([check_batch_failure_rate])
    reply, seconds = _timed(lambda: model.invoke(QUESTION))
    print(f"\n[tools/nativo] {seconds:.1f}s -> {reply.tool_calls}")
    assert reply.tool_calls, f"O modelo não chamou ferramenta: {reply.content!r}"
    assert reply.tool_calls[0]["name"] == "check_batch_failure_rate"
    assert reply.tool_calls[0]["args"].get("batch_id") == "LOTE-2026-DEF"


def test_openai_compatible_endpoint_tool_calling(settings):
    """Mesmo modelo, outro caminho: a troca de provedor é só configuração (D13)."""
    pytest.importorskip("langchain_openai")
    spec = resolve_llm_spec(settings, "investigator")
    if spec.provider != "ollama":
        pytest.skip("Comparação só faz sentido quando o provedor padrão é o Ollama")
    v1 = spec.model_copy(update={"provider": "openai_compatible", "base_url": f"{spec.base_url}/v1"})
    model = build_chat_model(v1).bind_tools([check_batch_failure_rate])
    reply, seconds = _timed(lambda: model.invoke(QUESTION))
    print(f"\n[tools/v1] {seconds:.1f}s -> {reply.tool_calls}")
    assert reply.tool_calls and reply.tool_calls[0]["args"].get("batch_id") == "LOTE-2026-DEF"
