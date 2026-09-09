"""Stage-3 deterministic reflow + de-hyphenation (T067).

The first semantic-transformation pass. It consumes the **Canonical Extracted Document
only** — the accepted verbatim segments in ``accepted_reading_order`` plus their frozen
``SourceRef`` geometry and the carried (never-applied) structural hints — and groups the
visually-wrapped lines of one logical paragraph back together (FR-013 / FR-016),
repairing an artificial line-break hyphen where — and only where — research §27's
positive document-internal evidence permits it (FR-014).

Hard guarantees
---------------

* **deterministic** — a pure function of the CED; no LLM, no network, no dictionary /
  word-list / spell-checker, no randomness;
* **literal-faithful** — a source segment's own character sequence is never changed
  except at a line boundary that a recorded :class:`SegmentTransform`
  (``dehyphenate`` | ``reflow_whitespace``) fully accounts for. Whitespace *inside* a
  source literal is immutable; whitespace *between* two segments is envelope;
* **order-preserving** — units are built by walking ``accepted_reading_order``; flatten
  every unit's ``segment_ids`` in unit order and you get that exact list back (FR-064 /
  SC-023). Adjacent segments may be combined, never reordered;
* **lineage-complete** — every unit carries *all* of its contributing segment ids in
  source order; a transform names every segment it touched.

Thresholds the architecture does not pin are **named module constants** — deliberately
not ``Config`` fields, not CLI options, not folded into run identity (block brief §10).

``SegmentTransform`` / ``HintDecision`` are the S1 internal audit records. They are
shaped to map onto the later ``model.human_review_verification.SegmentTransform``
(T141) and the ``Block.hint_decisions`` of the ``SemanticDocument`` (T073) without a
rewrite — S1 owns neither of those yet.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from solari_converter.model.canonical import AcceptedSegment, CanonicalExtractedDocument
from solari_converter.reconcile.confidence import comparison_key

__all__ = [
    "PARAGRAPH_BREAK_GAP_RATIO",
    "INDENT_TOLERANCE",
    "MIN_LETTERS_BEFORE_HYPHEN",
    "DEHYPHENATION_MIN_OCR_CONFIDENCE",
    "WRAPPED_LINE_JOIN",
    "LEADING_MARKER_RE",
    "TransformKind",
    "SegmentTransform",
    "HintDecision",
    "ReflowUnit",
    "ReflowResult",
    "reflow",
]

# --- frozen thresholds (module constants; NOT Config; run identity unchanged) --------

#: A vertical gap between two consecutive segments larger than this fraction of the
#: local line height ends the current paragraph. A smaller gap is a wrapped line of the
#: same paragraph. Prefer a conservative *failure to join* over an unsafe merge.
PARAGRAPH_BREAK_GAP_RATIO: float = 1.4

#: Two segments whose left edges differ by more than this many PDF units are treated as
#: differently-indented — not the continuation of one wrapped paragraph.
INDENT_TOLERANCE: float = 6.0

#: A word split across a line boundary must have at least this many Latin letters before
#: the trailing ``U+002D`` for the hyphen to be a de-hyphenation candidate (§27).
MIN_LETTERS_BEFORE_HYPHEN: int = 2

#: An OCR-derived fragment at or below this normalised confidence keeps its hyphen —
#: Stage 3 stays conservative on shaky OCR (§27). Mirrors the default OCR acceptance
#: floor; it is **not** a ``Config`` field.
DEHYPHENATION_MIN_OCR_CONFIDENCE: float = 70.0

#: The single structural separator a wrapped-line join inserts (FR-013). A retained
#: line-break hyphen suppresses it (the un-wrapped visual form has no space there).
WRAPPED_LINE_JOIN: str = " "

#: A conservative "this segment starts a new list item / clause" guard for paragraph
#: joining (block brief §11). ``lists.py`` reuses this exact pattern for consistency.
LEADING_MARKER_RE = re.compile(
    r"""^\s*(
        [-•‣◦⁃∙*]\s+        # bullet
      | \(?[0-9]{1,3}[.)]\s+                          # 1. / 1) / (1)
      | \(?[0-9]+(?:\.[0-9]+)+[.)]?\s+                # 1.2 / 1.2.3
      | \(?[a-zA-Z][.)]\s+                            # a. / a) / (a)
      | \(?(?:i{1,3}|iv|v|vi{0,3}|ix|x)[.)]\s+        # roman i. .. x.
      | (?:Article|Section|Clause|Artigo|Cláusula|Cl[aá]usula|Se[cç][aã]o|Par[aá]grafo)\b
    )""",
    re.VERBOSE,
)

_HYPHEN = "-"
#: Dash characters that are *never* line-break hyphens under §27.
_NON_BREAK_DASHES = frozenset("‐‑‒–—―­")

_BLOCKING_HINT_KINDS = frozenset(
    {"heading", "subheading", "list_item", "list_start", "list_end",
     "table", "table_row", "table_cell", "caption"}
)

_TOKEN_RE = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*", re.UNICODE)
_TRAILING_LETTERS_RE = re.compile(r"([^\W\d_]{1,})$", re.UNICODE)


# --- audit records -----------------------------------------------------------------

TransformKind = Literal["dehyphenate", "reflow_whitespace"]

_PERMITTED_BY: dict[str, str] = {
    "dehyphenate": "FR-014",
    "reflow_whitespace": "FR-013",
}


@dataclass(frozen=True)
class SegmentTransform:
    """One deterministic Stage-3 change to a segment's own character sequence at a line
    boundary. Ordered; every entry names an explicit kind and its permitting rule
    (research §25.2). Maps onto ``model.human_review_verification.SegmentTransform``."""

    kind: TransformKind
    permitted_by: str
    segment_ids: tuple[str, ...]
    joined_with: str | None
    boundary: str
    evidence: str | None = None
    stage: int = 3


@dataclass(frozen=True)
class HintDecision:
    """Records that a carried structural hint was applied — or deliberately not — by a
    Stage-3 pass (FR-064 / SC-026). Shared by ``structure.py`` and ``lists.py``."""

    hint_ref: str
    kind: str
    applied: bool
    reason: str


# --- reflow value types ------------------------------------------------------------


@dataclass(frozen=True)
class ReflowUnit:
    """One reflowed paragraph candidate — one or more adjacent CED segments joined."""

    segment_ids: tuple[str, ...]
    text: str
    segments: tuple[AcceptedSegment, ...]
    transforms: tuple[SegmentTransform, ...] = ()

    @property
    def page(self) -> int:
        return self.segments[0].source.physical_page

    @property
    def pages(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys(s.source.physical_page for s in self.segments))

    @property
    def starts_new_block(self) -> bool:
        return bool(LEADING_MARKER_RE.match(self.text))


@dataclass(frozen=True)
class ReflowResult:
    units: tuple[ReflowUnit, ...]
    transforms: tuple[SegmentTransform, ...] = ()

    def source_order(self) -> list[str]:
        return [sid for u in self.units for sid in u.segment_ids]


# --- geometry / text helpers (pure) ----------------------------------------------


def _line_height(a: AcceptedSegment, b: AcceptedSegment) -> float:
    hs = [
        s.source.bbox[3] - s.source.bbox[1]
        for s in (a, b)
        if s.source.bbox is not None
    ]
    return max([h for h in hs if h > 0.0] or [12.0])


def _is_wrapped_continuation(a: AcceptedSegment, b: AcceptedSegment) -> bool:
    """Deterministic: is ``b`` a wrapped line of the same paragraph as ``a``?"""
    sa, sb = a.source, b.source
    if sa.physical_page != sb.physical_page:
        return False  # a page boundary alone neither forces a break nor proves join
    if sa.bbox is None or sb.bbox is None:
        return False  # no geometry → cannot prove continuation → stay conservative
    ax0, atop, _, abot = sa.bbox
    bx0, btop, _, bbot = sb.bbox
    if btop < atop - 1.0:
        return False  # b is not below a
    gap = btop - abot
    if gap > PARAGRAPH_BREAK_GAP_RATIO * _line_height(a, b):
        return False  # a paragraph-sized vertical gap
    # a differently-indented next line is a different paragraph
    return abs(bx0 - ax0) <= INDENT_TOLERANCE


def _segment_hint_kinds(ced: CanonicalExtractedDocument, segment_id: str) -> set[str]:
    return {
        h.kind for h in ced.carried_structural_hints if h.segment_id == segment_id
    }


def _has_blocking_hint(ced: CanonicalExtractedDocument, segment_id: str) -> bool:
    return bool(_segment_hint_kinds(ced, segment_id) & _BLOCKING_HINT_KINDS)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(unicodedata.normalize("NFC", text))


def _token_key(token: str) -> str:
    return comparison_key(token).casefold()


def _is_latin_lower(ch: str) -> bool:
    if not (ch.isalpha() and ch.islower()):
        return False
    try:
        return "LATIN" in unicodedata.name(ch)
    except ValueError:
        return False


def _line_break_hyphen_fragment(text: str) -> str | None:
    """The trailing word-fragment before a genuine ``U+002D`` line-break hyphen, or
    ``None`` when ``text`` does not end in a de-hyphenation-candidate hyphen (§27)."""
    if not text.endswith(_HYPHEN):
        return None
    if len(text) >= 2 and text[-2] in _NON_BREAK_DASHES:
        return None  # e.g. an en dash immediately followed by a hyphen
    stem = text[:-1]
    m = _TRAILING_LETTERS_RE.search(stem)
    if m is None:
        return None
    frag = m.group(1)
    latin = [c for c in frag if "LATIN" in (unicodedata.name(c, "") or "")]
    if len(latin) < MIN_LETTERS_BEFORE_HYPHEN:
        return None
    before = stem[: m.start(1)]
    if before and before[-1].isdigit():
        return None  # a numbering / range pattern like "12-" or "pp. 3-"
    return frag


# --- the pass ------------------------------------------------------------------------


def reflow(
    ced: CanonicalExtractedDocument,
    *,
    excluded_segment_ids: frozenset[str] = frozenset(),
) -> ReflowResult:
    """Group ``ced``'s accepted segments (in accepted reading order) into reflowed
    paragraph units, repairing line-break hyphens per research §27. Deterministic.

    ``excluded_segment_ids`` lets a caller that has already determined ownership of
    some segments elsewhere (table reconstruction — T070) keep this pass to the
    remainder: an excluded segment never appears in any :class:`ReflowUnit` or
    :class:`SegmentTransform` and acts as a **hard boundary** — the segments
    immediately before and after it are never joined into the same unit, exactly as
    if a blocking structural hint sat there. The default (no exclusions) is
    byte/semantically identical to the prior signature. The §27 positive-evidence
    token index stays CED-wide regardless of exclusions (research §27 is a
    document-wide lexical check, not a per-unit one).
    """
    by_id = {s.segment_id: s for s in ced.accepted_segments}
    ordered = [by_id[sid] for sid in ced.accepted_reading_order if sid in by_id]

    # CED-wide complete-token index for the §27 positive-evidence lookup — unaffected
    # by exclusions; §27 attestation may come from any accepted segment.
    token_owner: dict[str, str] = {}
    for seg in ordered:
        for tok in _tokens(seg.text):
            token_owner.setdefault(_token_key(tok), seg.segment_id)

    units: list[ReflowUnit] = []
    cur_ids: list[str] = []
    cur_segs: list[AcceptedSegment] = []
    cur_text = ""
    cur_tx: list[SegmentTransform] = []

    def _flush() -> None:
        nonlocal cur_ids, cur_segs, cur_text, cur_tx
        if cur_ids:
            units.append(
                ReflowUnit(
                    segment_ids=tuple(cur_ids),
                    text=cur_text,
                    segments=tuple(cur_segs),
                    transforms=tuple(cur_tx),
                )
            )
        cur_ids, cur_segs, cur_text, cur_tx = [], [], "", []

    for seg in ordered:
        if seg.segment_id in excluded_segment_ids:
            # A hard boundary: end whatever unit was building; the excluded segment
            # itself never starts or joins one, so the segments on either side of it
            # can never become adjacent for reflow purposes.
            _flush()
            continue

        if not cur_ids:
            cur_ids, cur_segs, cur_text, cur_tx = [seg.segment_id], [seg], seg.text, []
            continue

        prev = cur_segs[-1]
        join = (
            _is_wrapped_continuation(prev, seg)
            and not _has_blocking_hint(ced, prev.segment_id)
            and not _has_blocking_hint(ced, seg.segment_id)
            and not LEADING_MARKER_RE.match(seg.text)
        )
        if not join:
            _flush()
            cur_ids, cur_segs, cur_text, cur_tx = [seg.segment_id], [seg], seg.text, []
            continue

        frag_left = _line_break_hyphen_fragment(cur_text)
        tx, new_text = _join(ced, cur_ids, prev, seg, cur_text, frag_left, token_owner)
        cur_text = new_text
        cur_ids.append(seg.segment_id)
        cur_segs.append(seg)
        cur_tx.append(tx)

    _flush()
    all_tx = tuple(t for u in units for t in u.transforms)
    return ReflowResult(units=tuple(units), transforms=all_tx)


def _join(
    ced: CanonicalExtractedDocument,
    unit_ids: list[str],
    left: AcceptedSegment,
    right: AcceptedSegment,
    left_text: str,
    frag_left: str | None,
    token_owner: dict[str, str],
) -> tuple[SegmentTransform, str]:
    """Produce the joined text + its single audit record for appending ``right``."""
    touched = tuple(unit_ids) + (right.segment_id,)

    if frag_left is not None:
        right_tokens = _tokens(right.text)
        frag_right = right_tokens[0] if right_tokens else ""
        attester = _dehyphenation_attester(
            frag_left, frag_right, right, token_owner
        )
        if attester is not None and _dehyphenation_guards_ok(ced, left, right, frag_right):
            joined_token = f"{frag_left}{frag_right}"
            return (
                SegmentTransform(
                    kind="dehyphenate",
                    permitted_by=_PERMITTED_BY["dehyphenate"],
                    segment_ids=touched,
                    joined_with=right.segment_id,
                    boundary=(
                        f"trailing U+002D + line break between "
                        f"{left.segment_id} and {right.segment_id}"
                    ),
                    evidence=(
                        f"joined token '{joined_token}' occurs as a complete token "
                        f"in segment {attester}"
                    ),
                ),
                left_text[:-1] + right.text,
            )
        # positive evidence or a guard is missing -> keep the hyphen, un-wrap only
        return (
            SegmentTransform(
                kind="reflow_whitespace",
                permitted_by=_PERMITTED_BY["reflow_whitespace"],
                segment_ids=touched,
                joined_with=right.segment_id,
                boundary=(
                    f"hard line break collapsed between {left.segment_id} and "
                    f"{right.segment_id}; trailing hyphen retained "
                    f"(no in-document attestation of the joined token)"
                ),
            ),
            left_text + right.text,
        )

    return (
        SegmentTransform(
            kind="reflow_whitespace",
            permitted_by=_PERMITTED_BY["reflow_whitespace"],
            segment_ids=touched,
            joined_with=right.segment_id,
            boundary=(
                f"hard line break collapsed to a single space between "
                f"{left.segment_id} and {right.segment_id}"
            ),
        ),
        left_text + WRAPPED_LINE_JOIN + right.text,
    )


def _dehyphenation_attester(
    frag_left: str,
    frag_right: str,
    right: AcceptedSegment,
    token_owner: dict[str, str],
) -> str | None:
    """The segment id whose text carries the joined token as a *complete* token,
    excluding the wrap's own right segment. ``None`` ⇒ no positive evidence (§27)."""
    if not frag_right or not _is_latin_lower(frag_right[0]):
        return None
    key = _token_key(f"{frag_left}{frag_right}")
    owner = token_owner.get(key)
    if owner is None or owner == right.segment_id:
        return None
    return owner


def _dehyphenation_guards_ok(
    ced: CanonicalExtractedDocument,
    left: AcceptedSegment,
    right: AcceptedSegment,
    frag_right: str,
) -> bool:
    """The §27 structural guards (the lexical evidence is checked separately)."""
    if left.source.physical_page != right.source.physical_page:
        return False
    if not _is_wrapped_continuation(left, right):
        return False
    if _has_blocking_hint(ced, left.segment_id) or _has_blocking_hint(ced, right.segment_id):
        return False
    for seg in (left, right):
        if (
            seg.source.origin_kind == "ocr"
            and seg.source.ocr_confidence is not None
            and seg.source.ocr_confidence < DEHYPHENATION_MIN_OCR_CONFIDENCE
        ):
            return False
    return True
