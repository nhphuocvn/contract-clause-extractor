"""Deal versioning and the change journal — the audit/governance backbone of the
negotiation core.

A deal is renegotiated repeatedly; each round is captured as a named, timestamped
`DealVersion` snapshot of the working state (terms, warrant, assumptions, ad-hoc
drivers). Versions are append-only — re-extracting or editing never mutates a
prior snapshot — so any two can be compared by the variance bridge.

The change journal records, edit by edit, what changed between two versions
(timestamp, field path, old value, new value), feeding both the per-version
history and the Excel Changelog tab. It reuses `variance_bridge.diff_changes` so
the journal and the bridge describe changes with the same lever vocabulary.

Pure module: callers supply timestamps (deterministic under tests); functions
never mutate their inputs.
"""

from __future__ import annotations

from datetime import datetime

from deal_copilot.schemas import (
    ChangeJournalEntry,
    DealAssumptions,
    DealPackage,
    DealVersion,
)
from deal_copilot.variance_bridge import diff_changes


def snapshot_version(
    pkg: DealPackage,
    assumptions: DealAssumptions,
    name: str,
    created_at: datetime,
    note: str = "",
) -> DealVersion:
    """Deep-copy the current working state into a named `DealVersion`.

    Assumptions live outside the package (the engine takes them separately), so
    they are passed in explicitly. Everything is deep-copied so later edits to
    the package or assumptions cannot reach back into the snapshot."""
    return DealVersion(
        name=name,
        created_at=created_at,
        terms=[t.model_copy(deep=True) for t in pkg.terms],
        warrant_terms=pkg.warrant_terms.model_copy(deep=True) if pkg.warrant_terms else None,
        assumptions=assumptions.model_copy(deep=True),
        ad_hoc_drivers=[d.model_copy(deep=True) for d in pkg.ad_hoc_drivers],
        note=note,
    )


def append_version(pkg: DealPackage, version: DealVersion) -> DealPackage:
    """Return a copy of `pkg` with `version` appended to its history. Append-only:
    the input package and all prior versions are left untouched."""
    new_pkg = pkg.model_copy(deep=True)
    new_pkg.versions = list(new_pkg.versions) + [version.model_copy(deep=True)]
    return new_pkg


def build_change_journal(
    old_version: DealVersion,
    new_version: DealVersion,
    timestamp: datetime,
    actor: str = "",
) -> list[ChangeJournalEntry]:
    """One `ChangeJournalEntry` per field that changed from `old_version` to
    `new_version`, using the same structured diff as the variance bridge."""
    entries: list[ChangeJournalEntry] = []
    for ch in diff_changes(old_version, new_version):
        entries.append(ChangeJournalEntry(
            timestamp=timestamp,
            field_path=ch.field_path,
            old_value=ch.old_value,
            new_value=ch.new_value,
            note=ch.label,
            actor=actor,
        ))
    return entries


__all__ = ["snapshot_version", "append_version", "build_change_journal"]
