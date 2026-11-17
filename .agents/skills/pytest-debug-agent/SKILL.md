# Pytest Debug Agent Skill

## Goal
Executar a suíte de testes automatizados, diagnosticar falhas e propor correções cirúrgicas.

## Instructions
1. Rode `pytest -v` no terminal.
2. Em caso de falha, leia o traceback completo, identifique se o erro ocorreu no motor determinístico, nos mocks omnichannel ou na máquina de estados do LangGraph.
3. Corrija o código mantendo a separação entre regras determinísticas e chamadas LLM, e reexecute `pytest` até que todos os testes passem.
