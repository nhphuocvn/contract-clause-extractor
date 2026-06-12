"""Glossary coverage (§9.7): every term used in the UI/outputs must have a
non-empty one-sentence plain-English definition, and the required finance terms
must all be present (no unexplained jargon)."""

from __future__ import annotations

import pytest

from deal_copilot.glossary import load_glossary, lookup

REQUIRED = [
    "ASP", "COGS", "NPV", "WACC", "MFN", "Take-or-pay", "Contra-revenue",
    "Accrual", "Contract liability", "PUE", "DSO", "DPO", "Inventory lead",
    "Working capital", "Peak receivables", "Dilution", "Effective net ASP",
    "Banked Units", "Policy verdict", "Assumption Register", "Assumption Gap Report",
]


def test_glossary_loads_nonempty():
    g = load_glossary()
    assert len(g) >= 30


def test_required_terms_present():
    g = load_glossary()
    missing = [t for t in REQUIRED if t not in g]
    assert missing == []


def test_every_definition_is_a_nonempty_sentence():
    g = load_glossary()
    for term, definition in g.items():
        assert isinstance(definition, str) and definition.strip(), term
        assert definition.strip().endswith("."), term      # one sentence, terminated


def test_lookup_is_case_insensitive():
    assert lookup("wacc") == lookup("WACC")
    assert lookup("npv").startswith("Net present value")


def test_lookup_missing_returns_none():
    assert lookup("not_a_real_term_xyz") is None
