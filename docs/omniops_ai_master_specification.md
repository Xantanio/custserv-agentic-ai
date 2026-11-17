# OmniOps AI — Especificação Técnica e Arquitetura Master

> **Instrução de Contexto para o Antigravity:** Este documento contém a especificação completa de arquitetura, modelagem de dados, regras de negócio determinísticas, fluxos multi-agente (LangGraph + MCP + A2A), estratégia de dados sintéticos/mocks e definições de *Agent Skills* (`.agents/skills/`) para o projeto **OmniOps AI**. Utilize este documento como fonte única da verdade (Single Source of Truth) para estruturar, implementar e testar o repositório.

## 1. Visão Geral e Filosofia de Engenharia

O **OmniOps AI** é um microsserviço assíncrono de **Atendimento ao Cliente Omnichannel e Inteligência de Operações (Customer Service & Operations Hub)**. Ele automatiza a triagem, análise de risco, detecção preditiva de defeitos de fabricação (com comunicação proativa) e resolução de chamados vindos de múltiplos canais (**WhatsApp, E-mail e Reclame Aqui**).

### Princípios Arquiteturais Fundamentais (O "Porquê")

1. **Separação entre Probabilístico e Determinístico:**
   * **Camada Probabilística (IA / NLP):** Responsável exclusivamente por interpretar linguagem natural não estruturada, extrair entidades, classificar sentimentos e redigir respostas humanizadas, alertas proativos ou resumos executivos.
   * **Camada Determinística (Python + Pydantic v2 + SQL):** Responsável por todas as regras de negócio, cálculos estatísticos de lotes, identificação de clientes afetados sem reclamação, pontuação de prioridade por LTV, tetos financeiros e travas de segurança (*Guardrails*). O LLM **nunca** executa queries SQL diretamente nem decide sozinho estornos de alto risco.
2. **Arquitetura Híbrida de Modelos:**
   * Utiliza um classificador leve e rápido na entrada (padrão **Jev**) para triagem instantânea de intenção e sentimento, reservando LLMs maiores apenas para a etapa final de síntese e comunicação. Isso reduz latência e custos de tokens.
3. **Desacoplamento via MCP (Model Context Protocol):**
   * O acesso ao banco de dados relacional (PostgreSQL) e às ações simuladas de ERP/mensageria é isolado em um **MCP Server** dedicado. Os agentes atuam como **MCP Clients**, consumindo ferramentas padronizadas e seguras.
4. **Orquestração Estadual e A2A (Agent-to-Agent):**
   * O fluxo é governado por uma máquina de estados finitos no **LangGraph** (`StateGraph`) com persistência de *checkpoints* (`thread_id`). Agentes especializados trocam contratos estritos em Pydantic e conseguem pausar a execução (*Human-in-the-Loop*) aguardando decisão ou diagnóstico de especialistas via **Slack/Teams**.

## 2. Stack Tecnológica

* **Linguagem:** Python 3.11+
* **API & Webhooks:** FastAPI (assíncrono), Uvicorn, Pydantic v2
* **Orquestração Multi-Agente:** LangGraph (StateGraph com persistência de estado e arestas condicionais)
* **Protocolo de Ferramentas:** MCP (`mcp` Python SDK — Server e Client)
* **Classificação de Entrada:** Módulo classificador dedicado (estilo Jev / NLP estruturado)
* **Camada de Síntese LLM:** LangChain / OpenAI-compatible SDK (Llama 3.2 / GLM / GPT)
* **Banco de Dados & ORM:** PostgreSQL 16 + SQLAlchemy 2.0 (async) + AsyncPG
* **Infraestrutura & Testes:** Docker, Docker Compose, Pytest, Streamlit (UI de demonstração e simulação)

## 3. Estrutura do Repositório (`omniops-ai/`)

```text
omniops-ai/
├── .agents/
│   └── skills/
│       ├── git-commit-formatter/
│       │   └── SKILL.md
│       ├── secrets-guard/
│       │   └── SKILL.md
│       ├── pytest-debug-agent/
│       │   └── SKILL.md
│       ├── docker-health-check/
│       │   └── SKILL.md
│       └── pydantic-contract-validator/
│           └── SKILL.md
├── api/
│   ├── main.py                  # Instância FastAPI e ciclo de vida
│   ├── routes/
│   │   ├── webhooks.py          # Endpoints omnichannel (WhatsApp, E-mail, Reclame Aqui)
│   │   └── slack_callback.py    # Webhook de retorno da Central de Especialistas (A2A)
│   └── adapters/
│       └── omnichannel.py       # Normaliza payloads externos para StandardTicket
├── agents/
│   ├── state.py                 # Definição do AgentState tipado para o LangGraph
│   ├── graph.py                 # Construção do StateGraph, nós e arestas condicionais
│   ├── triage_agent.py          # Classificador estilo Jev (intenção, sentimento, risco saúde)
│   ├── quality_agent.py         # Agente preditivo de lotes e busca de clientes silenciosos (MCP)
│   ├── decision_engine.py       # Motor determinístico de LTV, prioridade, fraude e autonomia
│   ├── liaison_agent.py         # Agente A2A de comunicação com especialistas (Slack/Teams)
│   └── synthesis_agent.py       # LLM para resposta empática e alertas proativos a clientes
├── mcp_server/
│   ├── server.py                # Servidor MCP expondo ferramentas de leitura/ação operacional
│   ├── database_tools.py        # Queries seguras de clientes, pedidos e histórico
│   └── inventory_tools.py       # Cálculo de saúde de lotes, bloqueio no ERP e fila de alerta proativo
├── core/
│   ├── config.py                # Variáveis de ambiente (Pydantic Settings)
│   ├── database.py              # Engine assíncrona PostgreSQL e modelos SQLAlchemy
│   └── schemas.py               # Contratos Pydantic v2 compartilhados (A2A payloads)
├── data/
│   ├── customers.csv            # Massa sintética de clientes (VIP, Regular, New, LTV)
│   ├── batches.csv              # Massa sintética de lotes de fabricação
│   ├── orders.csv               # Massa sintética de pedidos vinculados aos lotes
│   └── historic_tickets.csv     # Tickets históricos para gerar cenários de falha de lote
├── scripts/
│   ├── seed_db.py               # Popula o PostgreSQL automaticamente a partir de data/*.csv
│   └── simulate_traffic.py      # Test Harness que dispara cenários reais nos webhooks
├── ui/
│   └── app.py                   # Interface Streamlit para simular tickets e visualizar o grafo
├── tests/
│   ├── mocks/
│   │   ├── whatsapp_health.json
│   │   ├── reclame_aqui_batch.json
│   │   └── email_vip_tracking.json
│   └── test_flows.py            # Testes de integração com pytest
├── docker-compose.yml           # Orquestra API, PostgreSQL, MCP Server e Streamlit
├── Dockerfile
├── pyproject.toml
└── README.md
```

## 4. Modelagem do Banco de Dados (PostgreSQL) & Regras Matemáticas

O banco relacional possui 4 tabelas principais que fornecem contexto histórico, financeiro e industrial aos agentes:

### 4.1. Esquema Relacional

1. **`customers` (Perfil, Fidelidade e Risco do Cliente)**
   * `customer_id` (`UUID`, PK)
   * `name` (`VARCHAR`)
   * `email` (`VARCHAR`, Unique)
   * `phone` (`VARCHAR`, Unique)
   * `tier` (`ENUM`: `'VIP'`, `'Regular'`, `'New'`)
   * `lifetime_value` (`DECIMAL(10,2)` — total histórico gasto pelo cliente)
   * `total_orders` (`INT`)
   * `return_rate` (`FLOAT` — taxa histórica de devoluções de $0.0$ a $1.0$)

2. **`batches` (Lotes de Fabricação Industrial)**
   * `batch_id` (`VARCHAR`, PK — ex: `'LOTE-2026-11-A'`)
   * `product_id` (`VARCHAR`)
   * `product_name` (`VARCHAR`)
   * `manufacturing_date` (`DATE`)
   * `factory_code` (`VARCHAR`)
   * `total_units_produced` (`INT` — total de unidades fabricadas neste lote)
   * `is_blocked` (`BOOLEAN`, default `False` — bloqueio preventivo de vendas)
   * `proactive_recall_triggered` (`BOOLEAN`, default `False` — evita disparos duplicados de alerta em massa)

3. **`orders` (Pedidos)**
   * `order_id` (`VARCHAR`, PK — ex: `'ORD-10294'`)
   * `customer_id` (`UUID`, FK $\rightarrow$ `customers.customer_id`)
   * `product_id` (`VARCHAR`)
   * `batch_id` (`VARCHAR`, FK $\rightarrow$ `batches.batch_id`)
   * `order_value` (`DECIMAL(10,2)`)
   * `carrier_status` (`ENUM`: `'in_transit'`, `'delivered_signed'`, `'delayed'`)
   * `proactive_alert_sent` (`BOOLEAN`, default `False` — indica se o cliente já foi alertado proativamente sobre defeito no lote)
   * `purchase_date` (`TIMESTAMP`)

4. **`tickets` (Chamados, Sentimento e Auditoria)**
   * `ticket_id` (`UUID`, PK)
   * `thread_id` (`VARCHAR` — identificador de sessão no LangGraph para retomada)
   * `customer_id` (`UUID`, FK $\rightarrow$ `customers.customer_id`)
   * `order_id` (`VARCHAR`, FK $\rightarrow$ `orders.order_id`, Nullable)
   * `channel` (`ENUM`: `'whatsapp'`, `'email'`, `'reclame_aqui'`)
   * `message_text` (`TEXT`)
   * `intent` (`VARCHAR` — ex: `'defective_item'`, `'shipping_delay'`, `'health_issue'`, `'refund_request'`)
   * `sentiment_score` (`FLOAT` — escala contínua de $-1.0$ a $1.0$)
   * `sentiment_label` (`ENUM`: `'Positivo'`, `'Neutro'`, `'Negativo'`, `'Extremamente Negativo'`)
   * `is_health_risk` (`BOOLEAN`, default `False`)
   * `batch_flagged` (`BOOLEAN`, default `False`)
   * `priority_score` (`INT` — escala de $0$ a $100$)
   * `autonomy_status` (`ENUM`: `'auto_resolved'`, `'human_in_the_loop'`, `'escalated_specialist'`)
   * `created_at` (`TIMESTAMP`)

### 4.2. Fórmulas Determinísticas de Negócio

#### A. Taxa de Falha Preditiva de Lote e Ação Proativa
Sempre que um chamado tiver `intent == 'defective_item'`, o **Agente Preditivo de Lotes** consulta o MCP Server e calcula:

$$
\text{Taxa de Reclamação do Lote} = \frac{\text{Total de Tickets com Defeito no } \text{batch\_id}}{\text{Total de Unidades Produzidas no } \text{batch\_id}}
$$

* **Regra Crítica ($\ge 50\%$):** Quando $\text{Taxa de Reclamação do Lote} \ge 0.50$ ($50\%$), o sistema executa três ações coordenadas:
  1. **Contenção Industrial e Comercial:** Marca `batch_flagged = True` no ticket e bloqueia novas vendas daquele lote no ERP (`batches.is_blocked = True`).
  2. **Alerta Proativo aos Clientes Silenciosos:** Consulta via MCP todos os pedidos (`orders`) vinculados àquele `batch_id` cujos clientes **ainda não abriram reclamação** (`proactive_alert_sent == False` e sem ticket de defeito aberto). O sistema dispara notificações proativas (WhatsApp/E-mail) avisando sobre a possível falha detectada no lote e oferecendo troca preventiva ou reembolso sem burocracia, marcando `proactive_alert_sent = True`.
  3. **Acionamento de Especialistas para Causa Raiz:** Aciona o **Agente de Enlace Interno (`liaison_agent.py`)** enviando os metadados de produção (`batch_id`, `factory_code`, `manufacturing_date`, `product_id` e amostra dos defeitos relatados) para que a equipe de engenharia/qualidade investigue **o que causou o problema no lote** e valide ações corretivas na fábrica.

#### B. Score de Priorização do Cliente (`priority_score`)
Calculado deterministicamente de $0$ a $100$ para ordenar filas e definir urgência:

$$
\text{priority\_score} = \min\Big(100,\; W_{\text{tier}} + W_{\text{ltv}} + W_{\text{sentimento}} + W_{\text{canal}}\Big)
$$

* $W_{\text{tier}}$: `'VIP'` $= +35$, `'Regular'` $= +15$, `'New'` $= +5$.
* $W_{\text{ltv}}$: $+15$ se $\text{lifetime\_value} \ge 1500.00$, senão $+0$.
* $W_{\text{sentimento}}$: $+25$ se $\text{sentiment\_score} \le -0.7$, $+10$ se $\text{sentiment\_score} < 0$.
* $W_{\text{canal}}$: `'reclame_aqui'` $= +25$ (exposição pública), `'whatsapp'` $= +10$, `'email'` $= +5$.

## 5. Ingestão Omnichannel e Validação sem Empresa Real

Para validar toda a arquitetura em ambiente de desenvolvimento e portfólio sem depender de tráfego real de uma empresa, utilizamos uma **Camada de Normalização** acoplada a um **Simulador de Tráfego (Test Harness)**:

1. **Adapters de Ingestão (`api/adapters/omnichannel.py`):** Convertem os payloads específicos de cada webhook para um único schema interno `StandardTicket`:
   * **WhatsApp:** Estilo *Evolution API / Meta Cloud API* (`data.key.remoteJid`, `data.message.conversation`).
   * **E-mail:** Estilo *SendGrid Inbound Parse* (`from`, `subject`, `text`).
   * **Reclame Aqui:** Payload estruturado de monitoramento público (`consumer_username`, `title`, `complaint_body`).
2. **Seed Sintético (`scripts/seed_db.py`):** Popula o PostgreSQL no boot do Docker com cenários pré-fabricados (ex: `LOTE-2026-DEF` já com $49\%$ de reclamações registradas e outros clientes desse mesmo lote que ainda não reclamaram, de modo que o próximo ticket de defeito dispare exatamente o gatilho de $\ge 50\%$, o alerta proativo aos clientes silenciosos e o chamado ao especialista).
3. **Test Harness (`scripts/simulate_traffic.py`) & UI Streamlit (`ui/app.py`):** Permite enviar payloads reais de teste com 1 clique e inspecionar a transição de estados do LangGraph, os alertas proativos disparados e o relatório enviado aos especialistas.

## 6. Fluxo Multi-Agente (LangGraph), MCP e A2A

```text
[Canais: WhatsApp | E-mail | Reclame Aqui]
                    │
                    ▼
   [FastAPI Adapter -> StandardTicket]
                    │
                    ▼
  ┌───────────────────────────────────┐
  │ 1. Triage & Sentiment Agent (Jev) │
  │  - Extrai intent & entities       │
  │  - Calcula sentiment_score        │
  │  - Detecta is_health_risk         │
  └─────────────────┬─────────────────┘
                    │
         ┌──────────┴──────────┐
         ▼ (is_health_risk)    ▼ (Fluxo Padrão)
 [HARD STOP: Saúde]   ┌────────────────────────────────────┐
  - Acolhimento seguro│ 2. Predictive Batch Agent (MCP)    │
  - Alerta Máximo A2A │  - Consulta SQL via MCP Server     │
                      │  - Calcula Taxa de Defeito do Lote │
                      └─────────────────┬──────────────────┘
                                        │
                                        ▼
                      ┌────────────────────────────────────┐
                      │ 3. Customer & Risk Engine (Python) │
                      │  - Calcula priority_score (LTV)    │
                      │  - Checa fraude / teto financeiro  │
                      └─────────────────┬──────────────────┘
                                        │
                     ┌──────────────────┼──────────────────┐
                     ▼                  ▼                  ▼
           [Autonomia Total]   [Lote >= 50% Falha] [HITL Obrigatório]
           - Rastreio / VIP    - Auto-reembolso    - Fraude / Alto Valor
           - Resposta LLM      - Alerta Clientes   - Pausa StateGraph
                                 Silenciosos (Batch)
                               - Alerta Especialista
                                 (Causa Raiz)
                                       │
                                       ▼
                        [4. Internal Liaison Agent]
                         - Envia Dossiê Técnico ao Slack
                         - Especialista diagnostica causa
                         - Retoma thread_id / recall no ERP
```

### 6.1. Matriz de Autonomia e Guardrails

#### Situações de Autonomia Total (Zero Toque Humano)
* **Rastreio e Dúvidas de Entrega:** Consulta o status via MCP e responde ao cliente com o código de rastreio.
* **Contenção e Alerta Proativo por Lote Defeituoso ($\ge 50\%$):** Quando a falha industrial atinge o limiar crítico, o sistema bloqueia o lote no ERP, resolve o reembolso/troca do cliente reclamante (se houver bom histórico) e **dispara alertas preventivos autônomos** para todos os demais compradores daquele mesmo lote que ainda não reclamaram, enquanto aciona o especialista em paralelo para investigação da causa raiz.
* **Fast-Track VIP de Baixo Risco:** Cliente `'VIP'` com `return_rate < 0.10` e valor do pedido $\le \text{R\$ } 100,00$ recebe crédito/reenvio automático.

#### Situações de Bloqueio de Autonomia (Human-in-the-Loop Obrigatório)
1. **Reclamações de Saúde, Alergia ou Segurança Física (`is_health_risk == True`):**
   * *Ação:* **Hard Stop** imediato. O agente envia apenas uma resposta padrão prudente e acolhedora (sem assumir culpa jurídica antecipada), congela a automação e aciona a equipe de Qualidade/Médica/Jurídica com prioridade máxima.
2. **Investigação de Causa Raiz e Recall Formal de Lote ($\ge 50\%$):**
   * *Ação:* Embora o alerta preventivo ao cliente e o bloqueio de venda ocorram automaticamente, o encerramento da investigação industrial e a ordem formal de *recall* exigem o diagnóstico do especialista humano acionado via A2A.
3. **Suspeita de Fraude ou Contradição Logística:**
   * *Ação:* Cliente `'New'` com alta taxa de devolução histórica ou alegação de "caixa vazia" quando a transportadora registra `delivered_signed`.
4. **Alto Impacto Financeiro:**
   * *Ação:* Pedidos ou estornos acima de $\text{R\$ } 500,00$ exigem aprovação explícita de um supervisor.
5. **Sentimento Extremamente Negativo ($\le -0.8$) ou Ameaças Judiciais:**
   * *Ação:* Menções a Procon, processos ou hostilidade severa bloqueiam respostas automáticas genéricas e transferem o caso para atendimento humano prioritário.

### 6.2. Central de Especialistas (Comunicação A2A via Slack/Teams)

Quando o **Agente Preditivo** detecta um lote crítico ($\ge 50\%$) ou surge um caso de saúde, o **Agente de Enlace Interno (`liaison_agent.py`)** monta um payload A2A estruturado e publica um **Dossiê Técnico de Investigação** no canal privado de operações/engenharia (Slack/Teams) contendo:

* Canal de origem, resumo dos sintomas/defeitos relatados e `batch_id` afetado.
* Dados industriais para **análise de causa raiz**: código da fábrica (`factory_code`), data de fabricação (`manufacturing_date`), linha do produto (`product_id`), volume produzido vs. taxa de reclamações.
* Relatório de contenção já executada: confirmação do bloqueio de vendas do lote e contagem de **clientes silenciosos do lote que acabaram de receber o alerta proativo**.
* Botões/comandos de retorno (ex: `"Registrar causa raiz e confirmar recall do lote LOTE-2026-11-A"`). Ao receber o webhook de resposta do especialista, o FastAPI valida o token, registra o diagnóstico técnico e retoma a execução do LangGraph (`graph.ainvoke(None, config={"configurable": {"thread_id": ...}})`).

## 7. Antigravity Custom Skills (`.agents/skills/`)

Crie os seguintes arquivos dentro de `.agents/skills/` no repositório para automatizar boas práticas de engenharia durante o desenvolvimento no Antigravity:

### 7.1. `.agents/skills/git-commit-formatter/SKILL.md`

```markdown
# Git Commit Formatter Skill

## Goal
Analisar modificações pendentes no repositório (`git status` e `git diff`), gerar mensagens de commit no padrão *Conventional Commits* e executar o commit com segurança.

## Instructions
1. Execute `git status` e `git diff --cached` (ou `git diff`) para inspecionar o escopo das alterações.
2. Classifique a mudança em: `feat`, `fix`, `refactor`, `docs`, `test` ou `chore`.
3. Formate a mensagem como: `<tipo>(<escopo>): <descrição curta no imperativo>`.
4. Execute `git add` nos arquivos pertinentes e realize `git commit -m "..."`.

## Constraints
- Nunca execute `git push` sem autorização explícita do usuário.
- Se detectar `.env` ou chaves de API nos arquivos modificados, aborte imediatamente e alerte o usuário.
```

### 7.2. `.agents/skills/secrets-guard/SKILL.md`

```markdown
# Secrets Guard Skill

## Goal
Prevenir o vazamento de credenciais, chaves de API e variáveis sensíveis antes de commits ou criação de pull requests.

## Instructions
1. Inspecione todos os arquivos adicionados ou modificados (`git diff --cached`).
2. Busque por padrões de tokens (`sk-`, `ghp_`, `xoxb-`, `Bearer `, senhas hardcoded de PostgreSQL ou strings de conexão).
3. Verifique se o `.gitignore` inclui `.env`, `__pycache__/` e ambientes virtuais.

## Constraints
- Bloqueie qualquer tentativa de commit caso encontre credenciais expostas e instrua a migração para `core/config.py` via variáveis de ambiente.
```

### 7.3. `.agents/skills/pydantic-contract-validator/SKILL.md`

```markdown
# Pydantic Contract Validator Skill

## Goal
Garantir integridade e tipagem estrita nos contratos Pydantic v2 trocados entre os webhooks FastAPI, o MCP Server e os nós A2A do LangGraph.

## Instructions
1. Ao criar ou alterar schemas em `core/schemas.py` ou `agents/state.py`, verifique se todos os campos possuem type hints explícitos, validadores (`Field`) e valores padrão seguros.
2. Garanta compatibilidade com Pydantic v2 (`model_dump()`, `model_validate()`), evitando sintaxe depreciada da v1 (`.dict()`, `.parse_obj()`).
```

### 7.4. `.agents/skills/pytest-debug-agent/SKILL.md`

```markdown
# Pytest Debug Agent Skill

## Goal
Executar a suíte de testes automatizados, diagnosticar falhas e propor correções cirúrgicas.

## Instructions
1. Rode `pytest -v` no terminal.
2. Em caso de falha, leia o traceback completo, identifique se o erro ocorreu no motor determinístico, nos mocks omnichannel ou na máquina de estados do LangGraph.
3. Corrija o código mantendo a separação entre regras determinísticas e chamadas LLM, e reexecute `pytest` até que todos os testes passem.
```

### 7.5. `.agents/skills/docker-health-check/SKILL.md`

```markdown
# Docker Health Check Skill

## Goal
Garantir que todo o ambiente (FastAPI, PostgreSQL, MCP Server e Streamlit) suba de forma limpa e reproduzível com `docker compose up --build`.

## Instructions
1. Verifique o `docker-compose.yml` para garantir `depends_on` com `healthcheck` no PostgreSQL antes da execução do `scripts/seed_db.py` e da API.
2. Valide se todas as portas expostas e variáveis de ambiente estão documentadas no `.env.example`.
```

## 8. Roteiro de Implementação Sugerido (Execution Plan)

Ao iniciar o desenvolvimento deste projeto no Antigravity, siga esta ordem incremental:

1. **Fase 1 (Infraestrutura & Dados):** Criar `docker-compose.yml`, `core/database.py` (incluindo flags de controle de alerta proativo nos lotes e pedidos), os arquivos sintéticos em `data/*.csv` e o script `scripts/seed_db.py`.
2. **Fase 2 (MCP Server):** Implementar `mcp_server/server.py` expondo as ferramentas de consulta de cliente, pedido, cálculo de taxa de falha de lote e busca de clientes sem reclamação do lote afetado.
3. **Fase 3 (Motores Determinísticos & Triagem):** Implementar `agents/triage_agent.py` (classificador estilo Jev) e `agents/decision_engine.py` (cálculo de prioridade LTV, fraude e regras de saúde/lote).
4. **Fase 4 (Orquestração LangGraph, Proatividade & A2A):** Construir `agents/graph.py` com persistência de estado, disparo de alertas proativos aos clientes silenciosos do lote ($\ge 50\%$), *Hard Stop* de saúde e envio de dossiê técnico de causa raiz ao especialista (`agents/liaison_agent.py`).
5. **Fase 5 (Omnichannel, Mocks & UI):** Criar os adapters em `api/adapters/omnichannel.py`, os JSONs em `tests/mocks/`, a suíte `pytest` e o painel interativo em `ui/app.py` (Streamlit).