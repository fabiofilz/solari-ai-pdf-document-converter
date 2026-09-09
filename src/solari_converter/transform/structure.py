"""Stage-3 deterministic heading / hierarchy inference (T068).

Consumes the CED (via the :class:`~solari_converter.transform.reflow.ReflowResult`) and
classifies every reflowed unit as a ``heading`` (with a level) or ordinary ``body``
text. It **may** consult the CED's carried structural hints — but a hint is *evidence,
not truth* (FR-060b / FR-064): a heading hint is applied only when at least one
independent deterministic signal corroborates it, and **every** carried heading /
subheading hint is recorded ``applied`` or not (SC-026).

No LLM, no network, no randomness, no fabricated hierarchy. Levels 1–6 map to Markdown
headings later; a level > 6 is *flagged* (``deep``) for the ``[L{n}]`` emphasised-lead-in
treatment — never rendered here (block brief §19). Thresholds are named module constants
(not ``Config``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from solari_converter.model.canonical import CanonicalExtractedDocument
from solari_converter.transform.reflow import HintDecision, ReflowResult, ReflowUnit

__all__ = [
    "MARKDOWN_MAX_HEADING_LEVEL",
    "HEADING_MAX_WORDS",
    "HEADING_TERMINAL_PUNCTUATION",
    "StructuredUnit",
    "StructureResult",
    "infer_structure",
]

#: Deepest level Markdown heading syntax can carry; deeper levels are flagged ``deep``.
MARKDOWN_MAX_HEADING_LEVEL: int = 6

#: A heading candidate is short. A unit longer than this (in whitespace tokens) is body
#: text even if an extractor tagged it a heading.
HEADING_MAX_WORDS: int = 12

#: Trailing punctuation that marks running prose — a heading candidate must not end with
#: one of these.
HEADING_TERMINAL_PUNCTUATION: tuple[str, ...] = (".", ";", ",", ":")

_HEADING_HINT_KINDS = frozenset({"heading", "subheading"})

_FUNCTION_WORDS = frozenset({
    "a", "an", "the", "of", "and", "or", "to", "in", "for", "on", "at", "by", "with",
    "from", "as", "is", "are", "be", "de", "da", "do", "e", "o", "para", "por", "com",
    "sem", "que",
})

_KEYWORD_NUMBERING = re.compile(
    r"^\s*(?P<kw>Article|Section|Chapter|Clause|Part|Artigo|Cl[aá]usula|Se[cç][aã]o|"
    r"Cap[ií]tulo|Parte|Par[aá]grafo)\s+(?P<n>[0-9]+(?:[ºªo]|\.[0-9]+)*|[IVXLC]+)\b",
    re.IGNORECASE,
)
_DOTTED_NUMBERING = re.compile(r"^\s*(?P<n>[0-9]+(?:\.[0-9]+)*)(?=[.)\s–—-])")
_ROMAN_NUMBERING = re.compile(
    r"^\s*(?P<n>(?:x{0,3})(?:ix|iv|v?i{0,3}))(?=[.)]\s)", re.IGNORECASE
)


@dataclass(frozen=True)
class StructuredUnit:
    segment_ids: tuple[str, ...]
    text: str
    role: str  # "heading" | "body"
    level: int | None
    deep: bool
    numbering: str | None
    hint_decisions: tuple[HintDecision, ...]


@dataclass(frozen=True)
class StructureResult:
    units: tuple[StructuredUnit, ...]
    hint_decisions: tuple[HintDecision, ...]

    def source_order(self) -> list[str]:
        return [sid for u in self.units for sid in u.segment_ids]


# --- signal extraction (pure) ----------------------------------------------------


def _split_numbering(text: str) -> tuple[str | None, int]:
    """A leading heading/section number and its depth, or ``(None, 0)``."""
    s = unicodedata.normalize("NFC", text)
    m = _KEYWORD_NUMBERING.match(s)
    if m:
        n = m.group("n")
        depth = n.count(".") + 1 if any(c.isdigit() for c in n) else 1
        return f"{m.group('kw')} {n}", depth
    m = _DOTTED_NUMBERING.match(s)
    if m and s[m.end():].strip():
        n = m.group("n")
        return n, n.count(".") + 1
    m = _ROMAN_NUMBERING.match(s)
    if m and s[m.end():].strip():
        return m.group("n"), 1
    return None, 0


def _strip_leading_numbering(text: str) -> str:
    num, _ = _split_numbering(text)
    if num is None:
        return text
    rest = text
    # drop the matched prefix + a following separator run
    idx = rest.lower().find(num.split()[-1].lower()) + len(num.split()[-1])
    return rest[idx:].lstrip(" .)–—-\t")


def _is_titlish(text: str) -> bool:
    body = _strip_leading_numbering(text)
    if body and body == body.upper() and any(c.isalpha() for c in body):
        return True
    words = [w for w in re.findall(r"[^\W_]+", body, re.UNICODE)]
    content = [w for w in words if w.lower() not in _FUNCTION_WORDS]
    if not content:
        return False
    caps = sum(1 for w in content if w[:1].isupper())
    return caps / len(content) >= 0.6


def _ends_like_prose(text: str) -> bool:
    return text.rstrip().endswith(HEADING_TERMINAL_PUNCTUATION)


# --- the pass ------------------------------------------------------------------------


def _heading_hints(ced: CanonicalExtractedDocument, unit: ReflowUnit):
    ids = set(unit.segment_ids)
    return [
        h for h in ced.carried_structural_hints
        if h.segment_id in ids and h.kind in _HEADING_HINT_KINDS
    ]


def _hint_ref(h) -> str:
    return f"{h.segment_id}:{h.kind}:{h.source_technique}:{h.level}"


def infer_structure(
    ced: CanonicalExtractedDocument, reflow_result: ReflowResult
) -> StructureResult:
    """Classify every reflowed unit as ``heading`` (with a level) or ``body``.
    Deterministic. Records a :class:`HintDecision` for every carried heading hint."""
    units: list[StructuredUnit] = []
    all_decisions: list[HintDecision] = []

    for unit in reflow_result.units:
        text = unit.text
        numbering, depth = _split_numbering(text)
        words = len(text.split())
        short = words <= HEADING_MAX_WORDS
        single_line = len(unit.segment_ids) == 1
        titlish = _is_titlish(text)
        prose_end = _ends_like_prose(text)

        corroborated = (
            short
            and not prose_end
            and (single_line or numbering is not None or titlish)
        )

        hints = sorted(
            _heading_hints(ced, unit),
            key=lambda h: (h.segment_id, h.kind, h.source_technique, h.level or 0),
        )
        decisions: list[HintDecision] = []
        applied_level: int | None = None
        for h in hints:
            if corroborated and applied_level is None:
                applied_level = h.level
                decisions.append(
                    HintDecision(
                        hint_ref=_hint_ref(h), kind=h.kind, applied=True,
                        reason=(
                            "heading hint corroborated by "
                            + ", ".join(
                                sig for sig, ok in (
                                    ("short", short),
                                    ("single-line", single_line),
                                    ("section numbering", numbering is not None),
                                    ("title-case/uppercase", titlish),
                                ) if ok
                            )
                        ),
                    )
                )
            else:
                reason = (
                    "another heading hint was already applied to this unit"
                    if applied_level is not None
                    else "no corroborating deterministic signal "
                    f"(words={words}, prose_end={prose_end}, "
                    f"numbering={numbering!r}, title-ish={titlish})"
                )
                decisions.append(
                    HintDecision(
                        hint_ref=_hint_ref(h), kind=h.kind, applied=False, reason=reason
                    )
                )
        all_decisions.extend(decisions)

        is_heading = any(d.applied for d in decisions)
        level: int | None = None
        if is_heading:
            if applied_level is not None:
                level = applied_level
            elif depth:
                level = depth
            else:
                level = 1

        units.append(
            StructuredUnit(
                segment_ids=unit.segment_ids,
                text=text,
                role="heading" if is_heading else "body",
                level=level,
                deep=bool(level and level > MARKDOWN_MAX_HEADING_LEVEL),
                numbering=numbering if is_heading else None,
                hint_decisions=tuple(decisions),
            )
        )

    return StructureResult(units=tuple(units), hint_decisions=tuple(all_decisions))
