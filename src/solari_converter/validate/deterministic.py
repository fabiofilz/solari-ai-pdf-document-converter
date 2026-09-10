"""Stage-4 deterministic final-fidelity checks (T078).

The **non-LLM** validation subset — shared by ``pipeline/validate`` (the deterministic
section of the validation report, FR-053a) and the ``extract`` built-in self-check
(research §25.7 step 2). Every check here is a **pure, deterministic function** of its
inputs: identical effective inputs ⇒ byte-identical :class:`ValidationIssue` list. No
LLM, no network, no randomness, no wall-clock.

Checks (all emit ``check_origin == "deterministic"``)
----------------------------------------------------

* **source-text coverage (SC-001 / research §15)** — the share of the selected pages'
  extractable source text (minus what stage 3 *logged* as removed) that is present in
  the delivered Markdown, plus the list of missing tokens;
* **gross divergence (FR-036a)** — ``source_text_match_rate < gross_divergence_threshold``
  ⇒ one summary ``gross_divergence`` issue; per-token ``missing_content`` /
  ``numeric_mismatch`` noise is suppressed, **structural** checks still run;
* **numeric integrity** — a source numeric / monetary value that is not reproduced
  verbatim in the Markdown ⇒ ``numeric_mismatch``;
* **table shape** — a delivered table whose row / column count differs from the
  ``SemanticDocument`` table it renders ⇒ ``table_shape``;
* **duplicated header** — a table header row re-emitted as a data row (FR-022) ⇒
  ``duplicated_header``;
* **reading order** — a source segment rendered out of the CED accepted reading order
  with no logged ``structural_reorder`` covering it (FR-015 / SC-023) ⇒ ``reading_order``;
* **OCR low confidence** — an accepted OCR segment (or a candidate OCR region) whose
  normalised confidence is below the effective threshold (research §9a) ⇒
  ``ocr_low_confidence``.

:class:`ValidationIssue` is a frozen dataclass carrying the six mandatory
``validation-report.schema.json`` fields + ``check_origin`` + the optional block. It is
shaped to map onto the ``reports/validation_report.ValidationIssue`` pydantic model
(T098) and its ``defect_class`` is assigned later by ``validate/classify.py`` (T099) —
this module never guesses a root-cause class.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from solari_converter.model.candidate import ExtractionCandidate
from solari_converter.model.canonical import (
    AcceptedSegment,
    CanonicalExtractedDocument,
)
from solari_converter.model.semantic import SemanticDocument
from solari_converter.transform.tables import TableBlock, TableCell

__all__ = [
    "GROSS_DIVERGENCE_DEFAULT",
    "OCR_CONFIDENCE_DEFAULT",
    "MIN_LOCALISABLE_CHARS",
    "ValidationIssue",
    "DeterministicResult",
    "run_deterministic_checks",
]

#: Default gross-divergence threshold (0–1 fraction; research §15).
GROSS_DIVERGENCE_DEFAULT: float = 0.5

#: Default normalised-0–100 OCR acceptance floor (research §9a).
OCR_CONFIDENCE_DEFAULT: float = 70.0

#: A source segment literal shorter than this (stripped) is not localised in the
#: Markdown for the reading-order check — too short to place unambiguously.
MIN_LOCALISABLE_CHARS: int = 8

_WORD_OR_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+", re.UNICODE)
#: An authored numeric literal keeps its **surface semantics** (research §15 / FR-024):
#: an attached leading ``+`` / ``-`` sign, a trailing ``%``, the decimal / group
#: separators exactly as authored, and any leading zeros. ``-25`` ≠ ``25``; ``25%`` ≠
#: ``25``; ``1.00`` ≠ ``1``; ``0004`` ≠ ``4``; ``1.599,80`` ≠ ``1,599.80``. Locale forms
#: are **never** normalised to a common value — they are compared as literal strings.
#: The leading-boundary guard keeps a hyphen that is really a dash / range separator
#: (``10-25``) from being read as a sign.
_NUMBER_RE = re.compile(r"(?<![\w.])([+-]?\d+(?:[.,]\d+)*%?)")
_PIPE_SPLIT_RE = re.compile(r"(?<!\\)\|")
_SEPARATOR_CELL_RE = re.compile(r"^:?-{1,}:?$")
_TR_RE = re.compile(r"<tr>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(
    r"<(t[hd])((?:\s+[a-z]+=\"[^\"]*\")*)\s*>(.*?)</\1>", re.IGNORECASE | re.DOTALL
)
_COLSPAN_RE = re.compile(r'colspan="(\d+)"', re.IGNORECASE)
_ROWSPAN_RE = re.compile(r'rowspan="(\d+)"', re.IGNORECASE)

#: Markdown / HTML structure the renderer generates itself — never authored content.
#: Stripped before any authored-token / authored-number matching so a generated number
#: (``rowspan="2"``, ``colspan="3"``, a deep-heading ``[L7]`` envelope, an OCR comment,
#: a pipe separator row) can never stand in for missing author content (research §25.2).
_MD_ENVELOPE_RE = re.compile(r"<[^>]*>|\[L\d+\]")
_TRAILING_HYPHEN_FRAG_RE = re.compile(r"([^\W\d_]+)-\Z", re.UNICODE)
_LEADING_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


# --- public value types ----------------------------------------------------------


@dataclass(frozen=True)
class ValidationIssue:
    """One deterministic finding. Six mandatory ``validation-report.schema.json``
    fields + ``check_origin`` + the optional detail block. ``defect_class`` stays
    ``None`` here — ``validate/classify.py`` (T099) assigns the originating-stage
    class."""

    id: str
    severity: Literal["error", "warning", "info"]
    source_page: int
    markdown_line: int
    markdown_column: int
    issue_type: str
    description: str
    check_origin: Literal["deterministic"] = "deterministic"
    defect_class: str | None = None
    source_location: str | None = None
    expected: str | None = None
    found: str | None = None
    suggested_action: str | None = None


@dataclass(frozen=True)
class DeterministicResult:
    issues: tuple[ValidationIssue, ...] = ()
    source_text_match_rate: float = 1.0
    gross_divergence: bool = False
    gross_divergence_threshold: float = GROSS_DIVERGENCE_DEFAULT
    missing_tokens: tuple[str, ...] = ()


# --- text helpers (pure) --------------------------------------------------------


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for m in _WORD_OR_NUMBER_RE.finditer(_norm(text)):
        tok = m.group(0)
        out.append(tok if tok[0].isdigit() else tok.casefold())
    return out


def _numbers(text: str) -> list[str]:
    return _NUMBER_RE.findall(_norm(text))


def _author_visible(markdown: str) -> str:
    """``markdown`` with the renderer's own generated structure removed (HTML tags /
    comments, deep-heading ``[L{n}]`` envelopes). What remains is the author-visible
    text — the only thing an authored token / number is allowed to match against."""
    return _MD_ENVELOPE_RE.sub(" ", markdown)


def _cnorm(text: str) -> str:
    return _norm(text).casefold().strip()


def _excluded_segment_ids(semantic: SemanticDocument) -> frozenset[str]:
    """Accepted source segments whose literal is **not** expected to appear directly in
    the delivered Markdown, because a recorded, permitted Stage-3 operation already
    accounts for it (research §25.2):

    * ``removed_segment_ids`` — a logged artifact removal (page number / furniture);
    * ``collapsed_segment_ids`` — a repeated table header folded into its retained twin
      (FR-021 / FR-022);
    * every non-representative sibling of a ``table_identical_evidence_groups`` set — two
      or more byte-identical source literals T070 collapsed into one retained logical
      cell; only the lexicographically-smallest id is the rendered representative.
    """
    out: set[str] = set(semantic.removed_segment_ids) | set(
        semantic.collapsed_segment_ids
    )
    for group in semantic.table_identical_evidence_groups:
        siblings = sorted(group)
        out.update(siblings[1:])
    return frozenset(out)


def _dehyphenation_pairs(
    semantic: SemanticDocument, by_id: Mapping[str, AcceptedSegment]
) -> list[tuple[str, str]]:
    """``(left_fragment, right_fragment)`` for every recorded ``dehyphenate`` transform
    (FR-014) — the trailing word fragment before the joined ``U+002D`` and the leading
    word of the following segment. After the join neither surface appears literally; the
    merged token ``left+right`` does. Used to reconcile source-token expectations so a
    legitimate ``inter-`` + ``national`` → ``international`` is not a false divergence."""
    pairs: list[tuple[str, str]] = []
    for t in semantic.segment_transforms:
        if t.kind != "dehyphenate" or not t.segment_ids:
            continue
        right_id = t.joined_with or t.segment_ids[-1]
        left_ids = [s for s in t.segment_ids if s != right_id]
        if not left_ids:
            continue
        left = by_id.get(left_ids[-1])
        right = by_id.get(right_id)
        if left is None or right is None:
            continue
        lm = _TRAILING_HYPHEN_FRAG_RE.search(_norm(left.text).rstrip())
        rm = _LEADING_WORD_RE.search(_norm(right.text))
        if lm is None or rm is None:
            continue
        pairs.append((lm.group(1), rm.group(0)))
    return pairs


def _apply_dehyphenation(text: str, pairs: list[tuple[str, str]]) -> str:
    """Fold each recorded ``left-`` + ``right`` back into ``leftright`` in ``text`` so
    the two original token surfaces are not counted as missing source content."""
    for left, right in pairs:
        pat = re.compile(re.escape(left) + r"-\s*" + re.escape(right))
        text = pat.sub(left + right, text, count=1)
    return text


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """1-based (line, codepoint-column) of ``offset`` into ``text``."""
    if offset <= 0:
        return (1, 1)
    prefix = text[:offset]
    line = prefix.count("\n") + 1
    col = offset - (prefix.rfind("\n") + 1) + 1
    return (line, col)


# --- the pass ------------------------------------------------------------------


def run_deterministic_checks(
    *,
    markdown: str,
    semantic: SemanticDocument,
    ced: CanonicalExtractedDocument,
    candidates: Sequence[ExtractionCandidate] = (),
    source_page_text: Mapping[int, str] | None = None,
    gross_divergence_threshold: float = GROSS_DIVERGENCE_DEFAULT,
    ocr_confidence_threshold: float = OCR_CONFIDENCE_DEFAULT,
) -> DeterministicResult:
    """Run every deterministic check over ``markdown`` and return the issue list +
    the source-text match rate. Deterministic and side-effect free."""
    emitter = _Emitter()

    by_id = {s.segment_id: s for s in ced.accepted_segments}
    page_source = _resolve_source_text(ced, candidates, source_page_text)
    excluded_ids = _excluded_segment_ids(semantic)
    dehyphen_pairs = _dehyphenation_pairs(semantic, by_id)
    author_md = _author_visible(markdown)

    # -- coverage + gross divergence (runs first; before any LLM probe upstream) --
    match_rate, missing, missing_by_page = _coverage(
        author_md, semantic, ced, page_source, excluded_ids, dehyphen_pairs
    )
    gross = bool(page_source) and match_rate < gross_divergence_threshold

    if gross:
        emitter.add(
            severity="error", source_page=min(page_source, default=1),
            markdown_line=1, markdown_column=1, issue_type="gross_divergence",
            description=(
                f"source-text match rate {match_rate * 100:.1f}% is below the "
                f"gross-divergence threshold {gross_divergence_threshold * 100:.1f}% "
                "— the Markdown and the source PDF appear to be unrelated; per-token "
                "issues are suppressed"
            ),
            found=f"{match_rate:.4f}",
            expected=f">= {gross_divergence_threshold:.4f}",
        )
    else:
        for page in sorted(missing_by_page):
            toks = sorted(missing_by_page[page])
            emitter.add(
                severity="warning", source_page=page, markdown_line=1,
                markdown_column=1, issue_type="missing_content",
                description=(
                    f"{len(toks)} source token(s) from page {page} are absent from the "
                    f"delivered Markdown: {', '.join(toks)}"
                ),
                expected=", ".join(toks),
            )
        _numeric_checks(author_md, page_source, ced, excluded_ids, emitter)

    # -- structural checks (always run, even under gross divergence) --
    _table_checks(markdown, semantic, ced, emitter)
    if not gross:
        _reading_order_check(markdown, semantic, ced, excluded_ids, emitter)
    _ocr_confidence_check(ced, candidates, ocr_confidence_threshold, emitter)

    return DeterministicResult(
        issues=tuple(emitter.issues),
        source_text_match_rate=match_rate,
        gross_divergence=gross,
        gross_divergence_threshold=gross_divergence_threshold,
        missing_tokens=tuple(missing),
    )


# --- emitter -------------------------------------------------------------------


class _Emitter:
    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def add(self, **kw) -> None:
        self.issues.append(
            ValidationIssue(id=f"det-{len(self.issues) + 1:04d}", **kw)
        )


# --- source text resolution ---------------------------------------------------


def _resolve_source_text(
    ced: CanonicalExtractedDocument,
    candidates: Sequence[ExtractionCandidate],
    source_page_text: Mapping[int, str] | None,
) -> dict[int, str]:
    """Per-page extractable source text: the caller's ``source_page_text`` where given,
    else the accepted CED segments for that page, else the candidates' segments —
    "against candidates + PDF" (T077)."""
    pages = sorted({s.source.physical_page for s in ced.accepted_segments})
    provided = dict(source_page_text or {})
    out: dict[int, str] = {}
    for page in sorted(set(pages) | set(provided)):
        if page in provided:
            out[page] = provided[page]
            continue
        seg_text = " ".join(
            s.text for s in ced.accepted_segments if s.source.physical_page == page
        )
        if not seg_text:
            seen: set[str] = set()
            parts: list[str] = []
            for cand in candidates:
                for seg in cand.segments:
                    if seg.source.physical_page == page and seg.segment_id not in seen:
                        seen.add(seg.segment_id)
                        parts.append(seg.text)
            seg_text = " ".join(parts)
        out[page] = seg_text
    return out


# --- coverage -----------------------------------------------------------------


def _coverage(
    author_md: str,
    semantic: SemanticDocument,
    ced: CanonicalExtractedDocument,
    page_source: Mapping[int, str],
    excluded_ids: frozenset[str],
    dehyphen_pairs: list[tuple[str, str]],
) -> tuple[float, list[str], dict[int, list[str]]]:
    """Source-text coverage over the **delivered semantic expectations** (research
    §25.2): every accepted source token is expected in the Markdown *except* those an
    excluded segment owns (removed / collapsed / identical-evidence sibling) and those a
    recorded ``dehyphenate`` transform merged away. The self-check does not re-prove
    semantic fidelity (T066–T074 do) — it checks the render represents the already-
    verified ``SemanticDocument``."""
    excluded = Counter(
        tok
        for s in ced.accepted_segments
        if s.segment_id in excluded_ids
        for tok in _tokens(s.text)
    )
    md_bag = Counter(_tokens(author_md))

    total = 0
    matched = 0
    missing_by_page: dict[int, list[str]] = {}
    available = md_bag.copy()
    removed_left = excluded.copy()

    for page in sorted(page_source):
        source_text = _apply_dehyphenation(page_source[page], dehyphen_pairs)
        for tok in _tokens(source_text):
            if removed_left.get(tok, 0) > 0:
                removed_left[tok] -= 1  # accounted for by a recorded Stage-3 operation
                continue
            total += 1
            if available.get(tok, 0) > 0:
                available[tok] -= 1
                matched += 1
            else:
                missing_by_page.setdefault(page, []).append(tok)

    rate = 1.0 if total == 0 else matched / total
    missing = sorted({t for toks in missing_by_page.values() for t in toks})
    return (rate, missing, missing_by_page)


# --- numeric integrity ------------------------------------------------------


def _numeric_checks(
    author_md: str,
    page_source: Mapping[int, str],
    ced: CanonicalExtractedDocument,
    excluded_ids: frozenset[str],
    emitter: _Emitter,
) -> None:
    """A source numeric literal not reproduced verbatim in the author-visible Markdown
    (research §15 / FR-024). Sign, ``%``, separators and leading zeros are all part of
    the literal. Numbers the Markdown / HTML envelope generates (``rowspan="2"``,
    ``[L7]``) are already stripped from ``author_md``; numbers owned by an excluded
    segment (removed / collapsed / identical-evidence sibling) are not expected."""
    md_numbers = Counter(_numbers(author_md))
    leftover_md = md_numbers.copy()

    excluded_numbers = Counter(
        num
        for s in ced.accepted_segments
        if s.segment_id in excluded_ids
        for num in _numbers(s.text)
    )
    excluded_left = excluded_numbers.copy()

    unmatched: list[tuple[int, str]] = []
    for page in sorted(page_source):
        for num in _numbers(page_source[page]):
            if excluded_left.get(num, 0) > 0:
                excluded_left[num] -= 1
            elif leftover_md.get(num, 0) > 0:
                leftover_md[num] -= 1
            else:
                unmatched.append((page, num))

    spare = sorted(n for n, c in leftover_md.items() for _ in range(c))
    for page, num in unmatched:
        found = _nearest_number(num, spare)
        emitter.add(
            severity="error", source_page=page, markdown_line=1, markdown_column=1,
            issue_type="numeric_mismatch",
            description=(
                f"source numeric value {num!r} from page {page} is not reproduced "
                "verbatim in the delivered Markdown"
            ),
            expected=num,
            found=found,
        )


def _nearest_number(target: str, candidates: list[str]) -> str | None:
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda c: (abs(len(c) - len(target)), _digit_delta(c, target), c),
    )


def _digit_delta(a: str, b: str) -> int:
    da = [ch for ch in a if ch.isdigit()]
    db = [ch for ch in b if ch.isdigit()]
    common = min(len(da), len(db))
    return sum(1 for x, y in zip(da[:common], db[:common], strict=True) if x != y) + abs(
        len(da) - len(db)
    )


# --- table span geometry + duplicated header (research §25.2 / FR-020–FR-022) ------
#
# The rendered table is parsed into a placed-cell grid and compared **against the
# already-authoritative** ``SemanticDocument`` ``LogicalTable`` — never reconstructed
# independently from the PDF. A geometry disagreement (row / column count, ``th`` vs
# ``td``, ``rowspan``, ``colspan``, a missing / extra cell) is a ``table_shape`` issue.
# A duplicated header is flagged **only** when the render repeats the header row more
# often than the reconstructed table does.


@dataclass(frozen=True)
class _PCell:
    tag: str            # "th" | "td"
    rowspan: int
    colspan: int
    text: str           # NFC-casefold-stripped; rendered-space escaping left intact


@dataclass(frozen=True)
class _ParsedTable:
    rows: tuple[tuple[_PCell, ...], ...]
    line: int
    kind: str           # "pipe" | "html"

    @property
    def ncols(self) -> int:
        return max((sum(c.colspan for c in r) for r in self.rows), default=0)


def _ecell(cell: TableCell) -> _PCell:
    return _PCell(
        "th" if cell.is_header else "td",
        max(1, cell.rowspan),
        max(1, cell.colspan),
        _cnorm(cell.text),
    )


def _table_source_page(tblock: TableBlock, by_id: Mapping[str, AcceptedSegment]) -> int:
    """The first physical source page the reconstructed table draws on — from the
    logical cells' provenance / recorded page, then the block provenance. Deterministic
    fallback ``1`` only when no provenance is resolvable (research §25.8)."""
    pages: list[int] = []
    for row in tblock.table.rows:
        for c in row:
            if c.page is not None:
                pages.append(c.page)
            for sid in c.provenance:
                seg = by_id.get(sid)
                if seg is not None:
                    pages.append(seg.source.physical_page)
    for sid in tblock.provenance:
        seg = by_id.get(sid)
        if seg is not None:
            pages.append(seg.source.physical_page)
    return min(pages) if pages else 1


def _tables_min_page(
    expected: Sequence[TableBlock], by_id: Mapping[str, AcceptedSegment]
) -> int:
    pages = [_table_source_page(t, by_id) for t in expected]
    return min(pages) if pages else 1


def _table_checks(
    markdown: str,
    semantic: SemanticDocument,
    ced: CanonicalExtractedDocument,
    emitter: _Emitter,
) -> None:
    by_id = {s.segment_id: s for s in ced.accepted_segments}
    parsed = _parse_tables(markdown)
    expected = [b for b in semantic.blocks if isinstance(b, TableBlock)]
    fallback_page = _tables_min_page(expected, by_id)

    for i, tbl in enumerate(parsed):
        exp = expected[i] if i < len(expected) else None
        page = _table_source_page(exp, by_id) if exp is not None else fallback_page
        _check_one_table(tbl, exp, page, emitter)

    if len(parsed) != len(expected):
        emitter.add(
            severity="error", source_page=fallback_page, markdown_line=1,
            markdown_column=1, issue_type="table_shape",
            description=(
                f"the delivered Markdown has {len(parsed)} table(s); the reconstructed "
                f"document has {len(expected)} (FR-020/FR-021)"
            ),
            expected=str(len(expected)),
            found=str(len(parsed)),
        )


def _row_text(row: Sequence[_PCell]) -> tuple[str, ...]:
    return tuple(c.text for c in row)


def _check_one_table(
    tbl: _ParsedTable, exp: TableBlock | None, page: int, emitter: _Emitter
) -> None:
    line = tbl.line
    rendered: list[tuple[_PCell, ...]] = list(tbl.rows)
    if exp is None:
        return  # a spurious extra table — the table-count issue already reports it

    exp_rows = [tuple(_ecell(c) for c in row) for row in exp.table.rows]

    # --- R6: duplicated header (compare repeat counts, never "data row == header") --
    rendered_hdr = (
        sum(1 for r in rendered if _row_text(r) == _row_text(rendered[0]))
        if rendered else 0
    )
    expected_hdr = (
        sum(1 for r in exp_rows if _row_text(r) == _row_text(exp_rows[0]))
        if exp_rows else 0
    )
    if rendered and rendered_hdr >= 2 and rendered_hdr > expected_hdr:
        emitter.add(
            severity="error", source_page=page, markdown_line=line,
            markdown_column=1, issue_type="duplicated_header",
            description=(
                f"the table at Markdown line {line} repeats its header row "
                f"{rendered_hdr}×, but the reconstructed table carries it "
                f"{expected_hdr}× — a repeated physical header is being emitted into "
                "the output (FR-021/FR-022)"
            ),
            expected=str(expected_hdr),
            found=str(rendered_hdr),
        )
        rendered = _drop_surplus_header_rows(rendered, rendered_hdr - expected_hdr)

    # --- R5: placed-cell span geometry vs the authoritative LogicalTable ----------
    if len(rendered) != len(exp_rows):
        emitter.add(
            severity="error", source_page=page, markdown_line=line,
            markdown_column=1, issue_type="table_shape",
            description=(
                f"the table at Markdown line {line} has {len(rendered)} row(s); the "
                f"reconstructed table has {len(exp_rows)} (FR-020/FR-021)"
            ),
            expected=str(len(exp_rows)),
            found=str(len(rendered)),
        )
        return
    for r, (rrow, erow) in enumerate(zip(rendered, exp_rows, strict=True)):
        if len(rrow) != len(erow):
            emitter.add(
                severity="error", source_page=page, markdown_line=line,
                markdown_column=1, issue_type="table_shape",
                description=(
                    f"the table at Markdown line {line}, row {r} has {len(rrow)} "
                    f"cell(s); the reconstructed table has {len(erow)} (FR-020)"
                ),
                expected=str(len(erow)),
                found=str(len(rrow)),
            )
            continue
        for c, (rc, ec) in enumerate(zip(rrow, erow, strict=True)):
            diffs: list[str] = []
            if rc.tag != ec.tag:
                diffs.append(f"cell tag <{rc.tag}> vs <{ec.tag}>")
            if rc.rowspan != ec.rowspan:
                diffs.append(f"rowspan {rc.rowspan} vs {ec.rowspan}")
            if rc.colspan != ec.colspan:
                diffs.append(f"colspan {rc.colspan} vs {ec.colspan}")
            if diffs:
                emitter.add(
                    severity="error", source_page=page, markdown_line=line,
                    markdown_column=1, issue_type="table_shape",
                    description=(
                        f"the table at Markdown line {line}, row {r}, column {c} "
                        "disagrees with the reconstructed table geometry: "
                        + "; ".join(diffs) + " (FR-020/FR-021)"
                    ),
                    expected=(
                        f"<{ec.tag}> rowspan={ec.rowspan} colspan={ec.colspan}"
                    ),
                    found=f"<{rc.tag}> rowspan={rc.rowspan} colspan={rc.colspan}",
                )


def _drop_surplus_header_rows(
    rows: list[tuple[_PCell, ...]], surplus: int
) -> list[tuple[_PCell, ...]]:
    """Keep the first header occurrence, drop ``surplus`` of the later repeats so the
    span-geometry comparison is not swamped by the already-reported duplication."""
    if surplus <= 0 or not rows:
        return rows
    header = _row_text(rows[0])
    kept: list[tuple[_PCell, ...]] = []
    seen = 0
    for row in rows:
        if _row_text(row) == header:
            seen += 1
            if seen > 1 and surplus > 0:
                surplus -= 1
                continue
        kept.append(row)
    return kept


def _parse_tables(markdown: str) -> list[_ParsedTable]:
    lines = markdown.split("\n")
    out: list[_ParsedTable] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if _is_pipe_row(line) and i + 1 < len(lines) and _is_separator_row(lines[i + 1]):
            start = i + 1
            rows_text: list[tuple[str, ...]] = [_split_pipe(line)]
            i += 2
            while i < len(lines) and _is_pipe_row(lines[i].strip()):
                rows_text.append(_split_pipe(lines[i].strip()))
                i += 1
            prows = tuple(
                tuple(
                    _PCell("th" if ri == 0 else "td", 1, 1, _cnorm(cell))
                    for cell in row
                )
                for ri, row in enumerate(rows_text)
            )
            out.append(_ParsedTable(prows, start, "pipe"))
            continue
        if line == "<table>":
            start = i + 1
            block: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != "</table>":
                block.append(lines[i])
                i += 1
            i += 1
            out.append(_parse_html_table(block, start))
            continue
        i += 1
    return out


def _is_pipe_row(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and len(line) > 1


def _is_separator_row(line: str) -> bool:
    s = line.strip()
    if not _is_pipe_row(s):
        return False
    cells = _split_pipe(s)
    return bool(cells) and all(_SEPARATOR_CELL_RE.match(c) for c in cells)


def _split_pipe(line: str) -> tuple[str, ...]:
    inner = line.strip().strip("|")
    cells = _PIPE_SPLIT_RE.split(inner)
    return tuple(c.strip().replace("\\|", "|").replace("\\\\", "\\") for c in cells)


def _parse_html_table(block: list[str], line: int) -> _ParsedTable:
    joined = "\n".join(block)
    rows: list[tuple[_PCell, ...]] = []
    for tr in _TR_RE.findall(joined):
        cells: list[_PCell] = []
        for tag, attrs, content in _CELL_RE.findall(tr):
            rs = _ROWSPAN_RE.search(attrs)
            cs = _COLSPAN_RE.search(attrs)
            cells.append(
                _PCell(
                    tag.lower(),
                    int(rs.group(1)) if rs else 1,
                    int(cs.group(1)) if cs else 1,
                    _cnorm(_html_unescape(content)),
                )
            )
        rows.append(tuple(cells))
    return _ParsedTable(tuple(rows), line, "html")


def _html_unescape(text: str) -> str:
    return (
        text.replace("<br>", "\n")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


# --- reading order ----------------------------------------------------------


def _reading_order_check(
    markdown: str,
    semantic: SemanticDocument,
    ced: CanonicalExtractedDocument,
    excluded_ids: frozenset[str],
    emitter: _Emitter,
) -> None:
    by_id = {s.segment_id: s for s in ced.accepted_segments}
    md_norm = _norm(markdown)

    # A segment with no independent rendered occurrence must not be localised /
    # ordered: a removed or collapsed segment, an identical-evidence table sibling, or
    # a source surface a recorded ``dehyphenate`` transform merged away. The frozen
    # heuristic restriction (uniquely localisable literal, length ≥ 8) is unchanged.
    skip = set(excluded_ids)
    for t in semantic.segment_transforms:
        if t.kind == "dehyphenate":
            skip.update(t.segment_ids)

    located: list[tuple[str, int, int]] = []  # (segment_id, offset, page)
    for sid in ced.accepted_reading_order:
        if sid in skip:
            continue
        seg = by_id.get(sid)
        if seg is None:
            continue
        lit = _norm(seg.text).strip()
        if len(lit) < MIN_LOCALISABLE_CHARS:
            continue
        if md_norm.count(lit) != 1:
            continue
        located.append((sid, md_norm.index(lit), seg.source.physical_page))

    for (a_id, a_off, a_page), (b_id, b_off, _bp) in zip(
        located, located[1:], strict=False
    ):
        if b_off >= a_off:
            continue
        if _excused_by_reorder(semantic, a_id, b_id, a_off, b_off, located):
            continue
        line, col = _line_col(markdown, b_off)
        emitter.add(
            severity="error", source_page=a_page, markdown_line=line,
            markdown_column=col, issue_type="reading_order",
            description=(
                f"source segment {b_id} is rendered before {a_id}, contradicting the "
                "accepted CED reading order, and no structural_reorder covers it "
                "(FR-015/SC-023)"
            ),
            expected=f"{a_id} before {b_id}",
            found=f"{b_id} before {a_id}",
        )


def _excused_by_reorder(
    semantic: SemanticDocument,
    a_id: str,
    b_id: str,
    a_off: int,
    b_off: int,
    located: list[tuple[str, int, int]],
) -> bool:
    offsets = {sid: off for sid, off, _p in located}
    for sr in semantic.structural_reorder:
        affected = set(sr.affected_segment_ids)
        if {a_id, b_id} <= affected and a_id in sr.to_order and b_id in sr.to_order:
            rendered = sorted(
                (sid for sid in sr.to_order if sid in offsets),
                key=lambda s: offsets[s],
            )
            to_order = [s for s in sr.to_order if s in offsets]
            if rendered == to_order:
                return True
    return False


# --- OCR confidence -------------------------------------------------------


def _ocr_confidence_check(
    ced: CanonicalExtractedDocument,
    candidates: Sequence[ExtractionCandidate],
    threshold: float,
    emitter: _Emitter,
) -> None:
    flagged_pages: set[int] = set()
    for seg in ced.accepted_segments:
        ref = seg.source
        if ref.origin_kind != "ocr" or ref.ocr_confidence is None:
            continue
        if ref.ocr_confidence >= threshold:
            continue
        flagged_pages.add(ref.physical_page)
        emitter.add(
            severity="warning", source_page=ref.physical_page, markdown_line=1,
            markdown_column=1, issue_type="ocr_low_confidence",
            description=(
                f"OCR-derived segment {seg.segment_id} on page {ref.physical_page} has "
                f"normalised confidence {ref.ocr_confidence:.1f}, below the effective "
                f"threshold {threshold:.1f} (research §9a)"
            ),
            source_location=f"page {ref.physical_page}",
            found=f"{ref.ocr_confidence:.1f}",
            expected=f">= {threshold:.1f}",
        )

    for cand in candidates:
        for rec in cand.page_ocr:
            if not rec.ran_ocr or rec.physical_page in flagged_pages:
                continue
            # explicit per-run value when present — 0 is a valid floor, never a
            # truthiness fallback to the default (research §9a)
            floor = (
                threshold
                if getattr(rec, "confidence_threshold", None) is None
                else rec.confidence_threshold
            )
            if rec.mean_confidence >= floor and rec.low_confidence_regions == 0:
                continue
            flagged_pages.add(rec.physical_page)
            emitter.add(
                severity="warning", source_page=rec.physical_page, markdown_line=1,
                markdown_column=1, issue_type="ocr_low_confidence",
                description=(
                    f"OCR candidate region on page {rec.physical_page} has mean "
                    f"confidence {rec.mean_confidence:.1f} and "
                    f"{rec.low_confidence_regions} low-confidence region(s) "
                    f"(floor {floor:.1f})"
                ),
                source_location=f"page {rec.physical_page}",
                found=f"{rec.mean_confidence:.1f}",
                expected=f">= {floor:.1f}",
            )
