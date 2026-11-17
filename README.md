# OmniOps AI — Customer Service & Operations Hub

OmniOps AI é um microsserviço assíncrono de Atendimento ao Cliente Omnichannel e Inteligência de Operações. Ele automatiza triagem, análise de risco, detecção preditiva de defeitos de fabricação (com comunicação proativa para compradores silenciosos) e resolução de chamados oriundos de **WhatsApp, E-mail e Reclame Aqui**.

---

## 🏗️ Arquitetura

1. **Separação Probabilístico vs. Determinístico:**
   - **Camada Probabilística (LLM / NLP):** Interpretação não estruturada, extração de entidades/intenções e síntese de respostas empáticas.
   - **Camada Determinística (Python + Pydantic v2 + SQL):** Regras de negócio, cálculo de taxa de falha de lotes ($\ge 50\%$), score de prioridade por LTV, guardrails de fraude e tetos financeiros.
2. **Desacoplamento via MCP (Model Context Protocol):**
   - Ferramentas de acesso a dados (clientes, pedidos, lotes) isoladas no `mcp_server`.
3. **Orquestração LangGraph:**
   - Grafo de estados com persistência (`thread_id`), Human-in-the-Loop (HITL) e integração A2A com especialistas (Slack/Teams).

---

## 🚀 Como Executar

### 1. Clonar e configurar ambiente
```bash
cp .env.example .env
```

### 2. Executar via Docker Compose
```bash
docker compose up --build
```

Serviços iniciados:
- **API FastAPI & Webhooks:** `http://localhost:8000`
- **MCP Server:** `http://localhost:8001`
- **Streamlit UI:** `http://localhost:8501`
- **PostgreSQL 16:** `localhost:5432`

---

## 🧪 Estrutura de Diretórios

- `.agents/skills/`: Skills de suporte a boas práticas (commits, segredos, contratos pydantic, testes e health check).
- `api/`: Rotas de webhooks omnichannel, adaptadores e callbacks.
- `agents/`: Nós LangGraph (Triage, Quality/Batch, Decision Engine, Liaison, Synthesis).
- `core/`: Configurações de ambiente, modelos SQLAlchemy e contratos Pydantic v2.
- `data/`: Datasets sintéticos (`batches.csv`, `customers.csv`, `orders.csv`, `historic_tickets.csv`).
- `mcp_server/`: Servidor e ferramentas MCP.
- `scripts/`: Seed do banco de dados e simulador de tráfego (Test Harness).
- `ui/`: Dashboard Streamlit para demonstração interativa.
- `tests/`: Suíte de testes automatizados com mocks de webhooks.
