from __future__ import annotations

import learning


def test_confirmations_are_described_as_such():
    text = learning._format_corrections([
        {"field": "invoice_number", "old_value": "A1", "new_value": "A1", "kind": "confirmation"},
        {"field": "invoice_date", "old_value": "2026-01-02", "new_value": "2026-02-01", "kind": "correction"}])
    assert 'valeur "A1" signalée douteuse, confirmée exacte' in text
    assert 'extrait "2026-01-02" -> corrige en "2026-02-01"' in text


def test_rule_prompt_explains_confirmations():
    assert "confirmation" in learning.RULE_SYSTEM_PROMPT
