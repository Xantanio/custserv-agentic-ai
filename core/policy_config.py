"""Limiares e parâmetros da política determinística (CLAUDE.md 7.2).

Ficam aqui, e não espalhados pelo código, para que sejam revisáveis, testáveis
e auditáveis (o `rule_id` de cada regra aponta para cá). Valores iniciais, a calibrar.
A Etapa 7 acrescenta os limiares de classificação e as listas de palavras-chave.
"""

from decimal import Decimal

# Taxa de falha do lote a partir da qual há contenção (bloqueio, alertas, especialista).
# Decimal: limiar exato, sem depender de arredondamento de ponto flutuante.
BATCH_FAILURE_RATE_CRITICAL = Decimal("0.50")
RULE_BATCH_CRITICAL = "batch.failure_rate.critical_v1"
