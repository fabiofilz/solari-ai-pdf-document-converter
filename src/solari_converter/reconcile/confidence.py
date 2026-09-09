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
* :func:`is_material` — the pairwise materiality policy: a whitespace-only or a
  *simple* case-only difference (1:1, non-expanding letter case — never full Unicode
  case folding) is **not material**; every other difference (digits, letters,
  diacritics, punctuation, ligatures, ``ß``/``SS``, long-s, …) **is**.
* :func:`classify_group_diff` / :func:`group_material_disagreement` — the **group**
  policy layered on the pairwise class: a case-only difference between two *native*
  extractors (``docling`` vs ``pdfplumber``) is **material** — capitalization can
  carry legal/semantic weight and neither native path is authoritative, so the
  technique tie-break must not silently resolve it. A case-only difference is
  non-material only when the native evidence agrees and OCR is the differing side;
  whitespace-only stays non-material regardless. Ordering-independent.
* :data:`NATIVE_TECHNIQUE_PRECEDENCE` / :func:`preferred_technique` / :func:`pick_verbatim`
  — the M2 precedence for choosing among distinct **verbatim** candidates when their
  difference is non-material: native beats OCR; between the two native paths a fixed
  order derived from the frozen technique identifiers (``docling`` < ``pdfplumber``,
  lexicographic — deterministic, never input-iteration order). Its authority is
  **narrow** (block brief §4): it may only pick the representative member / stable
  ``SourceRef`` and segment identity, choose among candidates whose differing values
  are already proven non-material, and (later) pick a representative among members
  carrying an LLM-selected exact value. It never resolves a material literal
  disagreement, never turns a native-vs-native case disagreement into an automatic
  decision, never edits candidate text, and never substitutes for the LLM or Human
  Review. OCR never outranks native evidence for a non-material difference.
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
    "classify_group_diff",
    "group_material_disagreement",
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

#: Ordering of the classes by severity, for taking the worst pairwise class in a group.
_DIFF_ORDER = (_DIFF_EQUAL, _DIFF_WHITESPACE, _DIFF_CASE, _DIFF_MATERIAL)


def _is_simple_case_only(a: str, b: str) -> bool:
    """``True`` when ``a`` and ``b`` differ *only* by simple, 1:1, non-expanding letter
    case — the safe replacement for ``str.casefold()`` equality (block brief §2).

    Full Unicode case folding changes more than letter case, so it is never used here.
    A pair is *simple case-only* when the two strings have the same number of Unicode
    codepoints, they differ in at least one position, and for every differing pair
    ``(x, y)`` each side is exactly one codepoint, ``x.lower() == y.lower()``, and
    lowering neither side expands it into multiple codepoints. This keeps ``ﬁ``/``fi``
    (ligature), ``ß``/``SS`` (expansion), long-s ``ſ``/``s`` and other
    compatibility-like fold equivalences **material**.
    """
    if len(a) != len(b) or a == b:
        return False
    differs = False
    for x, y in zip(a, b, strict=True):
        if x == y:
            continue
        differs = True
        lx, ly = x.lower(), y.lower()
        if len(lx) != 1 or len(ly) != 1 or lx != ly:
            return False
    return differs


def classify_diff(a: str, b: str) -> str:
    """Classify the difference between two literals: ``equal`` | ``whitespace`` |
    ``case`` | ``material`` (block brief §5). Comparison-only normalisation is applied
    internally; neither input is mutated. ``case`` means *simple* letter case only —
    see :func:`_is_simple_case_only`; a fold that expands or changes codepoint count
    (``ﬁ``/``fi``, ``ß``/``SS``, …) is ``material``."""
    if a == b:
        return _DIFF_EQUAL
    ka, kb = comparison_key(a), comparison_key(b)
    if ka == kb:
        return _DIFF_WHITESPACE
    if _is_simple_case_only(ka, kb):
        return _DIFF_CASE
    return _DIFF_MATERIAL


def is_material(a: str, b: str) -> bool:
    """``True`` unless the only difference is whitespace or *simple* case (frozen
    pairwise policy). The **group** policy (:func:`classify_group_diff`) can still
    escalate a native-vs-native case difference to material. The *stored* literals are
    never changed regardless.
    """
    return classify_diff(a, b) not in _NON_MATERIAL


def classify_group_diff(group: AlignedSegmentGroup) -> str:
    """The group-level difference class over *all* members' verbatim texts, aware of
    native vs OCR provenance (block brief §3).

    Returns ``equal`` | ``whitespace`` | ``case`` | ``material``. It escalates a
    pairwise ``case`` result to ``material`` when two **native** extractors disagree
    (their comparison keys differ): capitalization can be semantically or legally
    significant and neither native path is universally authoritative, so the M2
    technique precedence must not silently resolve the disagreement. A case-only
    difference stays non-material only when every native member agrees and the
    differing evidence is OCR. Independent of member ordering.
    """
    members = list(group.members)
    if len(members) <= 1:
        return _DIFF_EQUAL
    worst = _DIFF_EQUAL
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            cls = classify_diff(members[i].text, members[j].text)
            if _DIFF_ORDER.index(cls) > _DIFF_ORDER.index(worst):
                worst = cls
    if worst != _DIFF_CASE:
        return worst
    native_keys = {
        comparison_key(m.text) for m in members if _is_native(m.technique)
    }
    if len(native_keys) > 1:
        return _DIFF_MATERIAL
    return _DIFF_CASE


def group_material_disagreement(group: AlignedSegmentGroup) -> bool:
    """``True`` when ``group``'s members carry a **material** disagreement under the
    group policy (:func:`classify_group_diff`) — the signal the T060 dispatch uses to
    take the material-confidence path instead of deterministic agreement."""
    return classify_group_diff(group) not in _NON_MATERIAL


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
    form. Used only when the members' differences are **non-material** (see
    :func:`group_material_disagreement`) and one verbatim value must represent the
    group; it must not be called to resolve a material disagreement (block brief §4).
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

    # character class of the widest material disagreement — group-aware materiality:
    # a case-only difference between two native extractors counts as material here
    # (block brief §3) so it flows through the normal material-confidence path. The
    # formula weights below are unchanged; only which pairs are "material" changed.
    worst = "none"
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            a, b = members[i].text, members[j].text
            cls = classify_diff(a, b)
            material = cls == _DIFF_MATERIAL or (
                cls == _DIFF_CASE
                and _is_native(members[i].technique)
                and _is_native(members[j].technique)
            )
            if material:
                cc = _material_char_class(a, b)
                if DIFF_CLASS_PENALTY.get(cc, 0.0) >= DIFF_CLASS_PENALTY.get(worst, 0.0):
                    worst = cc
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
