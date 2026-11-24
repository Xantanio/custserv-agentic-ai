"""Chat model falso e determinístico para testes de agentes (sem rede, sem GPU).

Os falsos do LangChain não implementam `bind_tools`, de que todo agente com
ferramentas precisa. `ScriptedChatModel` devolve, em ordem, as respostas
roteirizadas (inclusive `tool_calls`) e REGISTRA o que recebeu, para os testes
verificarem o comportamento do agente: quais mensagens enviou, quais
ferramentas lhe foram dadas (menor privilégio), quantas vezes chamou o modelo.
"""

from typing import Any, Callable, Optional, Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field


class ScriptExhaustedError(RuntimeError):
    """O agente chamou o modelo mais vezes do que o roteiro previa."""


def tool_call(name: str, args: dict[str, Any], call_id: Optional[str] = None) -> AIMessage:
    """Atalho: resposta do modelo pedindo uma chamada de ferramenta."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id or f"call_{name}", "type": "tool_call"}],
    )


class ScriptedChatModel(BaseChatModel):
    """Devolve `responses` em ordem; esgotado o roteiro, levanta `ScriptExhaustedError`."""

    responses: list[AIMessage]
    model_name: str = "scripted-fake"
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    @property
    def tool_names(self) -> list[str]:
        return [t["function"]["name"] for t in self.bound_tools]

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable | BaseTool],
        **kwargs: Any,
    ) -> "ScriptedChatModel":
        """Registra as ferramentas e devolve o PRÓPRIO objeto (o roteiro e o registro são compartilhados)."""
        self.bound_tools = [convert_to_openai_tool(t) for t in tools]
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        index = len(self.calls) - 1
        if index >= len(self.responses):
            raise ScriptExhaustedError(
                f"Chamada nº {index + 1} ao modelo, mas o roteiro tem {len(self.responses)} respostas"
            )
        return ChatResult(generations=[ChatGeneration(message=self.responses[index])])
