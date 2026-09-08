"""OCR fidelity metric functions (T012) — make benchmarks/ocr/test_metrics.py pass.

All functions are pure and deterministic. Error-rate metrics (``cer``,
``table_cell_cer``, insertion/deletion rates) are *lower is better*; the rest are
*higher is better*. ``weighted_total`` folds a per-metric dict into a single
0-1 "fidelity" score (higher = better) for the T013 selection rule.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

import jiwer

_NUM_RE = re.compile(r"R\$|US\$|€|£|\d+x\b|\d[\d.,]*%?")


# --------------------------------------------------------------------------------------
# Character / word error
# --------------------------------------------------------------------------------------

def cer(ref: str, hyp: str) -> float:
    ref, hyp = ref or "", hyp or ""
    if not ref and not hyp:
        return 0.0
    if not ref:
        return 1.0
    return float(jiwer.cer(ref, hyp))


def insertion_deletion_rates(ref: str, hyp: str) -> tuple[float, float]:
    ref_words = (ref or "").split()
    if not ref_words:
        return (0.0, 0.0)
    out = jiwer.process_words(ref, hyp)
    n = len(ref_words)
    return (out.insertions / n, out.deletions / n)


# --------------------------------------------------------------------------------------
# Numeric / monetary fidelity
# --------------------------------------------------------------------------------------

def numeric_token_exact_match(ref: str, hyp: str) -> float:
    ref_toks = Counter(_NUM_RE.findall(ref or ""))
    if not ref_toks:
        return 1.0
    hyp_toks = Counter(_NUM_RE.findall(hyp or ""))
    matched = sum(min(c, hyp_toks.get(t, 0)) for t, c in ref_toks.items())
    return matched / sum(ref_toks.values())


# --------------------------------------------------------------------------------------
# Diacritic fidelity
# --------------------------------------------------------------------------------------

def _accented_chars(s: str) -> list[str]:
    out = []
    for ch in s or "":
        nfd = unicodedata.normalize("NFD", ch)
        if any(unicodedata.combining(c) for c in nfd):
            out.append(ch)
    return out


def diacritic_accuracy(ref: str, hyp: str) -> float:
    ref_acc = Counter(_accented_chars(ref))
    if not ref_acc:
        return 1.0
    hyp_acc = Counter(_accented_chars(hyp))
    kept = sum(min(c, hyp_acc.get(ch, 0)) for ch, c in ref_acc.items())
    return kept / sum(ref_acc.values())


# --------------------------------------------------------------------------------------
# Table-cell fidelity
# --------------------------------------------------------------------------------------

def table_cell_cer(ref_cells: list[str], hyp_cells: list[str]) -> float:
    ref_cells = list(ref_cells or [])
    hyp_cells = list(hyp_cells or [])
    if not ref_cells:
        return 0.0
    n = max(len(ref_cells), len(hyp_cells))
    total = 0.0
    for i in range(n):
        r = ref_cells[i] if i < len(ref_cells) else ""
        h = hyp_cells[i] if i < len(hyp_cells) else ""
        total += cer(r, h)
    return total / n


# --------------------------------------------------------------------------------------
# Reading order
# --------------------------------------------------------------------------------------

def reading_order_kendall_tau(ref_order: list, hyp_order: list) -> float:
    ref_order = list(ref_order)
    hyp_order = list(hyp_order)
    rank = {v: i for i, v in enumerate(ref_order)}
    seq = [rank[v] for v in hyp_order if v in rank]
    n = len(seq)
    if n < 2:
        return 1.0
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            d = seq[i] - seq[j]
            if d < 0:
                concordant += 1
            elif d > 0:
                discordant += 1
    denom = n * (n - 1) / 2
    return (concordant - discordant) / denom


# --------------------------------------------------------------------------------------
# Language detection
# --------------------------------------------------------------------------------------

def language_detection_accuracy(pairs: list[tuple[str, str]]) -> float:
    pairs = list(pairs or [])
    if not pairs:
        return 0.0
    return sum(1 for pred, true in pairs if pred == true) / len(pairs)


# --------------------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------------------

_WEIGHTS = {
    "cer": 0.30,
    "numeric_token_exact_match": 0.15,
    "diacritic_accuracy": 0.15,
    "table_cell_cer": 0.10,
    "reading_order_kendall_tau": 0.10,
    "insertion_rate": 0.05,
    "deletion_rate": 0.05,
    "language_detection_accuracy": 0.10,
}
_ERROR_RATE = {"cer", "table_cell_cer", "insertion_rate", "deletion_rate"}


def _goodness(name: str, value: float) -> float:
    if name in _ERROR_RATE:
        return max(0.0, 1.0 - min(1.0, value))
    if name == "reading_order_kendall_tau":
        return (max(-1.0, min(1.0, value)) + 1.0) / 2.0
    return max(0.0, min(1.0, value))


def weighted_total(per_metric: dict[str, float]) -> float:
    num = den = 0.0
    for name, weight in _WEIGHTS.items():
        if name not in per_metric:
            continue
        num += weight * _goodness(name, per_metric[name])
        den += weight
    if den == 0.0:
        return 0.0
    return max(0.0, min(1.0, num / den))


# --------------------------------------------------------------------------------------
# Per-language aggregation + the AUTHORITATIVE per-language acceptance floor
# --------------------------------------------------------------------------------------
# The thresholds and applicability rules below are the single normative copy of
# research.md §4.1 "Per-language acceptance floor (v1)". Nothing else in the repo
# restates the numbers — task text and RESULTS.md reference this constant.

LANGUAGE_ACCEPTANCE_FLOOR: dict[str, float] = {
    "weighted_total_min": 0.80,             # criterion 1 — per-language weighted fidelity
    "cer_max": 0.20,                        # criterion 2 — character error rate
    "diacritic_accuracy_min": 0.90,         # criterion 3 — diacritic slices only (PT/ES)
    "numeric_token_exact_match_min": 0.95,  # criterion 4 — numeric/monetary slices only
}

#: primary benchmark languages (spec Clarifications 2026-09-07); everything else
#: (incl. the FR/IT/DE ``latin_coverage`` page, language ``mul``) is excluded from
#: per-language aggregation and from the engine-selection floor.
PRIMARY_LANGUAGES: tuple[str, ...] = ("pt", "en", "es")


def _mean(xs: list[float]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def text_has_diacritics(text: str) -> bool:
    """True iff ``text`` carries at least one combining-mark character — i.e. the
    slice has diacritic ground truth and §4.1 criterion 3 applies."""
    return bool(_accented_chars(text))


def text_has_numeric_tokens(text: str) -> bool:
    """True iff ``text`` carries a numeric / monetary token — i.e. §4.1 criterion
    4 applies to the slice."""
    return bool(_NUM_RE.search(text or ""))


def per_language_aggregate(pages: list[dict]) -> dict[str, dict[str, float]]:
    """Bucket ``pages`` by language and mean every metric per bucket.

    Each page is ``{"language": str, "scored": bool, "metrics": {name: value}}``.
    Only ``scored`` pages whose language is a primary benchmark language are
    counted. Each bucket gains a ``weighted_total`` computed from its mean metrics.
    """
    buckets: dict[str, list[dict[str, float]]] = {}
    for page in pages:
        if not page.get("scored", True):
            continue
        lang = page["language"]
        if lang not in PRIMARY_LANGUAGES:
            continue
        buckets.setdefault(lang, []).append(page["metrics"])

    out: dict[str, dict[str, float]] = {}
    for lang, metric_dicts in buckets.items():
        keys = set().union(*(m.keys() for m in metric_dicts))
        agg = {k: _mean([m[k] for m in metric_dicts if k in m]) for k in keys}
        agg["weighted_total"] = weighted_total(agg)
        out[lang] = agg
    return out


def evaluate_language_floor(
    aggregate: dict[str, float],
    *,
    diacritic_applicable: bool,
    numeric_applicable: bool,
) -> dict:
    """Deterministic PASS/FAIL of one language's aggregate against the §4.1 floor.

    Returns ``{"pass": bool, "criteria": {name: {"applicable", "value",
    "threshold", "pass"}}}``. A non-applicable criterion has ``value``/``pass`` =
    ``None`` and does not affect the overall ``pass``. Comparisons are inclusive
    at the boundary (``>=`` / ``<=``).
    """
    f = LANGUAGE_ACCEPTANCE_FLOOR
    criteria: dict[str, dict] = {}

    def record(
        name: str, applicable: bool, value: float | None, threshold: float, ok: bool
    ) -> None:
        criteria[name] = {
            "applicable": applicable,
            "value": value if applicable else None,
            "threshold": threshold,
            "pass": ok if applicable else None,
        }

    wt = aggregate.get("weighted_total", 0.0)
    cer_v = aggregate.get("cer", 1.0)
    dia_v = aggregate.get("diacritic_accuracy", 0.0)
    num_v = aggregate.get("numeric_token_exact_match", 0.0)

    record("weighted_total", True, wt, f["weighted_total_min"], wt >= f["weighted_total_min"])
    record("cer", True, cer_v, f["cer_max"], cer_v <= f["cer_max"])
    record(
        "diacritic_accuracy", diacritic_applicable, dia_v,
        f["diacritic_accuracy_min"], dia_v >= f["diacritic_accuracy_min"],
    )
    record(
        "numeric_token_exact_match", numeric_applicable, num_v,
        f["numeric_token_exact_match_min"], num_v >= f["numeric_token_exact_match_min"],
    )

    passed = all(c["pass"] for c in criteria.values() if c["applicable"])
    return {"pass": passed, "criteria": criteria}


def language_regression_flags(evaluations: dict[str, dict]) -> dict[str, bool]:
    """``{language: True}`` when the engine is *materially worse* for that primary
    language — i.e. it fails one or more **applicable** §4.1 floor criteria.

    Absolute by construction: the flag is a function of one engine's own
    evaluation only; it is never computed relative to the competing engine.
    """
    return {lang: (not ev["pass"]) for lang, ev in evaluations.items()}
