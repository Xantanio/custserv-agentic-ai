"""Mascaramento de dados pessoais (core/privacy.py)."""

import pytest

from core.privacy import mask_pii


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("me escreva em joao.silva+loja@gmail.com", "me escreva em [EMAIL]"),
        ("meu CPF é 123.456.789-09", "meu CPF é [CPF]"),
        ("CPF 12345678909 ok", "CPF [CPF] ok"),
        ("ligue (11) 98765-4321", "ligue [TELEFONE]"),
        ("whats +55 11 98765-4321", "whats [TELEFONE]"),
        ("tel +5511987654321.", "tel [TELEFONE]."),
        ("fixo 3456-7890", "fixo [TELEFONE]"),
    ],
)
def test_masks_personal_data(text, expected):
    assert mask_pii(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Serial SN-SW-000074.",
        "Pedido ORD-20050 do LOTE-2026-DEF",
        "parou após 2 dias, 3 vezes por semana",
        "fabricado em 2026-10-01",
    ],
)
def test_preserves_non_personal_identifiers(text):
    assert mask_pii(text) == text
