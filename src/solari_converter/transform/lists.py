"""Stage-3 deterministic list + legal-clause reconstruction (T069).

Consumes the CED (via the :class:`~solari_converter.transform.reflow.ReflowResult`) and
recognises list items (bullet / decimal / alphabetic) with their nesting, and numbered
articles / clauses — from **source evidence only**: the leading marker text, the
segment's left-edge indentation, and (as corroboration) a carried ``list_item`` hint. A
list hint with no marker and no indentation evidence is **not** applied (and is recorded
as such — FR-064).

Identifiers — ``Article 1``, ``Cláusula 4ª``, ``IV``, ``1.2.3`` — are **source content**
(FR-019): retained verbatim, never renumbered, normalised, translated, or reformatted.
Nesting is inferred conservatively: when two readings are equally supported, the flatter
one wins (block brief §23). No LLM, no natural-language parsing beyond the frozen marker
patterns. Thresholds are named module constants (not ``Config``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from solari_converter.model.canonical import CanonicalExtractedDocument
from solari_converter.transform.reflow import HintDecision, ReflowResult, ReflowUnit

__all__ = [
    "LIST_INDENT_STEP_MIN",
    "ListItemNode",
    "ClauseNode",
    "BodyNode",
    "ListResult",
    "reconstruct_lists",
]

#: A left-edge shift of at least this many PDF units is one nesting level. Smaller
#: shifts are treated as the same level (flatter reading wins — block brief §23).
LIST_INDENT_STEP_MIN: float = 8.0

_LIST_ITEM_HINT = "list_item"

_BULLET_CHARS = "-•‣◦⁃∙*–"

_BULLET_RE = re.compile(rf"^\s*(?P<m>[{re.escape(_BULLET_CHARS)}])\s+\S")
_DECIMAL_ITEM_RE = re.compile(r"^\s*(?P<m>\(?[0-9]{1,3}[.)])\s+\S")
_ALPHA_ITEM_RE = re.compile(r"^\s*(?P<m>\(?[a-z][.)])\s+\S")
_DOTTED_CLAUSE_RE = re.compile(r"^\s*(?P<id>[0-9]+(?:\.[0-9]+)+)(?=[.)\s–—-])")
_ROMAN_CLAUSE_RE = re.compile(r"^\s*(?P<id>[IVXLC]{1,7})(?=[.)]\s)")
_KEYWORD_CLAUSE_RE = re.compile(
    r"^\s*(?P<id>(?:Article|Section|Clause|Part|Artigo|Cl[aá]usula|Se[cç][aã]o|"
    r"Cap[ií]tulo|Parte|Par[aá]grafo)\s+"
    r"[0-9]+(?:[ºªo]|\.[0-9]+)*|[IVXLC]+(?:[ºªo])?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ListItemNode:
    segment_ids: tuple[str, ...]
    text: str
    marker: str
    family: Literal["bullet", "decimal", "alpha", "roman"]
    ordered: bool
    depth: int
    hint_decisions: tuple[HintDecision, ...] = ()
    role: str = "list_item"


@dataclass(frozen=True)
class ClauseNode:
    segment_ids: tuple[str, ...]
    text: str
    identifier: str
    depth: int
    hint_decisions: tuple[HintDecision, ...] = ()
    role: str = "clause"


@dataclass(frozen=True)
class BodyNode:
    segment_ids: tuple[str, ...]
    text: str
    hint_decisions: tuple[HintDecision, ...] = ()
    role: str = "body"


@dataclass(frozen=True)
class ListResult:
    units: tuple[ListItemNode | ClauseNode | BodyNode, ...]
    hint_decisions: tuple[HintDecision, ...]

    def source_order(self) -> list[str]:
        return [sid for u in self.units for sid in u.segment_ids]


# --- leading-marker classification (pure) --------------------------------------


@dataclass(frozen=True)
class _Lead:
    kind: Literal["list_item", "clause"]
    marker: str
    family: str
    ordered: bool
    identifier: str


#: Separators a bare clause marker may be followed by before its body text.
_CLAUSE_SEP_CHARS = " .)–—-\t"

#: The keyword half of ``_KEYWORD_CLAUSE_RE`` on its own — an explicit
#: ``Article`` / ``Cláusula`` / … keyword is unambiguous clause evidence; a *bare*
#: Roman numeral matched by that same regex's second alternative is not.
_KEYWORD_WORD_RE = re.compile(
    r"^(?:Article|Section|Clause|Part|Artigo|Cl[aá]usula|Se[cç][aã]o|"
    r"Cap[ií]tulo|Parte|Par[aá]grafo)\b",
    re.IGNORECASE,
)


def _reads_like_clause_body(rest: str) -> bool:
    """A bare numeric- or Roman-looking prefix only starts a legal clause when what
    follows reads like a clause heading rather than the continuation of a sentence:
    its first cased letter is upper-case (``IV. Governing law`` — yes;
    ``I. am available tomorrow`` — no; ``1.5 million residents voted`` — no). Ambiguous
    or lower-case-leading ⇒ not a clause, ordinary body content (R5). Only evidence
    already carried by the segment literal is used; the text itself is never altered."""
    body = rest.lstrip(_CLAUSE_SEP_CHARS)
    for ch in body:
        if ch.isalpha():
            return ch.isupper()
    return False  # nothing but separators / digits after the marker — not a clause


def _classify_leading(text: str) -> _Lead | None:
    s = unicodedata.normalize("NFC", text)

    m = _KEYWORD_CLAUSE_RE.match(s)
    if m:
        ident = m.group("id").strip()
        # an explicit keyword is unambiguous; a bare Roman numeral matched by the same
        # regex's second alternative needs a clause-like body (R5).
        if _KEYWORD_WORD_RE.match(ident) or _reads_like_clause_body(s[m.end():]):
            return _Lead("clause", "", "", True, ident)
    m = _DOTTED_CLAUSE_RE.match(s)
    if m and s[m.end():].strip() and _reads_like_clause_body(s[m.end():]):
        return _Lead("clause", "", "", True, m.group("id"))
    m = _ROMAN_CLAUSE_RE.match(s)
    if m and s[m.end():].strip() and _reads_like_clause_body(s[m.end():]):
        return _Lead("clause", "", "", True, m.group("id"))

    m = _BULLET_RE.match(s)
    if m:
        return _Lead("list_item", m.group("m"), "bullet", False, "")
    m = _DECIMAL_ITEM_RE.match(s)
    if m:
        return _Lead("list_item", m.group("m").strip(), "decimal", True, "")
    m = _ALPHA_ITEM_RE.match(s)
    if m:
        return _Lead("list_item", m.group("m").strip(), "alpha", True, "")
    return None


def _left_edge(unit: ReflowUnit) -> float | None:
    box = unit.segments[0].source.bbox
    return None if box is None else box[0]


# --- nesting (deterministic, flatter-wins) ------------------------------------


class _DepthStack:
    def __init__(self) -> None:
        self._stack: list[tuple[float, int]] = []

    def depth_for(self, x0: float | None) -> int:
        if x0 is None:
            return self._stack[-1][1] if self._stack else 0
        while self._stack and x0 < self._stack[-1][0] - LIST_INDENT_STEP_MIN:
            self._stack.pop()
        if not self._stack:
            self._stack.append((x0, 0))
            return 0
        top_x, top_d = self._stack[-1]
        if x0 > top_x + LIST_INDENT_STEP_MIN:
            self._stack.append((x0, top_d + 1))
            return top_d + 1
        return top_d


# --- hint handling -----------------------------------------------------------


def _list_hints(ced: CanonicalExtractedDocument, unit: ReflowUnit):
    ids = set(unit.segment_ids)
    return [
        h for h in ced.carried_structural_hints
        if h.segment_id in ids and h.kind == _LIST_ITEM_HINT
    ]


def _hint_ref(h) -> str:
    return f"{h.segment_id}:{h.kind}:{h.source_technique}:{h.level}"


# --- the pass --------------------------------------------------------------------


def reconstruct_lists(
    ced: CanonicalExtractedDocument, reflow_result: ReflowResult
) -> ListResult:
    """Classify every reflowed unit as a list item, a clause, or plain body.
    Deterministic; records a :class:`HintDecision` for every carried ``list_item`` hint."""
    stack = _DepthStack()
    units: list[ListItemNode | ClauseNode | BodyNode] = []
    all_decisions: list[HintDecision] = []

    for unit in reflow_result.units:
        lead = _classify_leading(unit.text)
        hints = sorted(
            _list_hints(ced, unit),
            key=lambda h: (h.segment_id, h.source_technique),
        )
        is_list_item = lead is not None and lead.kind == "list_item"

        decisions: list[HintDecision] = []
        for h in hints:
            applied = is_list_item
            decisions.append(
                HintDecision(
                    hint_ref=_hint_ref(h),
                    kind=_LIST_ITEM_HINT,
                    applied=applied,
                    reason=(
                        f"corroborated by a leading '{lead.marker}' list marker"
                        if applied
                        else "no leading list marker and no indentation evidence"
                    ),
                )
            )
        all_decisions.extend(decisions)
        dtuple = tuple(decisions)

        if lead is None:
            stack = _DepthStack()  # a plain paragraph ends the current list context
            units.append(BodyNode(unit.segment_ids, unit.text, dtuple))
            continue

        depth = stack.depth_for(_left_edge(unit))
        if lead.kind == "clause":
            units.append(
                ClauseNode(unit.segment_ids, unit.text, lead.identifier, depth, dtuple)
            )
        else:
            units.append(
                ListItemNode(
                    segment_ids=unit.segment_ids,
                    text=unit.text,
                    marker=lead.marker,
                    family=lead.family,  # type: ignore[arg-type]
                    ordered=lead.ordered,
                    depth=depth,
                    hint_decisions=dtuple,
                )
            )

    return ListResult(units=tuple(units), hint_decisions=tuple(all_decisions))
