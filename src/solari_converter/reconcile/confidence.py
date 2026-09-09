"""Deterministic materiality + confidence policy for reconciliation (T057).

Pure, deterministic functions over aligned-group / candidate evidence — **no LLM, no
network, no randomness, no mutable global state** (research §21b, block brief §4–§7).

Contents
--------

* :func:`comparison_key` — the **comparison-only** normal form. Frozen operations:
  Unicode **NFC**, collapse of Unicode whitespace (incl. NBSP / CR / LF), smart-quote
  folding. Nothing else — no NFKC, no ligature expansion, no soft-hyphen removal, no
  replacement-character / mojibake / OCR / punctuation / spelling repair, no case
  folding. It is used to *compare* literals; it never rewrites a stored value.
* :func:`is_material` — the frozen materiality policy: a whitespace-only or case-only
  difference is **not material**; every other difference (digits, letters, diacritics,
  punctuation, ligatures, …) **is**.
* :data:`NATIVE_TECHNIQUE_PRECEDENCE` / :func:`preferred_technique` / :func:`pick_verbatim`
  — the M2 precedence for choosing among distinct **verbatim** candidates when their
  difference is non-material: native beats OCR; between the two native paths a fixed
  order derived from the frozen technique identifiers (``docling`` < ``pdfplumber``,
  lexicographic — deterministic, never input-iteration order). This selects among
  existing verbatim candidates; it never edits candidate text; OCR never outranks
  native evidence for a non-material difference.
* :func:`literal_confidence` / :func:`reading_order_confidence` — deterministic scores
  in ``[0, 1]`` from {agreement fraction, native-vs-OCR, character class of the diff,
  OCR confidence, Kendall-τ}. The reconciliation acceptance threshold stays
  ``Config.reconcile_confidence_threshold`` (0.75) and is applied by the **T060**
  dispatch, not here — this module only computes the number.

Thresholds/weights that the architecture does not pin are named module constants with
keyword injection (finding M1 — deliberately not ``Config`` fields; run identity
unchanged).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence

from solari_converter.reconcile.align import AlignedSegmentGroup

__all__ = [
    "comparison_key",
    "is_material",
    "classify_diff",
    "NATIVE_TECHNIQUE_PRECEDENCE",
    "preferred_technique",
    "pick_verbatim",
    "literal_confidence",
    "reading_order_confidence",
]

# --- comparison key ---------------------------------------------------------------

# Smart quotes folded to their ASCII equivalents — comparison only.
_SMART_QUOTES = {
    ord("‘"): "'", ord("’"): "'", ord("‚"): "'", ord("‛"): "'",
    ord("′"): "'",
    ord("“"): '"', ord("”"): '"', ord("„"): '"', ord("‟"): '"',
    ord("″"): '"',
    ord("‹"): "'", ord("›"): "'",
}


def comparison_key(text: str) -> str:
    """The frozen comparison-only normal form (block brief §4).

    NFC → smart-quote fold → collapse every run of Unicode whitespace (NBSP, CR, LF,
    tab, …) to a single U+0020 and strip the ends. Case is preserved; every other
    codepoint is preserved. **Never** call this to produce a value that is stored.
    """
    out = unicodedata.normalize("NFC", text)
    out = out.translate(_SMART_QUOTES)
    out = " ".join(out.split())
    return out


# --- materiality -----------------------------------------------------------------

_DIFF_EQUAL = "equal"
_DIFF_WHITESPACE = "whitespace"
_DIFF_CASE = "case"
_DIFF_MATERIAL = "material"

#: Difference classes the frozen policy treats as **non-material**.
_NON_MATERIAL = frozenset({_DIFF_EQUAL, _DIFF_WHITESPACE, _DIFF_CASE})


def classify_diff(a: str, b: str) -> str:
    """Classify the difference between two literals: ``equal`` | ``whitespace`` |
    ``case`` | ``material`` (block brief §5). Comparison-only normalisation is applied
    internally; neither input is mutated."""
    if a == b:
        return _DIFF_EQUAL
    ka, kb = comparison_key(a), comparison_key(b)
    if ka == kb:
        return _DIFF_WHITESPACE
    if ka.casefold() == kb.casefold():
        return _DIFF_CASE
    return _DIFF_MATERIAL


def is_material(a: str, b: str) -> bool:
    """``True`` unless the only difference is whitespace or case (frozen policy).

    A case-only difference may be classified non-material here; the *stored* literals
    are never changed regardless.
    """
    return classify_diff(a, b) not in _NON_MATERIAL


# --- M2 technique precedence -----------------------------------------------------

#: The fixed order for the two native extraction paths, derived lexicographically from
#: the frozen technique identifiers in ``extract/docling_path`` (``"docling"``) and
#: ``extract/plumber_path`` (``"pdfplumber"``): ``"docling" < "pdfplumber"``. Fixed and
#: deterministic; independent of input iteration order.
NATIVE_TECHNIQUE_PRECEDENCE: tuple[str, ...] = ("docling", "pdfplumber")


def _is_native(technique: str) -> bool:
    return not technique.startswith("ocr:") and technique != "ocr"


def _precedence_rank(technique: str) -> tuple[int, int, str]:
    """Sort key: native before OCR; native paths in the frozen order; OCR paths by
    their (deterministic) identifier. Never uses call/iteration order."""
    if _is_native(technique):
        try:
            return (0, NATIVE_TECHNIQUE_PRECEDENCE.index(technique), technique)
        except ValueError:
            # an unknown native technique still outranks OCR; ordered by its identifier
            return (0, len(NATIVE_TECHNIQUE_PRECEDENCE), technique)
    return (1, 0, technique)


def preferred_technique(techniques: Iterable[str]) -> str:
    """The winning technique among ``techniques`` under the M2 precedence.

    1. a native path beats any OCR path;
    2. between native paths, :data:`NATIVE_TECHNIQUE_PRECEDENCE`;
    3. between OCR paths, the lexicographic order of the frozen identifiers.

    OCR never outranks native for a non-material difference. Raises ``ValueError`` on an
    empty input.
    """
    ranked = sorted(set(techniques), key=_precedence_rank)
    if not ranked:
        raise ValueError("preferred_technique: no techniques given")
    return ranked[0]


def pick_verbatim(group: AlignedSegmentGroup) -> str:
    """The verbatim text of ``group``'s member chosen by the M2 precedence.

    Returns a member's **stored** string byte-for-byte — never a ``comparison_key``
    form. Used when the members' differences are non-material and one verbatim value
    must represent the group.
    """
    by_tech = {m.technique: m for m in group.members}
    winner = preferred_technique(by_tech)
    return by_tech[winner].text


# --- confidence -----------------------------------------------------------------

#: A native candidate is present (not an all-OCR group) → the group is more trustworthy.
NATIVE_PRESENT_BONUS: float = 0.15
#: Every candidate is OCR → less trustworthy.
ALL_OCR_PENALTY: float = 0.10
#: Penalty by character class of the material diff.
DIFF_CLASS_PENALTY: dict[str, float] = {
    "digit": 0.30,
    "letter": 0.18,
    "punctuation": 0.10,
    "mixed": 0.30,
}
#: Weight of the OCR-confidence signal: ``(min_conf/100 - 0.5) * OCR_CONFIDENCE_WEIGHT``.
OCR_CONFIDENCE_WEIGHT: float = 0.20
#: Geometry unambiguously supports the order → reading-order confidence bonus.
GEOMETRY_SUPPORT_BONUS: float = 0.20


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _material_char_class(a: str, b: str) -> str:
    """Coarse character class of a material difference between two literals."""
    diff_chars = (set(a) ^ set(b)) | {c for c in set(a) & set(b)}
    changed = {c for c in (set(a) | set(b)) if (c in a) != (c in b)}
    sample = changed or diff_chars
    has_digit = any(c.isdigit() for c in sample)
    has_alpha = any(c.isalpha() for c in sample)
    has_punct = any((not c.isalnum() and not c.isspace()) for c in sample)
    if has_digit and (has_alpha or has_punct):
        return "mixed"
    if has_digit:
        return "digit"
    if has_alpha:
        return "letter"
    if has_punct:
        return "punctuation"
    return "mixed"


def _agreement_fraction(keys: Sequence[str]) -> float:
    if len(keys) <= 1:
        return 1.0
    top = max(keys.count(k) for k in set(keys))
    return top / len(keys)


def literal_confidence(group: AlignedSegmentGroup) -> float:
    """Deterministic confidence in ``[0, 1]`` that ``group``'s literal content can be
    reconciled automatically (research §21b). Higher ⇒ safer to accept / hand to the
    selection-only LLM; the ``< 0.75`` → HUMAN_REVIEW cut is applied by T060, not here.
    """
    members = list(group.members)
    if len(members) <= 1:
        return 1.0

    keys = [comparison_key(m.text) for m in members]
    score = _agreement_fraction(keys)

    natives = [m for m in members if _is_native(m.technique)]
    if natives:
        score += NATIVE_PRESENT_BONUS
    else:
        score -= ALL_OCR_PENALTY

    # character class of the widest material disagreement
    worst = "none"
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            if is_material(members[i].text, members[j].text):
                cls = _material_char_class(members[i].text, members[j].text)
                if DIFF_CLASS_PENALTY.get(cls, 0.0) >= DIFF_CLASS_PENALTY.get(worst, 0.0):
                    worst = cls
    score -= DIFF_CLASS_PENALTY.get(worst, 0.0)

    ocr_confs = [
        m.source.ocr_confidence
        for m in members
        if m.source.ocr_confidence is not None
    ]
    if ocr_confs:
        score += (min(ocr_confs) / 100.0 - 0.5) * OCR_CONFIDENCE_WEIGHT

    return _clamp(score)


def reading_order_confidence(
    *,
    candidate_orders: Sequence[Sequence[str]],
    max_pairwise_kendall_tau_distance: float,
    geometry_unambiguous: bool = False,
) -> float:
    """Deterministic confidence in ``[0, 1]`` for an automatic reading-order decision
    (research §21c). ``1.0`` when the candidate orders already agree; otherwise
    ``1 - Kendall-τ distance`` plus a bonus when geometry unambiguously supports an
    order. Kendall-τ is supplied by the caller (``reading_order.kendall_tau_distance``).
    """
    distinct = {tuple(o) for o in candidate_orders}
    base = (
        1.0
        if len(distinct) <= 1
        else 1.0 - _clamp(max_pairwise_kendall_tau_distance)
    )
    if geometry_unambiguous:
        base += GEOMETRY_SUPPORT_BONUS
    return _clamp(base)
