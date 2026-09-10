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
from solari_converter.model.canonical import CanonicalExtractedDocument
from solari_converter.model.semantic import SemanticDocument
from solari_converter.transform.tables import TableBlock

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
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_PIPE_SPLIT_RE = re.compile(r"(?<!\\)\|")
_SEPARATOR_CELL_RE = re.compile(r"^:?-{1,}:?$")
_TR_RE = re.compile(r"<tr>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(
    r"<(t[hd])((?:\s+[a-z]+=\"[^\"]*\")*)\s*>(.*?)</\1>", re.IGNORECASE | re.DOTALL
)
_COLSPAN_RE = re.compile(r'colspan="(\d+)"', re.IGNORECASE)


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

    page_source = _resolve_source_text(ced, candidates, source_page_text)

    # -- coverage + gross divergence (runs first; before any LLM probe upstream) --
    match_rate, missing, missing_by_page = _coverage(markdown, semantic, ced, page_source)
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
        _numeric_checks(markdown, page_source, emitter)

    # -- structural checks (always run, even under gross divergence) --
    _table_checks(markdown, semantic, emitter)
    if not gross:
        _reading_order_check(markdown, semantic, ced, emitter)
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
    markdown: str,
    semantic: SemanticDocument,
    ced: CanonicalExtractedDocument,
    page_source: Mapping[int, str],
) -> tuple[float, list[str], dict[int, list[str]]]:
    removed = Counter(
        tok
        for s in ced.accepted_segments
        if s.segment_id in semantic.removed_segment_ids
        for tok in _tokens(s.text)
    )
    md_bag = Counter(_tokens(markdown))

    total = 0
    matched = 0
    missing_by_page: dict[int, list[str]] = {}
    available = md_bag.copy()
    removed_left = removed.copy()

    for page in sorted(page_source):
        for tok in _tokens(page_source[page]):
            if removed_left.get(tok, 0) > 0:
                removed_left[tok] -= 1  # a logged stage-3 removal — not expected present
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
    markdown: str, page_source: Mapping[int, str], emitter: _Emitter
) -> None:
    md_numbers = Counter(_numbers(markdown))
    leftover_md = md_numbers.copy()

    unmatched: list[tuple[int, str]] = []
    for page in sorted(page_source):
        for num in _numbers(page_source[page]):
            if leftover_md.get(num, 0) > 0:
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


# --- table shape + duplicated header --------------------------------------


@dataclass(frozen=True)
class _ParsedTable:
    rows: tuple[tuple[str, ...], ...]
    ncols: int
    line: int


def _table_checks(markdown: str, semantic: SemanticDocument, emitter: _Emitter) -> None:
    parsed = _parse_tables(markdown)
    expected = [
        b for b in semantic.blocks if isinstance(b, TableBlock)
    ]

    for i, tbl in enumerate(parsed):
        norm = [tuple(c.casefold().strip() for c in r) for r in tbl.rows]
        if norm and norm[0] in norm[1:]:
            emitter.add(
                severity="error", source_page=1,
                markdown_line=tbl.line, markdown_column=1,
                issue_type="duplicated_header",
                description=(
                    f"the header row of the table at Markdown line {tbl.line} is "
                    "re-emitted as a data row (FR-022)"
                ),
                expected=" | ".join(tbl.rows[0]),
            )
        if i < len(expected):
            exp_rows = len(expected[i].table.rows)
            exp_cols = max(
                (sum(c.colspan for c in row) for row in expected[i].table.rows),
                default=0,
            )
            if (len(tbl.rows), tbl.ncols) != (exp_rows, exp_cols):
                emitter.add(
                    severity="error", source_page=1,
                    markdown_line=tbl.line, markdown_column=1,
                    issue_type="table_shape",
                    description=(
                        f"the delivered table at Markdown line {tbl.line} is "
                        f"{len(tbl.rows)}×{tbl.ncols}; the reconstructed table is "
                        f"{exp_rows}×{exp_cols} (FR-020/FR-021)"
                    ),
                    expected=f"{exp_rows}x{exp_cols}",
                    found=f"{len(tbl.rows)}x{tbl.ncols}",
                )

    if len(parsed) != len(expected):
        emitter.add(
            severity="error", source_page=1, markdown_line=1, markdown_column=1,
            issue_type="table_shape",
            description=(
                f"the delivered Markdown has {len(parsed)} table(s); the "
                f"reconstructed document has {len(expected)} (FR-020/FR-021)"
            ),
            expected=str(len(expected)),
            found=str(len(parsed)),
        )


def _parse_tables(markdown: str) -> list[_ParsedTable]:
    lines = markdown.split("\n")
    out: list[_ParsedTable] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if _is_pipe_row(line) and i + 1 < len(lines) and _is_separator_row(lines[i + 1]):
            start = i + 1
            header = _split_pipe(line)
            rows = [header]
            i += 2
            while i < len(lines) and _is_pipe_row(lines[i].strip()):
                rows.append(_split_pipe(lines[i].strip()))
                i += 1
            out.append(_ParsedTable(tuple(rows), len(header), start))
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
    return all(_SEPARATOR_CELL_RE.match(c) for c in _split_pipe(s)) and bool(_split_pipe(s))


def _split_pipe(line: str) -> tuple[str, ...]:
    inner = line.strip().strip("|")
    cells = _PIPE_SPLIT_RE.split(inner)
    return tuple(c.strip().replace("\\|", "|").replace("\\\\", "\\") for c in cells)


def _parse_html_table(block: list[str], line: int) -> _ParsedTable:
    joined = "\n".join(block)
    rows: list[tuple[str, ...]] = []
    ncols = 0
    for tr in _TR_RE.findall(joined):
        cells: list[str] = []
        span_total = 0
        for _tag, attrs, content in _CELL_RE.findall(tr):
            cells.append(_html_unescape(content).strip())
            m = _COLSPAN_RE.search(attrs)
            span_total += int(m.group(1)) if m else 1
        rows.append(tuple(cells))
        ncols = max(ncols, span_total)
    return _ParsedTable(tuple(rows), ncols, line)


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
    emitter: _Emitter,
) -> None:
    by_id = {s.segment_id: s for s in ced.accepted_segments}
    md_norm = _norm(markdown)

    located: list[tuple[str, int, int]] = []  # (segment_id, offset, page)
    for sid in ced.accepted_reading_order:
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
            floor = rec.confidence_threshold or threshold
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
