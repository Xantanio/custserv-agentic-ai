# Docker Health Check Skill

## Goal
Garantir que todo o ambiente (FastAPI, PostgreSQL, MCP Server e Streamlit) suba de forma limpa e reproduzível com `docker compose up --build`.

## Instructions
1. Verifique o `docker-compose.yml` para garantir `depends_on` com `healthcheck` no PostgreSQL antes da execução do `scripts/seed_db.py` e da API.
2. Valide se todas as portas expostas e variáveis de ambiente estão documentadas no `.env.example`.
