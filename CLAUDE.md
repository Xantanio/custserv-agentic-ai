# CLAUDE.md — OmniOps AI

Fonte única da verdade deste repositório. Leia inteiro antes de qualquer tarefa. Este arquivo **substitui** a antiga `omniops_ai_master_specification.md` (D18): tudo o que era essencial nela está aqui, já atualizado com as decisões posteriores.

## 0. Modo de trabalho (IMPORTANTE)

Projeto **didático e de portfólio**. O dono quer se tornar **engenheiro de IA** e usa o projeto para entender a arquitetura de sistemas de agentes e multiagentes.

- **Antes de começar qualquer alteração**, apresente: (1) a lista de arquivos que serão criados ou alterados; (2) o trade-off escolhido; (3) as alternativas descartadas e por quê. Só então edite.
- **Explique o porquê**, não só o quê. Antes de cada etapa, diga em poucas linhas qual conceito ela ensina e qual alternativa foi descartada. Depois, resuma o que mudou e por que o design é assim.
- **Ciclo de cada componente: implementar → fazer funcionar → medir → melhorar.** Nada de pular a medição: todo componente com modelo (classificador, agente, juiz) tem uma avaliação (eval) com casos conhecidos.
- Quando houver trade-off real, apresente as opções e recomende uma, em vez de decidir em silêncio. Decisões de **produto simulado** (valores, formatos, nomes) podem ser tomadas por você, registrando-as aqui.
- Não avance para a etapa seguinte sem os testes da etapa atual passando.
- Nunca faça `git push` sem autorização explícita. Siga as skills em `.agents/skills/`.
- Responda em **português do Brasil**. Identificadores de código em inglês; docstrings e comentários em português.

## 1. O que é o projeto

Microsserviço assíncrono de **atendimento omnichannel e inteligência de operações**. Recebe chamados de **WhatsApp, e-mail e Reclame Aqui**, faz triagem e análise de risco, **detecta defeitos de fabricação por lote** (com contenção e alerta proativo a compradores que ainda não reclamaram), investiga a causa provável e resolve ou escala chamados.

Para validar sem tráfego real, usa uma camada de normalização (adapters) e um simulador de tráfego (test harness) com dados sintéticos.

## 2. Princípios arquiteturais (não violar)

1. **Probabilístico ≠ determinístico.** Modelos e LLMs interpretam linguagem, investigam e redigem. Todo cálculo, regra de negócio, valor financeiro e trava de segurança é **Python + Pydantic v2 + SQL**. LLM nunca executa SQL e nunca decide sozinho estornos ou ações de risco.
2. **Autonomia proporcional à reversibilidade.** Agentes de LLM têm liberdade para **ler e analisar** (reversível). Efeitos irreversíveis (bloquear lote, enviar alerta, estornar) só ocorrem por decisão do código determinístico.
3. **`priority_score` ordena a fila e não autoriza nada.** Autorização vem de regras de decisão próprias.
4. **Fluxo explícito.** Transições do LangGraph e regras operacionais são explícitas, sobretudo antes de efeitos externos.
5. **MCP como fronteira de dados.** Agentes são MCP Clients; acesso ao Postgres e ações de ERP/mensageria ficam no MCP Server, com queries parametrizadas.
6. **Auditabilidade.** Eventos por `thread_id` distinguindo: interpretação do modelo, resultado de ferramenta, regra aplicada, decisão do código e ação executada, com versão do modelo/regra. Sem dados pessoais desnecessários.
7. **Idempotência em efeitos externos.** Repetir uma chamada não pode duplicar alerta, bloqueio ou estorno.
8. **Modularidade de provedores.** Nenhum código de negócio ou agente depende de um provedor de LLM, de classificador ou de tradução específico. Tudo atrás de interfaces, trocável por configuração.

## 3. Stack

Python 3.11+ (Docker usa 3.12) · FastAPI · Pydantic v2 · SQLAlchemy 2.0 async + asyncpg · PostgreSQL 16 · LangGraph · MCP Python SDK **2.x** (`mcp.server.mcpserver.MCPServer`) · LangChain (abstração de chat model) · **Ollama** (LLM local) · Streamlit · Pytest (`asyncio_mode = auto`) · Docker Compose · scikit-learn / sentence-transformers / transformers (classificação local; adicionar quando a etapa chegar).

### Camada de LLM modular (D13)

- O código depende apenas da interface `BaseChatModel` do LangChain. Uma **fábrica** (`llm/factory.py`: `get_chat_model(settings, role=...)`) devolve o modelo conforme a configuração.
- Hoje: **Ollama local**. Depois: API externa compatível com OpenAI. A troca é só configuração: `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`. O Ollama também expõe endpoint compatível com OpenAI, o que facilita testar o mesmo código nos dois.
- É possível ter **papéis** com modelos diferentes (ex.: `investigator`, `generalist`, `judge`, `translator`), cada um configurável.
- Testes usam um chat model falso e determinístico; só um *smoke test* separado e opcional fala com o Ollama real.
- Agentes que chamam ferramentas exigem um modelo com **suporte a tool calling**. Confirmar com `ollama show <modelo>` (campo `capabilities`) antes de adotar.
- **Ambiente de desenvolvimento (D19):** o Ollama roda em um **PC Windows separado** do dono (GPU RTX com **4 GB de VRAM** e **8 GB de RAM DDR4**), acessado por VPN (seção 12). O notebook de desenvolvimento não precisa de GPU. Isso limita a modelos de ~3–4B parâmetros em quantização de 4 bits. Padrão: **`qwen3:4b-instruct`** (D20; aprox. 2,5 GB de pesos, mas não cabe inteiro na VRAM útil). Configurar também `LLM_NUM_CTX` (janela de contexto; consome VRAM; padrão 4096), `LLM_TEMPERATURE=0` para agentes e o modo de raciocínio (*thinking*) por papel. Ver 8.2 para o desenho voltado a modelos pequenos.

## 4. Estrutura do repositório (alvo)

Legenda: `[ok]` existe · `[novo]` a criar.

```text
omniops-ai/
├── CLAUDE.md                      [ok]  este arquivo
├── .agents/skills/                [ok]  git-commit-formatter, secrets-guard, pytest-debug-agent, docker-health-check, pydantic-contract-validator
├── api/                           [novo]
│   ├── main.py                          FastAPI e ciclo de vida
│   ├── routes/{webhooks,slack_callback}.py
│   └── adapters/omnichannel.py          payload externo -> StandardTicket
├── agents/                        [novo]  SÓ agentes de LLM: decidem o próprio caminho, em laço (D25)
│   ├── investigator.py                  investigador de causa raiz, autônomo e somente leitura (Etapa 5)
│   └── generalist.py                    atendente ReAct de contatos simples (Etapa 9)
├── workflows/                     [novo]  caminho definido no código (LangGraph ou funções)
│   ├── state.py                         estado tipado do grafo
│   ├── graph.py                         orquestrador (StateGraph, roteamento determinístico)
│   ├── batch_containment.py             detecção e contenção do lote (determinístico)
│   └── response_judge.py                juiz da resposta: passo avaliador (LLM-as-judge), sem laço
├── integrations/                  [novo]  adaptadores para sistemas externos
│   └── specialist_liaison.py            A2A com Slack/Teams: publica dossiê e recebe a resposta
├── classifiers/                   [novo]  modelo de classificação, não agente
│   ├── triage.py                        interface TriageClassifier, TriageResult e implementações
│   └── translation.py                   interface Translator e TranslatingClassifier (decorator)
├── llm/                           [ok]
│   ├── factory.py                       get_chat_model(settings, role), resolve_llm_spec -> LLMSpec
│   └── testing.py                       ScriptedChatModel (falso com bind_tools) para testes
├── mcp_server/                    [ok]
│   ├── server.py, database_tools.py, inventory_tools.py
│   └── investigation_tools.py     [ok]    ferramentas de leitura/agregação + INVESTIGATOR_TOOLS
├── core/                          [ok]
│   ├── config.py, database.py, schemas.py, privacy.py (mask_pii)
│   ├── policy_config.py           [ok]    limiares (lote: Etapa 2) · [novo] palavras-chave (Etapa 7)
│   └── decision_engine.py         [novo]  política determinística (PolicyDecision; Etapa 7)
├── data/                          [ok]  customers.csv, batches.csv, orders.csv, historic_tickets.csv · [novo] units.csv
├── scripts/                       [ok]  generate_synthetic_data.py, seed_db.py · [novo] simulate_traffic.py, run_investigation.py
├── ui/app.py                      [novo]  Streamlit
├── tests/                         [ok]  test_phase1.py · [novo] mocks/*.json, test_flows.py, evals/
├── docker-compose.yml, Dockerfile, pyproject.toml, README.md, .env.example   [ok]
```

## 5. Decisões já tomadas

| # | Decisão | Motivo |
|---|---|---|
| D1 | **MCP Server via HTTP (streamable HTTP) na porta 8001**, não stdio | O compose, o `.env.example` e o README tratam o MCP como serviço de rede; `MCPServer` 2.x oferece `run_streamable_http_async`. |
| D2 | **Fixar `mcp>=2,<3`** | O código importa `mcp.server.mcpserver`, que só existe na 2.x. |
| D3 | **Recriar o banco** (`docker compose down -v`) ao mudar o modelo; **Alembic depois** | Protótipo; `create_all` não migra colunas. Alembic entra como etapa didática própria. |
| D4 | **Corrigir o modelo de dados antes de construir agentes** | Construir fluxo sobre a taxa de falha errada obrigaria refazer tudo. |
| D5 | **Determinístico antes do LLM** | Regras testáveis sem modelo; o LLM entra depois como componente plugado num sistema que já funciona. |
| D6 | **"Unidade" afetada = número de série**, em tabela `units` própria | A taxa conta unidades físicas distintas; um pedido pode ter várias unidades. |
| D7 | **Guardrails em camadas, fail-closed, incerteza como gatilho de HITL** | Erros de modelo são esperados; o desenho deve contê-los (seção 7). |
| D8 | **Componentes:** classificador (modelo, não agente), detecção e contenção de lote (workflow), investigador e generalista (agentes de LLM), juiz (passo avaliador com LLM; D25), orquestrador (workflow), `decision_engine` (regras) e liaison (adaptador) | Responsabilidades distintas; ver seções 8 e 8.6. |
| D9 | **Classificação atrás da interface `TriageClassifier`** | Trocar de modelo sem reescrever o sistema. |
| D10 | **Serial:** `SN-<SIGLA>-<6 dígitos>` (ex.: `SN-SW-000123`; regex `SN-[A-Z]{2,4}-\d{6}`), extraído por regex | Classificador escolhe rótulos, não extrai trechos; regex é determinística e testável. |
| D11 | **Alerta proativo de recall usa template aprovado**, sem geração livre | Comunicação de risco ao consumidor não pode ser improvisada. |
| D12 | **Classificação: caminho gratuito e didático.** Regras lexicais + `FakeTriageClassifier` → zero-shot NLI como ponte → classificador treinado localmente; **Jev (pago, TypeSafe) vira adaptador opcional** | Custo zero e ensina o ciclo de ML (dados, treino, avaliação, calibração). |
| D13 | **LLM local com Ollama, arquitetura modular** para trocar por API externa por configuração | Ver seção 3. |
| D14 | **Três componentes de LLM, nesta ordem de implementação:** investigador (agente) → generalista ReAct (agente) → juiz da resposta (passo avaliador; D25) | Cada um é uma fatia que se implementa, mede e melhora. |
| D15 | **O especialista de lotes é dividido:** detecção e contenção determinísticas (workflow) + **investigador autônomo somente leitura** | Quem age (bloqueia, avisa) é código previsível; quem investiga é o LLM. |
| D16 | **Tradução para inglês é uma estratégia opcional e avaliada por dados** (decorator sobre um classificador em inglês) | Permite usar modelos só em inglês; adotada apenas se superar o multilíngue no conjunto dourado. Ver 8.1. |
| D17 | **Ordem: o agente investigador primeiro**, como fatia vertical | Mostra um agente autônomo funcionando e avaliável cedo; o orquestrador completo vem depois. |
| D18 | **Este arquivo substitui `omniops_ai_master_specification.md`** | Uma única fonte da verdade, mantida atualizada ao fim de cada etapa. |
| D19 | **Ollama em um PC Windows dedicado (RTX 4 GB VRAM, 8 GB RAM), acessado por VPN a partir do notebook de desenvolvimento, ou usado localmente quando o código roda no próprio Windows; modelo inicial `qwen3:4b`**; `qwen3:8b` como referência com offload parcial; API externa só para comparação | Hardware restrito: modelos pequenos erram de forma instrutiva e exigem controles (orçamentos, validação, retentativas, evals). A arquitetura modular permite comparar com modelo maior sem mudar o código. |
| D20 | **Modelo padrão `qwen3:4b-instruct` e `LLM_NUM_CTX=4096`**; `qwen3:4b` (variante *Thinking-2507*) fica só como comparação na Etapa 6 | Medido em 2026-11-23 (Ollama 0.40.17, RTX 3050 Laptop): VRAM útil ~3,2 GB (o Windows usa ~730 MB). A tag `qwen3:4b` é *thinking-only*: ignora `think:false` e `/no_think` e gerou 600–1000 tokens para uma frase (86–275 s). O instruct gerou ~40 tokens em 5,2 s com o modelo carregado. Com `num_ctx` 8192 o modelo vai 45% para a CPU; com 4096, 34%; ~8,6 tok/s nos dois casos. Temperatura 0 **não** garantiu saída idêntica entre execuções: as evals devem repetir cada caso |
| D21 | **Cenário sintético da Etapa 1:** lote DEF com 50 unidades em `L1` e 50 em `L2`; 49 defeitos históricos (45 `L2` ≈ 92%); a unidade de Mariana (`ORD-20050`) reservada na `L2`; 1 unidade reclamada 2× e 1 reclamação sem serial (51 tickets, 49 unidades); 30 compradores silenciosos (`ORD-20054..20083`); `ORD-20052` com 2 unidades; `LOTE-2026-SEP` (mesma fábrica, ~2%) para comparação; coluna `orders.carrier`; **distratores de taxa-base** (RotaSul ≈ 50% do volume; semana de promoção); "bateria estufada" com `is_health_risk=True` (risco de incêndio) | Torna o investigador avaliável (causa conhecida) e exige raciocínio com taxa-base, não contagem bruta. Gerado com `SEED=42` e `uuid5`; `test_generator_is_deterministic` garante que os CSVs versionados batem com o gerador |
| D23 | **Fábrica de LLM em duas fases** (`resolve_llm_spec` pura → `LLMSpec` com `model_version` para auditoria; `get_chat_model` constrói). Provedores `ollama` (nativo, `langchain-ollama`) e `openai_compatible` (extra opcional `.[openai]`, import tardio). **Sobrescrita por papel** via `LLM_ROLES__<PAPEL>__<CAMPO>` (papel inválido falha na inicialização; `env_ignore_empty=True`). **Agentes recebem o modelo por injeção**; testes usam `llm.testing.ScriptedChatModel` (roteiro de `AIMessage`, implementa `bind_tools` e registra chamadas/ferramentas). Smoke test opt-in: `pytest -m ollama -s` | Os falsos do LangChain não implementam `bind_tools`. Medido em 2026-11-23: `qwen3:4b-instruct` acertou ferramenta e argumento nos dois caminhos (nativo 5,9 s, `/v1` 5,5 s, modelo carregado); com `qwen3:4b` (thinking) a mesma chamada levou 35 s. No caminho `/v1` **não há `num_ctx`**: o Ollama usa o padrão do servidor (`OLLAMA_CONTEXT_LENGTH`) |
| D24 | **Ferramentas do investigador:** lista fechada `INVESTIGATOR_TOOLS` (6): `check_batch_failure_rate`, `defect_rate_by(batch_id, dimension)` (uma ferramenta com `dimension` enumerada em vez de quatro), `compare_factory_batches`, `complaint_timeline`, `search_symptoms`, `sample_defect_complaints` (máx. 8). Devolvem **taxas já normalizadas** pela base do grupo (produzidas para linha/dia; vendidas para transportadora/semana), texto livre via `mask_pii`, orçamento de **≤ 1.500 caracteres por resposta** (testado) e erros com as opções válidas. Todas as ferramentas MCP têm `ToolAnnotations` (dica ao cliente, não proteção). `get_batch_defect_symptoms` (texto sem máscara, para o dossiê humano) e `find_silent_customers` (contatos) **ficam fora** | Para modelos pequenos, poucas ferramentas e respostas curtas importam mais que o prompt; cálculo é determinístico (princípio 1). Achado: nos dados, as taxas por transportadora variam por **ruído de amostra pequena** (ExpressoNorte 0,70 com 20 unidades × RotaSul 0,52 com 42), o que vira um distrator realista, muito mais fraco que L2 0,90 × L1 0,08. O servidor MCP também valida o `enum` e devolve as opções ao modelo |
| D25 | **Nomes e pastas pela natureza da peça** (seção 8.6): `agents/` só contém agentes de LLM (`investigator.py`, `generalist.py`); `workflows/` tem `state.py`, `graph.py`, `batch_containment.py` (ex-`quality_agent`) e `response_judge.py` (ex-`judge_agent`); `integrations/specialist_liaison.py` (ex-`liaison_agent`); `core/decision_engine.py`. Sem sufixo `_agent` em arquivos. **Pendência da Etapa 10:** se o juiz ganhar ferramentas para verificar fatos por conta própria (laço), ele passa a ser agente e muda para `agents/` | Decidido em 2026-11-24, antes de qualquer arquivo existir (custo zero). Chamar workflow, adaptador ou regra de "agente" esconde a arquitetura e soa como exagero em entrevista. Descartados: manter `agents/` e só renomear arquivos (a pasta continuaria imprecisa); pasta genérica `components/` (perde a informação); `policy/` para um arquivo só |
| D22 | **Ticket com serial válido do lote e sem pedido informado conta no numerador**; serial que não corresponde ao pedido citado (outro lote, outro pedido ou unidade em estoque) não conta em lote nenhum e vai para HITL | O serial identifica a unidade física; subcontar atrasaria a contenção de um risco de segurança (bateria estufada). A posse da unidade é verificada depois, no HITL. Inconsistência nunca infla nenhum lote |

## 6. Modelo de dados e fórmulas

### 6.1 Tabelas (PostgreSQL 16, SQLAlchemy 2.0 async)

- **`customers`**: `customer_id` UUID PK · `name` · `email` único · `phone` único · `tier` ∈ {`VIP`,`Regular`,`New`} · `lifetime_value` Decimal(10,2) · `total_orders` · `return_rate` float 0..1.
- **`batches`**: `batch_id` PK (ex.: `LOTE-2026-11-A`) · `product_id` · `product_name` · `manufacturing_date` · `factory_code` · `total_units_produced` · `is_blocked` (default false) · `proactive_recall_triggered` (default false).
- **`orders`**: `order_id` PK · `customer_id` FK · `product_id` · `batch_id` FK · `order_value` · `carrier_status` ∈ {`in_transit`,`delivered_signed`,`delayed`} · `carrier` (transportadora: `RotaSul`, `TransVale`, `ExpressoNorte`; D21) · `purchase_date`. O booleano `proactive_alert_sent` foi **removido** (Etapa 1) em favor de `proactive_alert_events`.
- **`units`** *(novo, D6)*: `serial_number` PK · `batch_id` FK · `product_id` · `order_id` FK anulável · `production_line` · `manufactured_at`. As colunas de produção existem para a investigação de causa raiz.
- **`tickets`**: `ticket_id` UUID PK · `thread_id` (sessão LangGraph) · `customer_id` FK · `order_id` FK anulável · **`serial_number` FK anulável para `units`** · `channel` ∈ {`whatsapp`,`email`,`reclame_aqui`} · `message_text` · `intent` (`defective_item`, `shipping_delay`, `health_issue`, `refund_request`, `tracking_inquiry`, `other`) · `sentiment_score` −1.0..1.0 · `sentiment_label` ∈ {`Positivo`,`Neutro`,`Negativo`,`Extremamente Negativo`} · `is_health_risk` · `batch_flagged` · `priority_score` 0..100 · `autonomy_status` ∈ {`auto_resolved`,`human_in_the_loop`,`escalated_specialist`} · `created_at`. `serial_number NULL` significa "unidade não identificada".
- **`proactive_alert_events`**: `event_id` · `order_id` FK, **`UNIQUE(order_id)`** (`uq_alert_per_order`: um alerta por pedido; novas tentativas atualizam a linha) · `status` ∈ {`pending`,`attempted`,`failed`,`delivered`} · `template_id` (D11; hoje `recall_alert_v1`) · `attempts` · `provider_message_id` · `last_error` · `created_at`/`updated_at`/`delivered_at`. **Só conta como alerta enviado após `delivered`** (confirmação do provedor). Enfileirar usa `INSERT ... ON CONFLICT DO NOTHING` (idempotente).
- **`audit_events`**: `event_id` · `thread_id` · `kind` ∈ {`model_interpretation`,`tool_result`,`rule_applied`,`decision`,`action`} · `payload` JSON (sem dados pessoais desnecessários) · `model_version` / `rule_id` · timestamp.

### 6.2 Fórmulas determinísticas

**Taxa de falha do lote** (disparada quando `intent == 'defective_item'`):

```
taxa = unidades distintas identificadas com defeito no lote / total_units_produced
```

- Numerador: `COUNT(DISTINCT tickets.serial_number)` dos tickets `defective_item` do lote com serial não nulo. Várias reclamações da mesma unidade contam **uma**.
- Reclamações sem serial identificável são contadas **à parte**, fora do numerador, e exibidas junto da taxa (a taxa pode estar abaixo da incidência real).
- Serial informado que não existe em `units` ou pertence a outro lote **não entra** no numerador e vai para HITL.
- **Regra exata implementada (Etapa 2, D22):** um ticket `defective_item` entra no numerador se `units.batch_id = lote` **e** (`tickets.order_id IS NULL` **ou** `tickets.order_id IS NOT DISTINCT FROM units.order_id`). Tickets ligados ao lote (pelo pedido ou pelo serial) que têm serial mas falham nessa condição são `inconsistent_serial_complaints_count` (HITL). Serial inexistente não pode ser gravado (FK): o ticket fica com `serial_number NULL` e cai em `unidentified_complaints_count`. Limiar `>= 0.50` em `core/policy_config.py` (`Decimal`, `rule_id = batch.failure_rate.critical_v1`). Saída validada por `BatchFailureMetrics`.
- **Taxa ≥ 0.50:** (1) marca `batch_flagged` no ticket e bloqueia o lote (`is_blocked = true`); (2) alerta proativo aos "clientes silenciosos"; (3) aciona o especialista humano (A2A) com dossiê e dispara o investigador.

**Clientes silenciosos:** a elegibilidade é **por pedido**. Um pedido do lote é elegível se não há reclamação de defeito referente ao produto/lote daquele pedido e não há alerta com status `delivered`. Implementado como: não existe ticket `defective_item` com `order_id` = pedido **ou** com serial de uma unidade do pedido; e não existe `proactive_alert_events` `delivered` do pedido. Outros pedidos do mesmo cliente não interferem. A ferramenta devolve `silent_orders` (com contato do cliente: **nunca** entregá-la ao investigador; menor privilégio/LGPD).

**Priority score** (ordena a fila, não autoriza ações):

```
priority_score = min(100, W_tier + W_ltv + W_sentimento + W_canal)
W_tier:        VIP +35 · Regular +15 · New +5
W_ltv:         +15 se lifetime_value >= 1500.00
W_sentimento:  +25 se sentiment_score <= -0.7 · +10 se sentiment_score < 0
W_canal:       reclame_aqui +25 · whatsapp +10 · email +5
```

## 7. Fluxo, autonomia e guardrails

### 7.1 Fluxo

```text
[WhatsApp | E-mail | Reclame Aqui] -> [Adapter -> StandardTicket]
        -> [Classificador (modelo): intenção, sentimento, risco de saúde, ameaça judicial, caixa vazia]
           + regex (serial, pedido) + regras lexicais (segundo sinal)
        -> [decision_engine: PolicyDecision AUTO | HITL | HARD_STOP]
              |-- saúde ........ HARD_STOP: texto padrão prudente + equipe de Qualidade/Médica/Jurídica
              |-- ameaça judicial  HITL prioritário: acuse neutro + atendimento humano
              |-- defective_item . [batch_containment (workflow): taxa do lote]
              |        taxa >= 0.50: bloqueio + alertas por template + dossiê ao especialista
              |                      (specialist_liaison, A2A)
              |                      + [investigator (AGENTE, somente leitura)] anexa hipóteses ao dossiê
              |-- demais ........ [generalist (AGENTE ReAct, ferramentas de leitura)]
                                        -> [response_judge (passo avaliador)] -> envio
                                           (se o juiz e a política aprovarem)
        HITL: o grafo pausa por thread_id e retoma quando o especialista responde (webhook).
```

### 7.2 Arquitetura de guardrails (D7)

Não existem valores universais de mercado (dependem do custo do erro); o padrão é o **desenho**:

1. **Fail-closed.** Na dúvida, não executa: encaminha a humano.
2. **Modelo propõe, política decide.** Modelos devolvem campos estruturados com probabilidade/confiança. O `decision_engine` devolve `PolicyDecision` (Pydantic): `outcome` ∈ {`AUTO`,`HITL`,`HARD_STOP`}, `reasons` (lista de `rule_id`), `required_approver`.
3. **Precedência fixa:** `HARD_STOP` > `HITL` > `AUTO`. A primeira regra que dispara vence; o `rule_id` vai para a auditoria.
4. **Risco assimétrico.** Saúde/segurança é de alta revocação: aceita falso positivo, nunca falso negativo.
5. **Incerteza é gatilho de HITL:** (a) confiança da intenção abaixo do limiar; (b) saída do modelo inválida no schema após 1 nova tentativa; (c) **discordância entre sinais** (ex.: modelo diz neutro, texto contém "procon"); (d) identificação ambígua de cliente, pedido ou serial; (e) dado essencial ausente; (f) falha de API ou timeout.
6. **Entrada não confiável.** Mensagem do cliente e saídas de ferramentas são dados, nunca instruções (prompt injection). Ferramentas de escrita só executam com decisão do motor determinístico; cada nó/agente tem lista explícita de ferramentas (menor privilégio).
7. **Dinheiro em camadas:** limite por ação, limite de velocidade por cliente e teto diário com *circuit breaker*.
8. **HITL bem projetado:** aprovação vinculada à ação específica, com evidências; SLA e *timeout* seguro (não executa, escala); registra quem aprovou.
9. **Kill switch:** flag `FORCE_HITL` desliga toda a autonomia.
10. **Avaliação contínua:** conjunto dourado (incluindo adversariais) no `pytest`; amostragem de casos auto-resolvidos para revisão humana.
11. **Privacidade (LGPD):** mascarar dados pessoais em logs, auditoria e antes de enviar texto a qualquer serviço externo.

**Valores iniciais** (configuráveis em `core/policy_config.py`; a calibrar):

| Regra | Valor inicial | Resultado |
|---|---|---|
| Confiança da intenção | < 0.75 | `HITL` |
| Risco de saúde/segurança | P ≥ 0.30 **ou** palavra-chave | `HARD_STOP`, **sempre humano, sem exceção**. Resposta ao cliente: só o texto padrão prudente, sem assumir culpa |
| Ameaça judicial (Procon, processo, advogado) | modelo **ou** regra lexical | `HITL` prioritário, **sempre humano, sem exceção**. Resposta automática: só acuse neutro, sem mérito |
| Sentimento | ≤ −0.8 | `HITL` prioritário |
| Sentimento | entre −0.8 e −0.5 com baixa confiança | `HITL` |
| Suspeita de fraude | cliente `New` com `return_rate` ≥ 0.30, **ou** "caixa vazia" com `delivered_signed` | `HITL` |
| Valor da ação | ≤ R$ 100 | `AUTO` se VIP de baixo risco (`return_rate` < 0.10) |
| Valor da ação | R$ 100 a R$ 500 | `AUTO` só com todos os checks e alta certeza; senão `HITL` |
| Valor da ação | > R$ 500 | supervisor (`HITL`) |
| Velocidade | até **2 reembolsos automáticos por cliente em 30 dias**, só com **alta certeza** (confiança ≥ 0.90 nos campos relevantes e todos os checks) | a partir do 3º, ou sem alta certeza → `HITL` |
| Teto diário de reembolsos automáticos | R$ 3.000,00 (simulação) | *circuit breaker* → `HITL` |

Autonomia total permitida: rastreio e dúvidas de entrega; contenção e alerta proativo de lote ≥ 50% (a ordem formal de **recall** e o encerramento da causa raiz exigem o especialista humano); fast-track VIP de baixo risco dentro dos limites acima.

## 8. Componentes

### 8.1 Classificador de mensagens (modelo, não agente) — D9, D12, D16

Recebe texto e devolve rótulos com probabilidades. Não gera linguagem, não chama ferramentas, não decide.

**Interface:** `TriageClassifier` (Protocol) com `async classify(ticket) -> TriageResult` (Pydantic: valor e probabilidade/confiança por campo, mais `model_version` e `provider`). Campos: `intent`, `sentiment_score`, `is_health_risk`, `legal_threat`, `empty_box_claim`. **Serial e pedido não são classificação:** vêm de regex (D10).

**Implementações, na ordem didática:**

| Ordem | Implementação | Custo | Observações |
|---|---|---|---|
| 1 | `FakeTriageClassifier` + regras lexicais | grátis | Determinística, para testes e demo offline. As regras lexicais ficam como **segundo sinal independente** em todas as configurações |
| 2 | Zero-shot NLI (ponte) | grátis | Multilíngue: `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` (MIT; o card não reporta acurácia em português; dados traduzidos por máquina). Só inglês: `facebook/bart-large-mnli` |
| 3 | **Classificador treinado localmente** | grátis | Embeddings multilíngues + regressão logística sobre nosso conjunto rotulado; sentimento como outra "cabeça" sobre os mesmos vetores. Probabilidades calibráveis, milissegundos em CPU |
| 4 | `LLMTriageClassifier` | grátis (Ollama) | Saída estruturada; mais lento; probabilidades não calibradas |
| opcional | `JevTriageClassifier` | **pago** | TypeSafe Jev via `typesafe-sdk` (`AsyncTypeSafeClient`). Inglês é o idioma principal; português não documentado. Fixar versão (`jev-1.14.0`, não `jev-latest`) e registrar o campo `model`. `Noul` devolve só probabilidade, sem `confidence`. Mapeamento: `intent`→`Choice`, `sentiment`→`Score`, `is_health_risk`/`legal_threat`/`empty_box_claim`→`Noul` |

**Estratégia de tradução (D16):** `TranslatingClassifier` é um *decorator* que traduz a mensagem para inglês e delega a um classificador em inglês. Regras:
1. Regex (serial, pedido) e regras lexicais rodam **sempre no texto original em português**.
2. A tradução alimenta somente o classificador; guardar original e tradução na auditoria (com PII mascarada).
3. Tradutor atrás da interface `Translator`. Candidatos gratuitos e locais: `Helsinki-NLP/opus-mt-ROMANCE-en` (existe no Hugging Face; verificar qualidade em português) ou o LLM local via Ollama. NLLB é outra alternativa a verificar.
4. Riscos: **erros se compõem** (tradução + classificação), perda de negação, ironia e gíria, nomes próprios ("Procon", "Reclame Aqui"), latência de mais um modelo.
5. **Decisão por dados:** comparar no mesmo conjunto dourado o multilíngue nativo contra traduzir+inglês, por campo, priorizando **revocação de saúde e ameaça judicial**. Adotar só se vencer.

**Calibração e avaliação:** conjunto dourado em português (mensagens sintéticas revisadas à mão, incluindo adversariais), com matriz de confusão e curva de calibração por campo. É o critério para escolher a implementação ativa.

### 8.2 Agente investigador de causa raiz — D14, D15, D17 (primeiro a implementar)

Agente de LLM **autônomo e somente leitura**, acionado quando a taxa do lote atinge 0.50 (e por script, durante o desenvolvimento). Recebe só o objetivo ("investigar a causa provável do defeito no lote X") e decide quais ferramentas chamar e em que ordem.

- **Ferramentas (MCP, só leitura, dados agregados e sem PII)**, em `mcp_server/investigation_tools.py` (implementadas na Etapa 4, D24): `check_batch_failure_rate`; `defect_rate_by(batch_id, dimension ∈ {production_line, manufacturing_day, carrier, purchase_week})`; `compare_factory_batches`; `complaint_timeline`; `search_symptoms(batch_id, term)`; `sample_defect_complaints(batch_id, limit≤8)`. O agente recebe **só** `INVESTIGATOR_TOOLS`.
- **Saída** (`InvestigationReport`, Pydantic): `hypotheses[]` (descrição, evidências, testes executados, confiança), `unknowns[]`, `recommended_checks[]`, `tools_called[]`, `stop_reason`. O agente pode concluir "causa indeterminada". Tudo é **hipótese para o especialista validar**, nunca recall.
- **Implementação:** subgrafo LangGraph em laço (nó do agente ↔ nó de ferramentas) usando `get_chat_model(role="investigator")`.
- **Desenho para modelos pequenos (D19):** poucas ferramentas (até ~6), com nomes claros, argumentos simples e **respostas compactas** (agregados curtos, nunca tabelas grandes, para não estourar o contexto); instruções de sistema curtas e explícitas; temperatura 0; saída final validada pelo schema com **uma nova tentativa** em caso de erro; se falhar de novo, devolver relatório `causa indeterminada` em vez de inventar. Modelos pequenos tendem a escolher a ferramenta errada ou repetir chamadas: o limite de passos e a detecção de chamadas repetidas protegem contra laços inúteis.
- **Controles:** lista fixa de ferramentas de leitura; limite de passos (ex.: 8), de tokens e de tempo; saída estruturada; cada chamada de ferramenta vai para `audit_events`; dados de ferramentas tratados como dados, não instruções.
- **Avaliação (eval):** os dados sintéticos **plantam uma causa conhecida**: ≥ 90% das unidades defeituosas vêm da linha `L2`, com sintoma "bateria estufada", além de **distratores** (atrasos de transportadora, semana de compra). Critério de sucesso: a hipótese principal aponta `L2`; métricas secundárias: passos usados, ferramentas irrelevantes chamadas, alucinações (afirmação sem evidência). Comparar modelos locais entre si e, depois, com uma API externa.

### 8.3 Generalista ReAct — D14

Atende rastreio, dúvidas de entrega e faz o atendimento inicial (acuse, perguntas de esclarecimento). Agente ReAct com **ferramentas MCP de leitura** (`lookup_order`, `lookup_customer`, histórico). É o único que redige texto livre ao cliente, e só dentro do que a política autorizou. Nunca recebe ferramentas de escrita.

### 8.4 Juiz da resposta — D14, D25

Passo avaliador do workflow (`workflows/response_judge.py`; LLM-as-judge, padrão *avaliador-otimizador*), sem laço nem ferramentas, que confere o rascunho do generalista **antes do envio**: aderência à política, ausência de promessa não autorizada, ausência de admissão de culpa, coerência com os dados consultados, tom. Devolve veredito estruturado (`aprovar` | `reescrever` | `escalar`). Não substitui a política: o `decision_engine` continua tendo a palavra final. Avaliar o próprio juiz com casos conhecidos (respostas boas e ruins). Se na Etapa 10 ele receber ferramentas para conferir fatos por conta própria, vira agente e muda para `agents/` (D25).

### 8.5 Orquestrador, política e enlace

- **Orquestrador** (`workflows/graph.py`, estado em `workflows/state.py`): `StateGraph` com **roteamento determinístico** (não um LLM supervisor), checkpoint por `thread_id`, pausa para HITL e retomada.
- **`core/decision_engine.py`**: política determinística; não é agente.
- **`workflows/batch_containment.py`**: detecção e contenção do lote (workflow determinístico com ferramentas MCP).
- **`integrations/specialist_liaison.py`**: adaptador A2A com Slack/Teams (não raciocina). Publica o **dossiê técnico** (canal de origem, sintomas, `batch_id`, `factory_code`, `manufacturing_date`, `product_id`, volume produzido vs. taxa, contenção já executada e contagem de clientes silenciosos alertados, hipóteses do investigador) e botões de retorno (ex.: "Registrar causa raiz e confirmar recall do lote X"). O webhook de resposta valida o token, registra o diagnóstico e retoma o grafo (`graph.ainvoke(None, config={"configurable": {"thread_id": ...}})`).
- **Ingestão omnichannel** (`api/adapters/omnichannel.py`): WhatsApp (estilo Evolution API/Meta Cloud API: `data.key.remoteJid`, `data.message.conversation`), e-mail (estilo SendGrid Inbound Parse: `from`, `subject`, `text`), Reclame Aqui (`consumer_username`, `title`, `complaint_body`) → `StandardTicket`.

### 8.6 Modelo, workflow ou agente? (nota didática)

Distinção do texto "Building effective agents" (Anthropic): *modelo de classificação* (entrada → rótulos, sem ferramentas nem laço); *workflow* (caminho definido em código, o LLM pode ser um passo); *agente* (o LLM decide dinamicamente ferramentas e ordem, em laço). Descrever cada peça pelo que ela é, no README e em entrevistas. A estrutura de pastas segue esta tabela (D25):

| Peça | Natureza | Laço e escolha do próximo passo? | Onde |
|---|---|---|---|
| Classificador de triagem | modelo de ML (entrada → rótulos) | não | `classifiers/` |
| `decision_engine` | regras determinísticas | não | `core/` |
| Contenção de lote, orquestrador | workflow | não (caminho fixo no código) | `workflows/` |
| Juiz da resposta | passo avaliador com LLM | não (uma chamada, sem ferramentas) | `workflows/` |
| Liaison (Slack/Teams) | adaptador de integração | não | `integrations/` |
| **Investigador** | **agente de LLM** | **sim** (objetivo → escolhe ferramentas e quando parar) | `agents/` |
| **Generalista** | **agente de LLM** (ReAct) | **sim** | `agents/` |

**Agência é um espectro.** Pelas propriedades clássicas (Wooldridge & Jennings: autonomia, reatividade, proatividade, habilidade social), o investigador é agente com **autonomia deliberadamente limitada** (só leitura, ≤ 6 ferramentas, ≤ 8 passos; princípio 2), reage a cada resultado de ferramenta e persegue o objetivo, mas **não se ativa sozinho** (o workflow o dispara) e **adapta-se só dentro de uma execução** (sem memória entre execuções; a melhora entre versões é feita pelos engenheiros via evals, Etapa 6). O **sistema** resolve tarefas simples de ponta a ponta combinando peças estreitas: classificador percebe → política decide → generalista age → juiz e política verificam. O classificador nunca fala com o cliente.

## 9. Estado atual do código (auditoria de 2026-11-23)

**Existe:** `core/{config,database,schemas,policy_config,privacy}.py` · `llm/{factory,testing}.py` · `mcp_server/{server,database_tools,inventory_tools,investigation_tools}.py` · `scripts/{generate_synthetic_data,seed_db}.py` · `data/*.csv` (incl. `units.csv`) · `tests/{conftest,test_phase1,test_mcp_transport,test_data_model,test_batch_rules,test_llm_factory,test_investigation_tools,test_privacy}.py` · `tests/smoke/test_ollama_smoke.py` (opt-in, `-m ollama`) · `Dockerfile` · `docker-compose.yml` · `.env.example` · `.gitattributes` · `.agents/skills/*`.

**Testes de integração** (`@pytest.mark.integration`): usam o banco `<POSTGRES_DB>_test` (criado automaticamente, esquema recriado a cada execução, rollback por teste); são pulados se o Postgres não responder. Nunca tocam o banco de desenvolvimento.

**Não existe:** `api/*` · `agents/*` · `workflows/*` · `integrations/*` · `core/decision_engine.py` · `classifiers/*` · `ui/*` · `scripts/simulate_traffic.py` · `tests/mocks/*` · `tests/test_flows.py`.

**Divergências a corrigir, em ordem:**

1. ~~Taxa de falha conta tickets~~ **resolvido nas Etapas 1 e 2:** modelo e dados (D21) e consulta por `COUNT(DISTINCT serial)` (D22). Antes devolvia 0.51 / crítico com 49 unidades; agora 0.49 / não crítico. Testes em `tests/test_batch_rules.py`.
2. ~~Alerta proativo é booleano~~ **resolvido na Etapa 1:** `proactive_alert_events`; a ferramenta `mark_alerts_sent` virou `queue_alerts` (`queue_proactive_alerts`), que só cria `pending` de forma idempotente. Falta o fluxo de envio/confirmação do provedor (Etapa 8).
3. ~~"Cliente silencioso" calculado por cliente~~ **resolvido na Etapa 2:** por pedido, com `EXISTS` correlacionado (`.correlate(Order)`) e só alertas `delivered`. A chave de saída mudou para `silent_orders` / `silent_orders_count`.
4. ~~Falta `audit_events`~~ **tabela criada na Etapa 1**; a escrita de eventos entra com os agentes.
5. ~~MCP Server usa stdio~~ **resolvido na Etapa 0:** streamable HTTP em `MCP_SERVER_HOST:MCP_SERVER_PORT/mcp`, rota `/health` fora do protocolo e `healthcheck` no compose. Teste: `tests/test_mcp_transport.py` (cliente MCP real, sem Postgres). Nota: com `MCP_SERVER_HOST=0.0.0.0` a proteção contra DNS rebinding da biblioteca fica desligada (necessário para `mcp_server:8001` no Docker); fora do Docker, o MCP escuta em todas as interfaces.
6. **`pyproject.toml`:** ~~`mcp>=2,<3`~~ feito (instalado 2.3.0). Pendente: incluir `classifiers*` e `llm*` no `include` quando existirem; adicionar dependências das etapas conforme chegarem.
7. ~~`.env.example` e `core/config.py`~~ **resolvido na Etapa 0:** `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` (`SecretStr`), `LLM_TEMPERATURE`, `LLM_NUM_CTX`, `LLM_TIMEOUT_SECONDS`; `LLM_DOCKER_BASE_URL` (URL vista de dentro dos containers; `host.docker.internal` com `extra_hosts: host-gateway`). Variáveis `OPENAI_*` removidas. Se o Jev for usado, adicionar `TYPESAFE_API_KEY` e `TYPESAFE_DEFAULT_MODEL`.
8. Menores: ~~datas sem fuso no seed~~ (resolvido na Etapa 1: CSVs em ISO 8601 UTC, `fromisoformat`); `get_customer` normaliza e-mail e não telefone (normalizar para E.164). `.gitignore` cobre `.env`, `__pycache__/` e `.venv/` (ok); `.gitattributes` criado (Etapa 0). **Não leia nem comite o `.env` real.**
9. **Testes de integração lentos sem Postgres:** com o banco fora do ar, os testes são pulados corretamente, mas cada um espera o tempo limite de conexão (suíte de ~20 s passou a 132 s em 2026-11-24). Detectar a indisponibilidade uma vez por execução no `conftest.py` e pular os demais na hora.

## 10. Roteiro por etapas (investigador primeiro — D17)

Cada etapa termina com testes passando, esta seção e a 9 atualizadas, a **tabela de status, o roteiro e a estrutura do `README.md` atualizados** (o README é a vitrine: só promete o que roda), e proposta de commit.

| Etapa | Entrega | Conceito a explicar |
|---|---|---|
| 0 ✅ | Preparação: `mcp>=2,<3`, MCP via HTTP + healthcheck, variáveis `LLM_*` no `.env.example`/`config.py`, preparar o PC Windows como servidor de Ollama (seção 12), baixar `qwen3:4b` e validar a conexão a partir do notebook com `curl` pela VPN. O código no notebook usa `LLM_BASE_URL` apontando para o PC (modo A) | Transportes MCP; pinagem de dependências; configuração por ambiente |
| 1 ✅ | Modelo de dados: `units`, `tickets.serial_number`, `proactive_alert_events`, `audit_events`; CSVs e seed com **causa `L2` plantada**, gerados com semente fixa e IDs determinísticos (`uuid5`) para reprodutibilidade entre máquinas | Modelar estado com efeitos externos; idempotência; criar dados que tornam um agente avaliável |
| 2 ✅ | Taxa por unidades distintas e silenciosos por pedido, com testes (49% → 50%, duplicata, sem serial) | TDD em regra de negócio; SQL com `DISTINCT` e subqueries |
| 3 ✅ | `llm/factory.py` (Ollama; chat model falso para testes; smoke test opcional) | Abstração de provedor; testar código com LLM sem LLM |
| 4 ✅ | `mcp_server/investigation_tools.py` com testes | Desenho de ferramentas para LLM: pequenas, tipadas, agregadas, seguras |
| 5 | **Agente investigador v1** (`agents/investigator.py`; subgrafo em laço, orçamentos, `InvestigationReport`) rodando via `scripts/run_investigation.py` | Laço ReAct, tool calling, limites de autonomia, saída estruturada |
| 6 | **Avaliar e melhorar o investigador:** eval contra a causa plantada, métricas, ajuste de prompt, comparação entre `qwen3:4b`, `qwen3:8b` (com offload parcial para CPU) e, depois, uma API externa | Como medir um agente; avaliação de sistemas não determinísticos |
| 7 | `core/policy_config.py`, `core/decision_engine.py` e classificador: `Fake` + lexical → NLI → treinado; tradução opcional; conjunto dourado e calibração | Camada determinística vs. modelo; fail-closed; ciclo de ML; avaliação por campo |
| 8 | Orquestrador (`workflows/graph.py`, `workflows/state.py`), contenção de lote integrada (`workflows/batch_containment.py`), HITL, `integrations/specialist_liaison.py`; investigador acionado ao atingir 50% | Estado, roteamento condicional, pausa e retomada por `thread_id`, A2A |
| 9 | Generalista ReAct (`agents/generalist.py`), com avaliação | Agente voltado ao cliente com menor privilégio |
| 10 | Juiz da resposta (`workflows/response_judge.py`), com avaliação do próprio juiz; decidir se ganha ferramentas (vira agente, D25) | LLM-as-judge e seus vieses |
| 11 | `api/*`, mocks JSON, `simulate_traffic.py`, `test_flows.py`, `ui/app.py` | Normalização omnichannel; demo de portfólio |
| 12 | Alembic e endurecimento (observabilidade, limites, kill switch) | Migrações de esquema; operação |

## 11. Convenções

- Pydantic v2 apenas: `model_dump()`, `model_validate()`; nada de `.dict()` / `.parse_obj()` (skill `pydantic-contract-validator`).
- Contratos compartilhados em `core/schemas.py`; estado do grafo em `workflows/state.py`. Arquivos sem sufixo `_agent`; a pasta diz a natureza da peça (D25).
- Tudo assíncrono (SQLAlchemy async + asyncpg). Ferramentas MCP aceitam `session` opcional para facilitar testes.
- Provedores (LLM, classificador, tradutor) sempre atrás de interface e configuração (princípio 8).
- Commits em Conventional Commits: `<tipo>(<escopo>): <descrição no imperativo>` (skill `git-commit-formatter`).
- Nenhuma credencial no código; tudo via `core/config.py`. `.env.example` documenta toda variável e porta (skills `secrets-guard` e `docker-health-check`).
- Efeitos externos são idempotentes e registram evento de auditoria.
- Testes de agentes usam o chat model falso; avaliações (evals) ficam em `tests/evals/` e podem rodar contra o Ollama real sob marcador opcional.

## 12. Comandos

```bash
cp .env.example .env                       # primeira vez
docker compose up --build                  # postgres, seed, api, mcp_server, ui
docker compose down -v                     # recria o banco do zero (D3)
pip install -e ".[dev]"                    # ambiente local
pytest -v                                  # testes
python scripts/generate_synthetic_data.py  # regenera data/*.csv
python scripts/seed_db.py                  # popula o Postgres a partir dos CSVs
```

Portas: API 8000 · MCP 8001 · Streamlit 8501 · Postgres 5432 · Ollama 11434 (padrão).

### Ambientes do dono: dois computadores

- **Notebook Linux:** repositório principal, desenvolvimento, testes com chat model falso, Docker (Postgres, MCP).
- **PC Windows com GPU (RTX 4 GB de VRAM, 8 GB de RAM):** servidor de LLM (Ollama) e, **às vezes, também executa o código** diretamente.
- Os dois se conectam por **VPN privada** (solução a escolher; opções comuns: Tailscale, WireGuard, ZeroTier; verificar).

**Dois modos de uso, mesma base de código, configuração diferente:**

| Modo | Onde roda o código | `LLM_BASE_URL` no `.env` | Observações |
|---|---|---|---|
| A. Remoto | Notebook | `http://<ip-da-vpn-do-pc>:11434` | Só as chamadas de LLM atravessam a VPN; Postgres e dados ficam no notebook |
| B. Local no Windows | PC Windows | `http://localhost:11434` | Exige o projeto e um Postgres no Windows (ver abaixo) |

O `.env` não vai para o git e é específico de cada máquina; o `.env.example` documenta os dois valores de `LLM_BASE_URL`.

**PC Windows como servidor de Ollama (modo A):**
1. Instalar o Ollama para Windows (usa a GPU NVIDIA diretamente) e baixar o modelo: `ollama pull qwen3:4b`.
2. Para aceitar conexões pela VPN, definir a variável de ambiente `OLLAMA_HOST=0.0.0.0` e reiniciar o Ollama. Isso o faz escutar em **todas** as interfaces, então o passo 3 é obrigatório.
3. No Firewall do Windows, liberar a porta TCP 11434 **apenas para o intervalo de IPs da VPN**, sem liberar Wi-Fi ou rede local comum.
4. No notebook, testar: `curl http://<ip-da-vpn>:11434/api/tags`.

**Segurança:** o Ollama **não tem autenticação**. Qualquer dispositivo que alcance a porta pode usar a GPU e os modelos. Por isso a regra de firewall restrita à VPN, e nunca expor à internet.

**PC Windows executando o código (modo B):**
- Sincronizar o repositório por git (o remoto é decisão do dono; nada de `git push` sem autorização).
- Instalar Python 3.11+ e Git; criar o ambiente virtual (no Windows, `.venv\Scripts\activate`).
- **Postgres**, duas opções: (1) PostgreSQL nativo para Windows, que usa menos RAM; (2) Docker Desktop (WSL2), limitando o WSL2 em `%UserProfile%\.wslconfig` com valores iniciais `[wsl2]`, `memory=3GB`, `swap=4GB` (aplicar com `wsl --shutdown`). Com 8 GB de RAM, **o modelo no Ollama tem prioridade de memória**.
- Adicionar `.gitattributes` com `* text=auto eol=lf` para o CRLF do Windows não quebrar scripts e o `Dockerfile`.
- **Dados reproduzíveis:** gerar os dados sintéticos com semente fixa e IDs determinísticos (`uuid5`) e versionar os CSVs, para que o seed e as avaliações deem o mesmo resultado nas duas máquinas. Hoje `generate_synthetic_data.py` usa `uuid4` nos tickets históricos, o que muda os IDs a cada regeneração.
- O código usa `pathlib` e não deve ter caminhos fixos; manter assim para funcionar em Linux e Windows.

## 13. Perguntas em aberto

- VPN entre o notebook e o PC Windows (seção 12): qual solução será usada (Tailscale, WireGuard, ZeroTier...)? Anotar o IP do PC na VPN e testar `curl http://<ip-da-vpn>:11434/api/tags`. Modo B: Postgres via **Docker Desktop** (decidido em 2026-11-23).
- Opcional para caber mais na VRAM: `OLLAMA_FLASH_ATTENTION=1` e `OLLAMA_KV_CACHE_TYPE=q8_0` no Windows (KV cache pela metade). Medir antes e depois.
- Medir, na Etapa 6, se `qwen3:4b` basta para o investigador ou se vale comparar com `qwen3:8b` (offload) e com uma API externa de baixo custo.
- Valores finais dos guardrails (7.2): confirmar limiares, teto diário e limite de `return_rate`; definir as listas de palavras-chave (saúde, ameaça judicial, "caixa vazia").
- Resposta ao cliente que informa um serial inexistente ou de outro lote: pedir confirmação ou escalar a humano?
- Recall formal e comunicação a autoridades e consumidores (Código de Defesa do Consumidor, art. 10): fora do escopo do código; validar com o jurídico antes de apresentar o projeto como solução real.
- Jev: o dono tem chave da TypeSafe? É opcional (D12); se for usado, validar o português com o conjunto dourado.
