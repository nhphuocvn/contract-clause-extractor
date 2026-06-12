"""Deal versioning + change journal.

Versions are append-only deep snapshots; the change journal records one entry per
changed field with correct old/new values.
"""

from __future__ import annotations

from datetime import datetime

from deal_copilot.schemas import TermType
from deal_copilot.versioning import append_version, build_change_journal, snapshot_version
from tests.fixtures import default_assumptions, synthetic_package

T0 = datetime(2026, 6, 11)
T1 = datetime(2026, 6, 12)


def _pricing(pkg):
    return next(t for t in pkg.terms if t.term_type == TermType.PRICING)


def test_snapshot_is_deep_and_independent():
    pkg, a = synthetic_package(), default_assumptions()
    vA = snapshot_version(pkg, a, "Counterparty initial", T0)
    # Mutate the working state after snapshotting.
    _pricing(pkg).parameters["base_asp_usd"] = 26000
    a2 = a.model_copy(update={"unit_cogs_usd": 16000.0})
    # The snapshot is untouched.
    assert _pricing_value(vA) == 25000
    assert vA.assumptions.unit_cogs_usd == 15000.0
    assert a2.unit_cogs_usd == 16000.0  # the new working assumptions did change


def _pricing_value(version):
    return next(t for t in version.terms if t.term_type == TermType.PRICING).parameters["base_asp_usd"]


def test_append_version_is_append_only():
    pkg, a = synthetic_package(), default_assumptions()
    v1 = snapshot_version(pkg, a, "v1", T0)
    pkg2 = append_version(pkg, v1)
    assert len(pkg.versions) == 0          # original untouched
    assert len(pkg2.versions) == 1
    v2 = snapshot_version(pkg2, a, "v2", T1)
    pkg3 = append_version(pkg2, v2)
    assert [v.name for v in pkg3.versions] == ["v1", "v2"]
    assert len(pkg2.versions) == 1         # pkg2 untouched by the second append


def test_change_journal_records_each_changed_field():
    pkg, a = synthetic_package(), default_assumptions()
    vA = snapshot_version(pkg, a, "A", T0)

    pkgB = pkg.model_copy(deep=True)
    next(t for t in pkgB.terms if t.term_type == TermType.PRICING).parameters["base_asp_usd"] = 26000
    aB = a.model_copy(update={"unit_cogs_usd": 16000.0})
    vB = snapshot_version(pkgB, aB, "B", T1)

    entries = build_change_journal(vA, vB, T1, actor="analyst@firm")
    by_path = {e.field_path: e for e in entries}
    assert "terms[PRICING].base_asp_usd" in by_path
    assert by_path["terms[PRICING].base_asp_usd"].old_value == 25000
    assert by_path["terms[PRICING].base_asp_usd"].new_value == 26000
    assert "assumptions.unit_cogs_usd" in by_path
    assert by_path["assumptions.unit_cogs_usd"].old_value == 15000.0
    assert by_path["assumptions.unit_cogs_usd"].new_value == 16000.0
    assert all(e.actor == "analyst@firm" and e.timestamp == T1 for e in entries)


def test_change_journal_empty_when_identical():
    pkg, a = synthetic_package(), default_assumptions()
    vA = snapshot_version(pkg, a, "A", T0)
    vA2 = snapshot_version(pkg, a, "A-again", T1)
    assert build_change_journal(vA, vA2, T1) == []
