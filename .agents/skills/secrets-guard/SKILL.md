# Secrets Guard Skill

## Goal
Prevenir o vazamento de credenciais, chaves de API e variáveis sensíveis antes de commits ou criação de pull requests.

## Instructions
1. Inspecione todos os arquivos adicionados ou modificados (`git diff --cached`).
2. Busque por padrões de tokens (`sk-`, `ghp_`, `xoxb-`, `Bearer `, senhas hardcoded de PostgreSQL ou strings de conexão).
3. Verifique se o `.gitignore` inclui `.env`, `__pycache__/` e ambientes virtuais.

## Constraints
- Bloqueie qualquer tentativa de commit caso encontre credenciais expostas e instrua a migração para `core/config.py` via variáveis de ambiente.
