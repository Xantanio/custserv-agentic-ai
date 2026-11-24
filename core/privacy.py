"""Mascaramento de dados pessoais (LGPD, guardrail 11 do CLAUDE.md).

Aplicado a todo texto livre de cliente que sai para um LLM, para logs ou para
auditoria. Regex determinística e testável; cobre formatos brasileiros comuns.
Limitação conhecida: nomes próprios NÃO são mascarados (exigiria NER).
Seriais (`SN-XX-000000`) e IDs de pedido não são dados pessoais e são preservados.
"""

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
# +55 (11) 98765-4321 · (11) 98765-4321 · 11987654321 · +5511987654321 · 98765-4321
_PHONE = re.compile(
    r"(?<![\w-])(?:\+?55[\s-]?)?(?:\(?\d{2}\)?[\s-]?)?9?\d{4}[\s-]?\d{4}(?![\w-])"
)


def mask_pii(text: str) -> str:
    """Substitui e-mail, CPF e telefone por marcadores. A ordem importa: CPF antes de telefone."""
    text = _EMAIL.sub("[EMAIL]", text)
    text = _CPF.sub("[CPF]", text)
    text = _PHONE.sub("[TELEFONE]", text)
    return text
