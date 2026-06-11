"""Phase 2 eval harness — measure extraction quality against ground_truth.json.

Three scorecards in one report:
  1. Term-presence: did the extractor find each (term_type, source_document) the
     ground truth lists? → precision / recall / F1.
  2. Parameter accuracy: of matched terms, do the parameter values agree within
     tolerance? Reported as a separate breakdown.
  3. Ambiguity & cross-reference: did the planted test signals (REBATE ambiguity
     flag, CROSS_REFERENCE to the Warrant Agreement, "only Doc A" unresolved
     fixture) match exactly?

Numeric tolerance: max(1, 0.01 * |truth|) — accommodates 1% formatting drift
(e.g., $25,000 vs 25_000.00) while catching real errors.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from deal_copilot.schemas import CommercialTerm, TermType
from deal_copilot.term_extractor import ExtractionResult


# Keys whose string values should be compared by case-insensitive substring,
# not strict equality. These are short labels where "annual" should match
# "annual_in_arrears" etc.
_STRING_SUBSTRING_KEYS = {"settlement_cadence", "measurement_basis"}


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------


TermOutcome = Literal["matched", "wrong_doc", "missed", "extra"]
ParamAccuracy = Literal["all_match", "partial", "none", "n/a"]


class ParameterDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    predicted: Any | None
    expected: Any | None
    why: str


class TermVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term_type: TermType
    source_document_stem: str
    outcome: TermOutcome
    parameter_accuracy: ParamAccuracy
    parameter_diffs: list[ParameterDiff] = Field(default_factory=list)
    matched_keys: int = 0
    total_truth_keys: int = 0


class PerTypeMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term_type: TermType
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    parameter_accurate_tp: int = Field(
        description="Subset of tp where parameter_accuracy == 'all_match'."
    )


class EvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_precision: float
    overall_recall: float
    overall_f1: float
    overall_tp: int
    overall_fp: int
    overall_fn: int
    per_type: list[PerTypeMetric]
    term_verdicts: list[TermVerdict]

    ambiguity_tp: int = 0
    ambiguity_fp: int = 0
    ambiguity_fn: int = 0
    rebate_ambiguity_quantified: bool = False

    cross_ref_warrant_detected: bool = False
    cross_ref_unresolved_fixture_passes: bool | None = Field(
        default=None,
        description="None when the doc-A-only fixture wasn't evaluated separately. "
                    "True/False after running the second extraction pass on Doc A alone.",
    )

    def passes_acceptance(self, threshold: float = 0.85) -> bool:
        """Smoke acceptance per Phase 2 plan."""
        return (
            self.overall_precision >= threshold
            and self.overall_recall >= threshold
            and self.rebate_ambiguity_quantified
            and self.cross_ref_warrant_detected
        )


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _stem(filename: str) -> str:
    return Path(filename).stem.lower()


def _numeric_tolerance(truth: float) -> float:
    return max(1.0, 0.01 * abs(truth))


def _values_match(key: str, predicted: Any, expected: Any) -> tuple[bool, str]:
    """Compare one (key, predicted, expected) pair per the matching policy.

    Returns (match, reason). `reason` describes the disagreement when match=False.
    """
    # Bool first because bool is a subclass of int.
    if isinstance(expected, bool):
        if not isinstance(predicted, bool):
            return False, f"expected bool, got {type(predicted).__name__}"
        return predicted == expected, "" if predicted == expected else "bool mismatch"

    if isinstance(expected, (int, float)):
        if not isinstance(predicted, (int, float)) or isinstance(predicted, bool):
            return False, f"expected numeric, got {type(predicted).__name__}"
        if expected == 0:
            ok = predicted == 0
            return ok, "" if ok else f"expected 0, got {predicted}"
        tol = _numeric_tolerance(float(expected))
        diff = abs(float(predicted) - float(expected))
        ok = diff <= tol
        return ok, "" if ok else f"|{predicted} - {expected}| = {diff:.4f} > tol={tol:.4f}"

    if isinstance(expected, str):
        if not isinstance(predicted, str):
            return False, f"expected string, got {type(predicted).__name__}"
        if key in _STRING_SUBSTRING_KEYS:
            ok = expected.lower() in predicted.lower() or predicted.lower() in expected.lower()
            return ok, "" if ok else f"neither substring of the other ({predicted!r}, {expected!r})"
        ok = predicted.lower() == expected.lower()
        return ok, "" if ok else f"strings differ ({predicted!r} vs {expected!r})"

    if isinstance(expected, list):
        if not isinstance(predicted, list):
            return False, f"expected list, got {type(predicted).__name__}"
        if len(predicted) != len(expected):
            return False, f"list length {len(predicted)} != {len(expected)}"
        for i, (p, e) in enumerate(zip(predicted, expected)):
            ok, reason = _values_match(f"{key}[{i}]", p, e)
            if not ok:
                return False, f"index {i}: {reason}"
        return True, ""

    if isinstance(expected, dict):
        if not isinstance(predicted, dict):
            return False, f"expected dict, got {type(predicted).__name__}"
        for k, ev in expected.items():
            pv = predicted.get(k)
            if pv is None and ev is not None:
                return False, f"key '{k}' missing"
            ok, reason = _values_match(k, pv, ev)
            if not ok:
                return False, f"key '{k}': {reason}"
        return True, ""

    if expected is None:
        ok = predicted is None
        return ok, "" if ok else f"expected None, got {predicted!r}"

    # Fallback: exact equality
    ok = predicted == expected
    return ok, "" if ok else f"!= {expected!r}"


def _parameter_accuracy(
    predicted_params: dict[str, Any],
    expected_params: dict[str, Any],
) -> tuple[ParamAccuracy, list[ParameterDiff], int, int]:
    """Score parameter-level agreement for one matched term.

    Returns (label, diffs, matched_keys, total_truth_keys).
    """
    diffs: list[ParameterDiff] = []
    matched = 0
    for k, ev in expected_params.items():
        pv = predicted_params.get(k)
        if pv is None and ev is not None:
            diffs.append(ParameterDiff(key=k, predicted=None, expected=ev, why="key missing in prediction"))
            continue
        ok, reason = _values_match(k, pv, ev)
        if ok:
            matched += 1
        else:
            diffs.append(ParameterDiff(key=k, predicted=pv, expected=ev, why=reason))

    total = len(expected_params)
    if total == 0:
        return "n/a", diffs, 0, 0
    if matched == total:
        return "all_match", diffs, matched, total
    if matched > 0:
        return "partial", diffs, matched, total
    return "none", diffs, matched, total


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def _find_match(
    predicted_terms: list[CommercialTerm],
    truth_term_type: TermType,
    truth_doc_stem: str,
) -> CommercialTerm | None:
    """Return the first prediction matching (term_type, doc stem), or None."""
    for p in predicted_terms:
        if p.term_type == truth_term_type and _stem(p.source_document) == truth_doc_stem:
            return p
    return None


def evaluate(
    extraction: ExtractionResult,
    ground_truth_path: Path,
) -> EvalReport:
    """Score an extraction against ground_truth.json."""
    gt = json.loads(ground_truth_path.read_text(encoding="utf-8"))

    expected_terms = gt.get("expected_terms", [])
    # Each truth entry: term_type, source_document, parameters, ambiguity_flag
    truth_keys: set[tuple[TermType, str]] = set()
    truth_lookup: dict[tuple[TermType, str], dict] = {}
    for t in expected_terms:
        tt = TermType(t["term_type"])
        stem = _stem(t["source_document"])
        truth_keys.add((tt, stem))
        truth_lookup[(tt, stem)] = t

    predicted_terms = extraction.package.terms

    verdicts: list[TermVerdict] = []
    tp_by_type: dict[TermType, int] = {}
    fp_by_type: dict[TermType, int] = {}
    fn_by_type: dict[TermType, int] = {}
    accurate_by_type: dict[TermType, int] = {}

    def _bump(d: dict[TermType, int], k: TermType, v: int = 1) -> None:
        d[k] = d.get(k, 0) + v

    # Iterate truth entries → determine matched / wrong_doc / missed
    for (tt, stem), truth in truth_lookup.items():
        prediction = _find_match(predicted_terms, tt, stem)
        if prediction is not None:
            # matched
            outcome: TermOutcome = "matched"
            acc, diffs, matched_keys, total_keys = _parameter_accuracy(
                prediction.parameters, truth.get("parameters", {})
            )
            verdicts.append(TermVerdict(
                term_type=tt, source_document_stem=stem, outcome=outcome,
                parameter_accuracy=acc, parameter_diffs=diffs,
                matched_keys=matched_keys, total_truth_keys=total_keys,
            ))
            _bump(tp_by_type, tt)
            if acc == "all_match":
                _bump(accurate_by_type, tt)
        else:
            # Distinguish wrong_doc vs missed
            same_type_anywhere = any(p.term_type == tt for p in predicted_terms)
            outcome = "wrong_doc" if same_type_anywhere else "missed"
            verdicts.append(TermVerdict(
                term_type=tt, source_document_stem=stem, outcome=outcome,
                parameter_accuracy="n/a", parameter_diffs=[],
            ))
            _bump(fn_by_type, tt)

    # Now find extras (predictions whose key isn't in truth)
    seen_pred_keys: set[tuple[TermType, str]] = set()
    for p in predicted_terms:
        key = (p.term_type, _stem(p.source_document))
        if key in seen_pred_keys:
            continue
        seen_pred_keys.add(key)
        if key not in truth_keys:
            verdicts.append(TermVerdict(
                term_type=p.term_type, source_document_stem=_stem(p.source_document),
                outcome="extra", parameter_accuracy="n/a", parameter_diffs=[],
            ))
            _bump(fp_by_type, p.term_type)

    # Per-type metrics
    all_types = set(tp_by_type) | set(fp_by_type) | set(fn_by_type)
    per_type: list[PerTypeMetric] = []
    for tt in sorted(all_types, key=lambda x: x.value):
        tp = tp_by_type.get(tt, 0)
        fp = fp_by_type.get(tt, 0)
        fn = fn_by_type.get(tt, 0)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        per_type.append(PerTypeMetric(
            term_type=tt, tp=tp, fp=fp, fn=fn,
            precision=precision, recall=recall, f1=f1,
            parameter_accurate_tp=accurate_by_type.get(tt, 0),
        ))

    overall_tp = sum(tp_by_type.values())
    overall_fp = sum(fp_by_type.values())
    overall_fn = sum(fn_by_type.values())
    overall_precision = overall_tp / (overall_tp + overall_fp) if (overall_tp + overall_fp) > 0 else 0.0
    overall_recall = overall_tp / (overall_tp + overall_fn) if (overall_tp + overall_fn) > 0 else 0.0
    overall_f1 = (
        2 * overall_precision * overall_recall / (overall_precision + overall_recall)
        if (overall_precision + overall_recall) > 0 else 0.0
    )

    # ----- Ambiguity scorecard -----
    truth_amb_keys = {
        (TermType(t["term_type"]), _stem(t["source_document"]))
        for t in expected_terms
        if t.get("ambiguity_flag")
    }
    pred_amb_keys = {
        (p.term_type, _stem(p.source_document))
        for p in predicted_terms
        if p.ambiguity_flag
    }
    ambiguity_tp = len(truth_amb_keys & pred_amb_keys)
    ambiguity_fn = len(truth_amb_keys - pred_amb_keys)
    ambiguity_fp = len(pred_amb_keys - truth_amb_keys)

    rebate_predictions = [p for p in predicted_terms if p.term_type == TermType.REBATE]
    rebate_ambiguity_quantified = any(
        p.ambiguity_flag and len(p.variants) >= 2 for p in rebate_predictions
    )

    # ----- Cross-reference scorecard -----
    cross_ref_warrant_detected = any(
        p.term_type == TermType.CROSS_REFERENCE
        and "warrant" in str(p.parameters.get("referenced_document_label", "")).lower()
        for p in predicted_terms
    )

    return EvalReport(
        overall_precision=overall_precision,
        overall_recall=overall_recall,
        overall_f1=overall_f1,
        overall_tp=overall_tp,
        overall_fp=overall_fp,
        overall_fn=overall_fn,
        per_type=per_type,
        term_verdicts=verdicts,
        ambiguity_tp=ambiguity_tp,
        ambiguity_fp=ambiguity_fp,
        ambiguity_fn=ambiguity_fn,
        rebate_ambiguity_quantified=rebate_ambiguity_quantified,
        cross_ref_warrant_detected=cross_ref_warrant_detected,
    )


def evaluate_cross_ref_only_doc_a(
    extraction_only_doc_a: ExtractionResult,
    ground_truth_path: Path,
) -> bool:
    """Verify the 'only Doc A uploaded' fixture: unresolved_cross_references
    must contain 'Warrant Agreement' (case-insensitive, allowing for label
    variations)."""
    gt = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    expected = gt.get("expected_unresolved_cross_references_when_only_doc_a_uploaded", [])
    if not expected:
        return False
    expected_label = expected[0].get("referenced_label", "").lower()
    actual = [s.lower() for s in extraction_only_doc_a.package.unresolved_cross_references]
    return any(expected_label in a or a in expected_label for a in actual)


__all__ = [
    "TermOutcome",
    "ParamAccuracy",
    "ParameterDiff",
    "TermVerdict",
    "PerTypeMetric",
    "EvalReport",
    "evaluate",
    "evaluate_cross_ref_only_doc_a",
]
