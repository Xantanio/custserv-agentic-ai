"""Fábrica de chat models (D13): o código de agentes depende só de `BaseChatModel`.

Duas fases, para testar a configuração sem instanciar nada:

1. `resolve_llm_spec(settings, role)` -> `LLMSpec`: função pura que combina os
   valores globais `LLM_*` com a sobrescrita do papel (`LLM_ROLES__<PAPEL>__*`).
2. `get_chat_model(settings, role)` -> `BaseChatModel`: constrói o cliente do provedor.

Trocar de provedor é configuração (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`,
`LLM_API_KEY`), nunca código. Agentes recebem o modelo por injeção de dependência;
esta fábrica só é chamada na borda (scripts, API).
"""

from typing import Callable, Optional, get_args

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from core.config import LLMProvider, LLMRoleName, Settings

LLMRole = LLMRoleName
ROLES: tuple[str, ...] = get_args(LLMRoleName)


class LLMSpec(BaseModel):
    """Configuração resolvida de um papel. `api_key` é `SecretStr`: não vaza em logs."""

    model_config = ConfigDict(frozen=True)

    role: LLMRoleName
    provider: LLMProvider
    base_url: str
    model: str
    api_key: Optional[SecretStr] = None
    temperature: float = Field(ge=0.0, le=2.0)
    num_ctx: int = Field(gt=0)
    reasoning: Optional[bool] = None
    timeout_seconds: float = Field(gt=0)

    @property
    def model_version(self) -> str:
        """Identificador para a auditoria (princípio 6), ex.: `ollama:qwen3:4b-instruct`."""
        return f"{self.provider}:{self.model}"


def resolve_llm_spec(settings: Settings, role: LLMRoleName) -> LLMSpec:
    """Combina os valores globais com a sobrescrita do papel (campo ausente herda o global)."""
    if role not in ROLES:
        raise ValueError(f"Papel de LLM desconhecido: {role!r}. Válidos: {', '.join(ROLES)}")
    override = settings.LLM_ROLES.get(role)
    o = override.model_dump(exclude_none=True) if override else {}
    return LLMSpec(
        role=role,
        provider=o.get("provider", settings.LLM_PROVIDER),
        base_url=o.get("base_url", settings.LLM_BASE_URL),
        model=o.get("model", settings.LLM_MODEL),
        api_key=o.get("api_key", settings.LLM_API_KEY),
        temperature=o.get("temperature", settings.LLM_TEMPERATURE),
        num_ctx=o.get("num_ctx", settings.LLM_NUM_CTX),
        reasoning=o.get("reasoning", settings.LLM_REASONING),
        timeout_seconds=o.get("timeout_seconds", settings.LLM_TIMEOUT_SECONDS),
    )


def _build_ollama(spec: LLMSpec) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=spec.model,
        base_url=spec.base_url,
        temperature=spec.temperature,
        num_ctx=spec.num_ctx,
        reasoning=spec.reasoning,
        client_kwargs={"timeout": spec.timeout_seconds},
    )


def _build_openai_compatible(spec: LLMSpec) -> BaseChatModel:
    """API compatível com OpenAI (externa, ou o próprio Ollama em `<base_url>/v1`).

    Import tardio: `langchain-openai` é um extra opcional (`pip install -e ".[openai]"`).
    `num_ctx` e `reasoning` são conceitos do Ollama e não se aplicam aqui.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            "LLM_PROVIDER=openai_compatible exige o extra opcional: pip install -e \".[openai]\""
        ) from exc

    # O SDK da OpenAI exige uma chave; servidores locais aceitam qualquer valor.
    api_key = spec.api_key or SecretStr("not-needed")
    return ChatOpenAI(
        model=spec.model,
        base_url=spec.base_url,
        api_key=api_key,
        temperature=spec.temperature,
        timeout=spec.timeout_seconds,
    )


_BUILDERS: dict[str, Callable[[LLMSpec], BaseChatModel]] = {
    "ollama": _build_ollama,
    "openai_compatible": _build_openai_compatible,
}


def build_chat_model(spec: LLMSpec) -> BaseChatModel:
    try:
        builder = _BUILDERS[spec.provider]
    except KeyError:  # pragma: no cover - o Literal já barra na configuração
        raise ValueError(f"Provedor de LLM sem implementação: {spec.provider!r}") from None
    return builder(spec)


def get_chat_model(settings: Settings, role: LLMRoleName) -> BaseChatModel:
    """Ponto de entrada: devolve o chat model configurado para o papel."""
    return build_chat_model(resolve_llm_spec(settings, role))
