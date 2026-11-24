"""Etapa 3: fábrica de LLM e chat model falso (sem rede, sem GPU)."""

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from pydantic import ValidationError

from core.config import Settings
from llm import ROLES, get_chat_model, resolve_llm_spec
from llm.testing import ScriptedChatModel, ScriptExhaustedError, tool_call


def _settings(**env) -> Settings:
    """Settings isolado do .env da máquina: só padrões + o que o teste passar."""
    return Settings(_env_file=None, **env)


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch):
    """Variáveis LLM_* do ambiente não podem vazar para os testes."""
    import os

    for key in list(os.environ):
        if key.upper().startswith("LLM_"):
            monkeypatch.delenv(key)


# ------------------------------------------------------------------ resolução
def test_defaults_follow_d20():
    spec = resolve_llm_spec(_settings(), "investigator")
    assert spec.provider == "ollama"
    assert spec.model == "qwen3:4b-instruct"
    assert spec.num_ctx == 4096
    assert spec.temperature == 0.0
    assert spec.reasoning is None
    assert spec.model_version == "ollama:qwen3:4b-instruct"


def test_role_override_from_env_inherits_the_rest(monkeypatch):
    monkeypatch.setenv("LLM_ROLES__INVESTIGATOR__MODEL", "qwen3:8b")
    monkeypatch.setenv("LLM_ROLES__JUDGE__REASONING", "true")
    s = _settings()

    investigator = resolve_llm_spec(s, "investigator")
    judge = resolve_llm_spec(s, "judge")
    generalist = resolve_llm_spec(s, "generalist")

    assert investigator.model == "qwen3:8b"
    assert investigator.num_ctx == 4096, "Campo não sobrescrito herda o global"
    assert judge.reasoning is True and judge.model == "qwen3:4b-instruct"
    assert generalist.model == "qwen3:4b-instruct"


def test_unknown_role_in_env_fails_at_startup(monkeypatch):
    """Erro de digitação no .env falha cedo, em vez de ser ignorado em silêncio."""
    monkeypatch.setenv("LLM_ROLES__INVESTIGADOR__MODEL", "qwen3:8b")
    with pytest.raises(ValidationError):
        _settings()


def test_unknown_role_in_code_is_rejected():
    with pytest.raises(ValueError, match="desconhecido"):
        resolve_llm_spec(_settings(), "supervisor")  # type: ignore[arg-type]


def test_empty_env_values_mean_unset(monkeypatch):
    monkeypatch.setenv("LLM_REASONING", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    spec = resolve_llm_spec(_settings(), "generalist")
    assert spec.reasoning is None and spec.api_key is None


def test_api_key_never_leaks_in_repr_or_dump():
    spec = resolve_llm_spec(_settings(LLM_API_KEY="sk-super-secreta"), "judge")
    assert "sk-super-secreta" not in repr(spec)
    assert "sk-super-secreta" not in str(spec.model_dump())
    assert spec.api_key.get_secret_value() == "sk-super-secreta"


def test_all_roles_resolve():
    s = _settings()
    assert {resolve_llm_spec(s, r).role for r in ROLES} == set(ROLES)


# ------------------------------------------------------------------ construção
def test_builds_ollama_client_with_spec_values():
    from langchain_ollama import ChatOllama

    s = _settings(LLM_BASE_URL="http://10.0.0.5:11434", LLM_REASONING=False)
    model = get_chat_model(s, "investigator")  # não conecta: só instancia o cliente
    assert isinstance(model, ChatOllama)
    assert model.model == "qwen3:4b-instruct"
    assert model.base_url == "http://10.0.0.5:11434"
    assert model.num_ctx == 4096 and model.temperature == 0.0
    assert model.reasoning is False


def test_switching_provider_is_configuration_only():
    pytest.importorskip("langchain_openai")
    from langchain_openai import ChatOpenAI

    s = _settings(LLM_PROVIDER="openai_compatible", LLM_BASE_URL="http://localhost:11434/v1")
    model = get_chat_model(s, "generalist")
    assert isinstance(model, ChatOpenAI)
    assert isinstance(model, BaseChatModel), "Agentes só enxergam a interface"


# ------------------------------------------------------------------ chat model falso
def test_scripted_model_returns_responses_in_order_and_records_calls():
    fake = ScriptedChatModel(responses=[AIMessage(content="um"), AIMessage(content="dois")])
    assert fake.invoke([HumanMessage(content="oi")]).content == "um"
    assert fake.invoke("de novo").content == "dois"
    assert len(fake.calls) == 2
    assert fake.calls[0][0].content == "oi"


def test_scripted_model_supports_tool_calling():
    @tool
    def check_batch_failure_rate(batch_id: str) -> str:
        """Calcula a taxa de falha de um lote."""
        return "{}"

    fake = ScriptedChatModel(
        responses=[tool_call("check_batch_failure_rate", {"batch_id": "LOTE-2026-DEF"})]
    )
    bound = fake.bind_tools([check_batch_failure_rate])
    reply = bound.invoke("Investigue o lote")

    assert reply.tool_calls[0]["name"] == "check_batch_failure_rate"
    assert reply.tool_calls[0]["args"] == {"batch_id": "LOTE-2026-DEF"}
    assert fake.tool_names == ["check_batch_failure_rate"], "Registra as ferramentas recebidas"


def test_scripted_model_fails_loudly_when_script_runs_out():
    """Um agente que chama o modelo mais vezes do que deveria é um bug visível, não silencioso."""
    fake = ScriptedChatModel(responses=[AIMessage(content="só uma")])
    fake.invoke("1")
    with pytest.raises(ScriptExhaustedError):
        fake.invoke("2")
