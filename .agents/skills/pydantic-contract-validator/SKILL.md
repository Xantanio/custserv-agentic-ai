# Pydantic Contract Validator Skill

## Goal
Garantir integridade e tipagem estrita nos contratos Pydantic v2 trocados entre os webhooks FastAPI, o MCP Server e os nós A2A do LangGraph.

## Instructions
1. Ao criar ou alterar schemas em `core/schemas.py` ou `agents/state.py`, verifique se todos os campos possuem type hints explícitos, validadores (`Field`) e valores padrão seguros.
2. Garanta compatibilidade com Pydantic v2 (`model_dump()`, `model_validate()`), evitando sintaxe depreciada da v1 (`.dict()`, `.parse_obj()`).
