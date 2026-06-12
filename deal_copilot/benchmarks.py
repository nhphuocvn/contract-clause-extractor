"""Benchmarks (§9.2 / §9.5) — compare a deal's key terms to portfolio/industry
medians and produce the CRB memo's benchmark sentences.

`load_benchmarks` is the only I/O (cached per path); `compare_to_benchmarks`
and `deal_benchmark_metrics` are pure. Graceful degradation: a missing file
yields an empty list (labeled absence, not a crash), and a benchmark more than
two quarters old is flagged stale so the memo never quotes a stale figure as
current.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from deal_copilot import driver_mapper as dm
from deal_copilot.schemas import (
    Benchmark,
    BenchmarkComparison,
    DealEconomics,
    DealPackage,
    ScenarioName,
    TermType,
    ViewMode,
)

DEFAULT_BENCHMARKS_PATH = Path("data/benchmarks.json")
STALE_AFTER_DAYS = 183     # ~2 quarters; benchmarks older than this are flagged stale

# metric -> (human label, lower_is_better). Determines the "better/worse" wording.
_METRIC_META: dict[str, tuple[str, bool]] = {
    "blended_gross_margin_pct": ("blended gross margin", False),
    "rebate_pct_of_revenue": ("rebate as % of revenue", True),
    "payment_terms_net_days": ("payment terms", True),
    "take_or_pay_pct": ("take-or-pay floor", False),
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_benchmarks(path: str | Path = DEFAULT_BENCHMARKS_PATH) -> list[Benchmark]:
    """Read the benchmark list. Returns `[]` if the file is absent (labeled
    absence — the comparison layer reports `benchmark_present=False`)."""
    resolved = str(Path(path).resolve())
    try:
        raw = _load_cached(resolved)
    except FileNotFoundError:
        return []
    return [Benchmark(**b) for b in raw]


@lru_cache(maxsize=8)
def _load_cached(resolved_path: str) -> tuple[dict, ...]:
    with open(resolved_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return tuple(data.get("benchmarks", []))


# ---------------------------------------------------------------------------
# Deal-side metric extraction (pure)
# ---------------------------------------------------------------------------


def _base_cash(econ: DealEconomics):
    for s in econ.scenarios:
        if s.scenario == ScenarioName.BASE and s.view == ViewMode.CASH_COMMERCIAL:
            return s
    return None


def deal_benchmark_metrics(pkg: DealPackage, econ: DealEconomics) -> dict[str, float]:
    """The deal's values for the benchmarked metrics, pulled from the economics
    output and the extracted terms. Pure."""
    metrics: dict[str, float] = {}
    base = _base_cash(econ)
    if base is not None:
        metrics["blended_gross_margin_pct"] = base.total_gross_margin_pct
        gross = sum(r.gross_revenue for r in base.quarterly_pl)
        rebates = sum(r.rebates for r in base.quarterly_pl)
        if gross:
            metrics["rebate_pct_of_revenue"] = rebates / gross

    pt = dm._first(pkg, TermType.PAYMENT_TERMS)
    net_days = pt.parameters.get("net_days") if pt is not None else None
    if isinstance(net_days, (int, float)):
        metrics["payment_terms_net_days"] = float(net_days)

    top = dm._first(pkg, TermType.TAKE_OR_PAY)
    floor = top.parameters.get("annual_minimum_pct_of_committed") if top is not None else None
    if isinstance(floor, (int, float)):
        metrics["take_or_pay_pct"] = float(floor)

    return metrics


# ---------------------------------------------------------------------------
# Comparison (pure)
# ---------------------------------------------------------------------------


def _fmt(metric: str, value: float) -> str:
    if metric.endswith("_pct") or metric.endswith("_of_revenue"):
        return f"{value * 100:.1f}%"
    if metric == "payment_terms_net_days":
        return f"net-{int(round(value))}"
    return f"{value:g}"


def _is_stale(benchmark: Benchmark, as_of: datetime) -> bool:
    return (as_of - benchmark.as_of) > timedelta(days=STALE_AFTER_DAYS)


def compare_to_benchmarks(
    deal_metrics: dict[str, float],
    benchmarks: list[Benchmark],
    as_of: datetime,
) -> list[BenchmarkComparison]:
    """One BenchmarkComparison per benchmark, with a plain-English verdict and a
    staleness flag. Metrics without a deal value are skipped; benchmarks for a
    metric the deal does not expose still produce a labeled comparison."""
    by_metric = {b.metric: b for b in benchmarks}
    out: list[BenchmarkComparison] = []
    for metric, bench in by_metric.items():
        label, lower_is_better = _METRIC_META.get(metric, (metric, False))
        deal_val = deal_metrics.get(metric)
        stale = _is_stale(bench, as_of)
        stale_tag = " (benchmark is stale — refresh before relying on it)" if stale else ""
        if deal_val is None:
            sentence = f"No deal value for {label}; portfolio benchmark is {_fmt(metric, bench.value)}.{stale_tag}"
            out.append(BenchmarkComparison(
                metric=metric, deal_value=None, benchmark_value=bench.value,
                verdict_sentence=sentence, is_stale=stale, benchmark_present=True,
            ))
            continue
        if deal_val > bench.value:
            direction = "above"
        elif deal_val < bench.value:
            direction = "below"
        else:
            direction = "in line with"
        if direction == "in line with":
            quality = "in line with"
        else:
            better = (direction == "below") if lower_is_better else (direction == "above")
            quality = "better than" if better else "worse than"
        sentence = (
            f"Deal {label} {_fmt(metric, deal_val)} is {direction} the portfolio "
            f"benchmark {_fmt(metric, bench.value)} ({quality} the median).{stale_tag}"
        )
        out.append(BenchmarkComparison(
            metric=metric, deal_value=deal_val, benchmark_value=bench.value,
            verdict_sentence=sentence, is_stale=stale, benchmark_present=True,
        ))
    return out


def benchmark_sentences(comparisons: list[BenchmarkComparison]) -> list[str]:
    """Flatten comparisons to the memo's benchmark sentence list."""
    return [c.verdict_sentence for c in comparisons]


__all__ = [
    "DEFAULT_BENCHMARKS_PATH",
    "STALE_AFTER_DAYS",
    "load_benchmarks",
    "deal_benchmark_metrics",
    "compare_to_benchmarks",
    "benchmark_sentences",
]
