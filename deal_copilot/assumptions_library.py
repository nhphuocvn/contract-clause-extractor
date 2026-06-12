"""Assumptions-library loader.

This is the ONLY module in the engine stack that performs file I/O. It reads
`data/assumptions_library.json` and constructs a populated `DealAssumptions`
plus a parallel provenance map. Everything downstream (driver_mapper,
economics_engine, accounting_schedules) is a pure function of an already-built
`DealAssumptions` — so the engine stays deterministic and trivially testable,
and Monte Carlo / goal-seek become thin layers later.

Each JSON entry has the shape `{value, basis_class, note, as_of}`:
- `basis_class` maps to `ProvenanceClass` (almost always LIBRARY_DEFAULT here);
- `note` is the free-text source/basis citation surfaced in UI and Excel;
- `as_of` is an ISO date string recording when the value was set.

`build_default_assumptions` takes a caller-supplied `as_of` timestamp for the
`AssumptionProvenance.as_of` fields rather than calling `datetime.now()`, so the
output is deterministic under tests and a persistence layer controls the clock.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from deal_copilot.schemas import (
    AssumptionProvenance,
    DealAssumptions,
    ProvenanceClass,
)

DEFAULT_LIBRARY_PATH = Path("data/assumptions_library.json")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_library(path: str | Path = DEFAULT_LIBRARY_PATH) -> dict[str, Any]:
    """Read and parse the assumptions library JSON. Cached per resolved path."""
    return _load_cached(str(Path(path).resolve()))


@lru_cache(maxsize=8)
def _load_cached(resolved_path: str) -> dict[str, Any]:
    with open(resolved_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _entry_value(entry: dict[str, Any]) -> Any:
    """Pull the scalar value out of a `{value, basis_class, note, as_of}` entry."""
    return entry["value"]


def _provenance(entry: dict[str, Any], as_of: datetime) -> AssumptionProvenance:
    """Build an AssumptionProvenance from a library entry.

    `as_of` on the returned provenance is the caller-supplied recording time;
    the entry's own `as_of` date is folded into the note so the original
    library timestamp is not lost.
    """
    try:
        basis = ProvenanceClass(entry.get("basis_class", "LIBRARY_DEFAULT"))
    except ValueError:
        basis = ProvenanceClass.LIBRARY_DEFAULT
    note = entry.get("note", "")
    lib_as_of = entry.get("as_of")
    if lib_as_of:
        note = f"{note} (library as_of {lib_as_of})" if note else f"library as_of {lib_as_of}"
    return AssumptionProvenance(
        value=entry["value"], basis=basis, note=note, as_of=as_of
    )


# ---------------------------------------------------------------------------
# Building a DealAssumptions from the library
# ---------------------------------------------------------------------------


def build_default_assumptions(
    library: dict[str, Any], as_of: datetime
) -> tuple[DealAssumptions, dict[str, AssumptionProvenance]]:
    """Construct a `DealAssumptions` from library globals plus a parallel
    provenance map keyed by the assumption's attribute name.

    Only the scalar globals consumed by the Phase 3 engine are mapped. The
    per-generation defaults live under `library["generations"]` and are read
    directly by multi-generation modeling (deferred P1); they are not folded
    into the scalar `DealAssumptions` here.
    """
    g = library["globals"]

    assumptions = DealAssumptions(
        unit_cogs_usd=_entry_value(g["unit_cogs_usd"]),
        opex_allocation_pct=_entry_value(g["opex_allocation_pct"]),
        discount_rate_wacc=_entry_value(g["wacc"]),
        tax_rate=_entry_value(g["tax_rate"]),
        current_stock_price_usd=_entry_value(g["current_stock_price_usd"]),
        assumed_volatility=_entry_value(g["assumed_volatility"]),
    )

    # Parallel provenance map, keyed by DealAssumptions attribute name.
    provenance: dict[str, AssumptionProvenance] = {
        "unit_cogs_usd": _provenance(g["unit_cogs_usd"], as_of),
        "opex_allocation_pct": _provenance(g["opex_allocation_pct"], as_of),
        "discount_rate_wacc": _provenance(g["wacc"], as_of),
        "tax_rate": _provenance(g["tax_rate"], as_of),
        "current_stock_price_usd": _provenance(g["current_stock_price_usd"], as_of),
        "assumed_volatility": _provenance(g["assumed_volatility"], as_of),
    }

    return assumptions, provenance


def dso_for_payment_terms(
    library: dict[str, Any], net_days: int | None, default: int = 60
) -> int:
    """Resolve days-sales-outstanding for the cash view.

    Prefers an exact `net_<n>` key in the library's payment-terms map; falls
    back to the supplied `net_days` itself, then to `default`. Keeps the engine
    free of any payment-terms lookup table.
    """
    dso_map = _entry_value(library["globals"]["payment_terms_dso_map"])
    if net_days is not None:
        key = f"net_{int(net_days)}"
        if key in dso_map:
            return int(dso_map[key])
        return int(net_days)
    return default


__all__ = [
    "DEFAULT_LIBRARY_PATH",
    "load_library",
    "build_default_assumptions",
    "dso_for_payment_terms",
]
