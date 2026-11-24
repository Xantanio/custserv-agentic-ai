"""Camada de LLM modular (D13): fábrica por papel e chat model falso para testes."""

from llm.factory import ROLES, LLMRole, LLMSpec, get_chat_model, resolve_llm_spec

__all__ = ["ROLES", "LLMRole", "LLMSpec", "get_chat_model", "resolve_llm_spec"]
