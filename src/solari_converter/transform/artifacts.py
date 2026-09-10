"""Stage-3 deterministic non-semantic artifact removal (T071).

Consumes the **Canonical Extracted Document** plus a **non-table** ``ReflowResult`` —
per the frozen post-T070 orchestration order, table ownership is determined first
(``tables = build_tables(ced)``) and only ``reflow(ced,
excluded_segment_ids=tables.consumed_segment_ids)`` reaches this module. Table-owned
content is therefore structurally absent here — this module never reclassifies a table
cell, a collapsed table header, or a table caption as document furniture (FR-020–FR-022
own that lineage exclusively).

Hard guarantees
----------------

* **deterministic** — a pure function of the CED + the non-table ``ReflowResult``; no
  LLM, no network, no dictionary, no randomness, no PDF reopening, no OCR re-run, no
  extraction retry;
* **conservative** — removal requires *positive* deterministic evidence. Ambiguous
  content is always kept; a suspicious-but-insufficiently-evidenced repeat is kept and
  recorded (``kept_due_to_ambiguity``), never silently dropped (FR-010);
* **stricter than T070's stitch transparency** — this module does **not** import or
  reuse ``transform.tables``'s ``_is_transparent`` rule (which only answers "may a
  table stitch ignore this segment", a much weaker question). This module defines its
  own independent, stricter evidence: exact comparison-key repetition, a required
  minimum-page threshold, a *majority*-of-pages requirement, bbox-top position
  consistency, and — critically — a **margin-band** requirement (the segment must sit
  at the very top or very bottom of its own page's accepted content) that stitch
  transparency never checks;
* **whole-unit** — a :class:`~solari_converter.transform.reflow.ReflowUnit` is removed
  only when it is a single-segment, standalone unit that itself carries the removal
  evidence. A unit that wrapped multiple segments together (e.g. a repeated header line
  that happens to wrap onto a distinct second line) is never partially stripped — its
  own joined text differs from the repeated family and it is kept whole;
* **never removes on shape alone** — verticality (tall/narrow bbox) is never, by
  itself, removal evidence. A bare number is never removed without positive
  page-number evidence (an explicit prefix, a physical-page match, or an adjacent-page
  sequence) *and* margin-band positioning. Years, prices, section/clause numbers, and
  legal references never match any removal family.

Thresholds are **named module constants** — not ``Config`` fields, not CLI options, not
folded into run identity, matching ``transform/tables.py``'s and ``transform/reflow.py``'s
pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from solari_converter.model.canonical import AcceptedSegment, CanonicalExtractedDocument
from solari_converter.reconcile.confidence import comparison_key
from solari_converter.reports.removal_log import RemovalEntry, RemovalLog, removal_entry_id
from solari_converter.transform.reflow import ReflowResult, ReflowUnit

__all__ = [
    "HEADER_FOOTER_MIN_PAGES",
    "FURNITURE_TOP_TOLERANCE",
    "MARGIN_BAND_TOLERANCE",
    "SUBSTRING_COLLISION_MIN_LENGTH",
    "AUTH_HEX_MIN_LENGTH",
    "BARCODE_OCR_RUN_MIN_LENGTH",
    "TALL_NARROW_ASPECT_RATIO",
    "PAGE_NUMBER_RE",
    "PAGE_NUMBER_BARE_RE",
    "AUTH_PHRASE_RE",
    "AUTH_HEX_RE",
    "BARCODE_OCR_RUN_RE",
    "ArtifactResult",
    "remove_artifacts",
]

# --- frozen thresholds (module constants; NOT Config; run identity unchanged) --------

#: A repeated running header/footer needs at least this many distinct physical-page
#: occurrences. Independent of, and stricter overall than, T070's stitch-transparency
#: 2-page threshold — combined below with a majority requirement and margin-band /
#: position-consistency checks stitch transparency never applies.
HEADER_FOOTER_MIN_PAGES: int = 2

#: Carried structural-hint kinds that mark a repeated segment as *meaningful content*
#: (a recurring section title, a figure caption). Their presence weighs against
#: furniture removal — an ambiguous repeat is kept and recorded, never removed (R2).
STRUCTURAL_CONTENT_HINT_KINDS: frozenset[str] = frozenset(
    {"heading", "subheading", "caption"}
)

#: Repeated furniture must recur with its bbox top within this many PDF units on every
#: counted page — position-consistency (own copy; not imported from ``transform.tables``,
#: to keep this module's removal authority fully independent of T070's rule).
FURNITURE_TOP_TOLERANCE: float = 4.0

#: A segment counts as sitting in a page's top or bottom margin band only if its own
#: top/bottom is within this many PDF units of the extreme (min top / max bottom) among
#: all of that physical page's accepted segments.
MARGIN_BAND_TOLERANCE: float = 1.0

#: A repeated-header/footer candidate's comparison-key text must be at least this many
#: characters before a substring match against other (non-candidate) content on the
#: same document counts as a body-content collision — avoids single-character noise.
SUBSTRING_COLLISION_MIN_LENGTH: int = 3

#: A standalone hex-looking token at or above this length is protocol/hash-mark evidence.
AUTH_HEX_MIN_LENGTH: int = 24

#: A standalone OCR-derived unspaced alphanumeric run at or above this length is
#: barcode/QR-OCR-like evidence.
BARCODE_OCR_RUN_MIN_LENGTH: int = 16

#: height / width at or above this ratio marks a segment "tall and narrow" — used only
#: to choose between the ``auth_stamp`` and ``vertical_auth_text`` *label* when a
#: segment already matched independent pattern evidence; verticality never triggers
#: removal on its own.
TALL_NARROW_ASPECT_RATIO: float = 2.0

#: An explicitly prefixed page number (own copy of the T070 pattern — this module's
#: removal authority is independent; a future change to ``transform.tables``'s pattern
#: must not silently loosen or tighten this module's removal decisions).
PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:[-–—]\s*)?(?:p\.|p[aá]g\.?|page|p[aá]gina|fls?\.|folha)\s*"
    r"(?:[0-9]{1,6}|[ivxlc]{1,6})\s*(?:/\s*[0-9]{1,6})?\s*(?:[-–—]\s*)?$",
    re.IGNORECASE,
)

#: A bare decimal page-number candidate — not evidence on its own; see
#: ``_page_number_evidence`` for the positional/sequence corroboration it still needs.
PAGE_NUMBER_BARE_RE = re.compile(
    r"^\s*(?:[-–—]\s*)?([0-9]{1,6})\s*(?:/\s*[0-9]{1,6})?\s*(?:[-–—]\s*)?$"
)

#: Deterministic authentication / signature phrases (PT/EN). Text-pattern only — no
#: image analysis, no computer vision, no PDF reopening.
AUTH_PHRASE_RE = re.compile(
    r"^\s*("
    r"digitally\s+signed|electronically\s+signed|"
    r"assinad[oa]\s+digitalmente|assinado\s+eletronicamente|"
    r"authenticated\s+copy|c[oó]pia\s+autenticada|"
    r"protocolo\s+de\s+autentica[cç][aã]o|autentica[cç][aã]o\s+digital"
    r")\s*[.:]?\s*$",
    re.IGNORECASE,
)

#: A standalone hex-looking protocol/hash mark.
AUTH_HEX_RE = re.compile(rf"^[0-9a-fA-F]{{{AUTH_HEX_MIN_LENGTH},}}$")

#: A standalone OCR-derived unspaced alphanumeric run (barcode/QR OCR artifact shape).
BARCODE_OCR_RUN_RE = re.compile(rf"^[A-Za-z0-9]{{{BARCODE_OCR_RUN_MIN_LENGTH},}}$")


def _key(text: str) -> str:
    return comparison_key(text).casefold()


# --- result type -------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactResult:
    """T071's output. ``kept_units`` is the retained subset of the input
    ``ReflowResult.units`` (order preserved) that T068/T069 consume next.
    ``removed_segment_ids`` is deterministic in-memory lineage — the committed
    ``removal-log.schema.json`` carries no ``segment_ids`` field (M1-style JSON
    minimalism), so T073's source-accounting invariant is proven against this set
    rather than against the persisted record."""

    kept_units: tuple[ReflowUnit, ...]
    removal_log: RemovalLog
    removed_segment_ids: frozenset[str] = field(default_factory=frozenset)


def remove_artifacts(
    ced: CanonicalExtractedDocument, reflow_result: ReflowResult
) -> ArtifactResult:
    """Detect and remove non-semantic artifacts from ``reflow_result``'s units.
    Deterministic; never mutates ``ced``; never considers a segment absent from
    ``reflow_result`` (table-owned content is structurally excluded upstream)."""
    return _Detector(ced, reflow_result).run()


@dataclass
class _Decision:
    unit: ReflowUnit
    element_type: str
    reason: str
    remove: bool
    kept_due_to_ambiguity: bool
    note: str | None = None


class _Detector:
    def __init__(
        self, ced: CanonicalExtractedDocument, reflow_result: ReflowResult
    ) -> None:
        self.ced = ced
        self.reflow_result = reflow_result
        self.by_id: dict[str, AcceptedSegment] = {
            s.segment_id: s for s in ced.accepted_segments
        }
        self.pages: list[int] = sorted(
            {s.source.physical_page for s in ced.accepted_segments}
        )
        self._page_top: dict[int, float] = {}
        self._page_bottom: dict[int, float] = {}
        for s in ced.accepted_segments:
            box = s.source.bbox
            if box is None:
                continue
            p = s.source.physical_page
            self._page_top[p] = min(self._page_top.get(p, box[1]), box[1])
            self._page_bottom[p] = max(self._page_bottom.get(p, box[3]), box[3])

        self._standalone: list[ReflowUnit] = [
            u for u in reflow_result.units if len(u.segment_ids) == 1
        ]
        self._decided: dict[str, _Decision] = {}  # unit.segment_ids[0] -> decision

    # -- geometry helpers -------------------------------------------------

    def _bbox(self, unit: ReflowUnit) -> tuple[float, float, float, float] | None:
        return unit.segments[0].source.bbox

    def _margin_band(self, unit: ReflowUnit) -> str | None:
        """``"top"`` / ``"bottom"`` if this standalone unit sits at the extreme of its
        own page's accepted content, else ``None``."""
        box = self._bbox(unit)
        if box is None:
            return None
        page = unit.page
        top = self._page_top.get(page)
        bottom = self._page_bottom.get(page)
        if top is not None and abs(box[1] - top) <= MARGIN_BAND_TOLERANCE:
            return "top"
        if bottom is not None and abs(box[3] - bottom) <= MARGIN_BAND_TOLERANCE:
            return "bottom"
        return None

    # -- run ----------------------------------------------------------------

    def run(self) -> ArtifactResult:
        self._detect_repeated_header_footer()
        self._detect_page_numbers()
        self._detect_auth_protocol()

        removed_ids: set[str] = set()
        entries: list[RemovalEntry] = []
        for sid, d in self._decided.items():
            seg = self.by_id[sid]
            if d.remove:
                removed_ids.add(sid)
            entries.append(
                RemovalEntry(
                    id=removal_entry_id(
                        page=seg.source.physical_page, element_type=d.element_type,
                        segment_ids=[sid],
                    ),
                    page=seg.source.physical_page,
                    element_type=d.element_type,  # type: ignore[arg-type]
                    text_excerpt=seg.text,
                    bbox=seg.source.bbox,
                    reason=d.reason,  # type: ignore[arg-type]
                    kept_due_to_ambiguity=d.kept_due_to_ambiguity,
                    note=d.note,
                )
            )
        entries.sort(key=lambda e: (e.page, e.element_type, e.id))

        kept_units = tuple(
            u for u in self.reflow_result.units
            if not (len(u.segment_ids) == 1 and u.segment_ids[0] in removed_ids)
        )

        log = RemovalLog(
            record_type="removal_log",
            schema_version="2.0",
            run_id=self.ced.run_id,
            tool_version=self.ced.tool_version,
            source_pdf=self.ced.source_pdf,
            source_sha256=self.ced.source_sha256,
            page_selection=self.ced.page_selection,
            entries=entries,
        )
        return ArtifactResult(
            kept_units=kept_units, removal_log=log,
            removed_segment_ids=frozenset(removed_ids),
        )

    # -- repeated running header / footer ------------------------------------

    def _body_contains(self, key: str, exclude_ids: set[str]) -> bool:
        if len(key) < SUBSTRING_COLLISION_MIN_LENGTH:
            return False
        for u in self.reflow_result.units:
            if set(u.segment_ids) & exclude_ids:
                continue
            if key in _key(u.text):
                return True
        return False

    def _structural_content_evidence(self, unit: ReflowUnit) -> bool:
        """A carried heading / subheading / caption hint on any of this unit's
        segments — a recurring section title or figure caption is meaningful content;
        its repetition must weigh *against* furniture removal (R2)."""
        ids = set(unit.segment_ids)
        return any(
            h.segment_id in ids and h.kind in STRUCTURAL_CONTENT_HINT_KINDS
            for h in self.ced.carried_structural_hints
        )

    def _detect_repeated_header_footer(self) -> None:
        by_key: dict[str, list[ReflowUnit]] = {}
        for u in self._standalone:
            by_key.setdefault(_key(u.text), []).append(u)

        for key, units in by_key.items():
            if not key:
                continue
            pages = {u.page for u in units}
            if len(pages) < HEADER_FOOTER_MIN_PAGES:
                continue  # a single occurrence can never establish repetition
            bands = {self._margin_band(u) for u in units}
            if bands - {"top", "bottom"} or None in bands or len(bands) != 1:
                continue  # not margin-positioned at all — not a furniture candidate
            tops = [self._bbox(u)[1] for u in units]  # type: ignore[index]
            if max(tops) - min(tops) > FURNITURE_TOP_TOLERANCE:
                continue  # not position-consistent — repeated content, not furniture

            band = next(iter(bands))
            element_type = "running_header" if band == "top" else "running_footer"
            exclude_ids = {u.segment_ids[0] for u in units}

            # R2: margin position + position-consistency are necessary but, on their
            # own, cannot turn a short or discontinuous set of occurrences into
            # removal authority. Each unmet condition below is a *keep* reason — an
            # ambiguous repeat is kept and recorded, never silently dropped (FR-010).
            pages_sorted = sorted(pages)
            contiguous_run = pages_sorted == list(
                range(pages_sorted[0], pages_sorted[-1] + 1)
            )
            majority = len(pages) > len(self.pages) / 2

            keep_reasons: list[str] = []
            if self._body_contains(key, exclude_ids):
                keep_reasons.append(
                    "identical text also appears in retained body content"
                )
            if any(self._structural_content_evidence(u) for u in units):
                keep_reasons.append(
                    "a carried heading/caption hint marks this as meaningful content"
                )
            if not contiguous_run:
                keep_reasons.append(
                    "the occurrence pages are discontinuous — a continuous running "
                    "header/footer cannot be established from a discontinuous set"
                )
            if not majority:
                keep_reasons.append(
                    "the text repeats on only a minority of the selected pages"
                )

            remove = not keep_reasons
            note = "; ".join(keep_reasons) or None
            for u in units:
                self._decided[u.segment_ids[0]] = _Decision(
                    unit=u, element_type=element_type, reason="matched_repeated",
                    remove=remove, kept_due_to_ambiguity=not remove, note=note,
                )

    # -- page numbers ---------------------------------------------------------

    def _bare_value(self, unit: ReflowUnit) -> int | None:
        m = PAGE_NUMBER_BARE_RE.match(unit.text)
        return int(m.group(1)) if m else None

    def _page_number_evidence(self, unit: ReflowUnit) -> bool:
        if PAGE_NUMBER_RE.match(unit.text):
            return True  # explicit prefix — positive evidence on its own
        value = self._bare_value(unit)
        if value is None:
            return False
        if value == unit.page:
            return True
        for delta in (-1, 1):
            for other in self._standalone:
                if other.page != unit.page + delta:
                    continue
                if self._bare_value(other) == value + delta:
                    return True
        return False

    def _detect_page_numbers(self) -> None:
        for u in self._standalone:
            sid = u.segment_ids[0]
            if sid in self._decided:
                continue
            if not self._page_number_evidence(u):
                continue
            if self._margin_band(u) is None:
                continue  # value evidence alone is not enough — position corroborates
            self._decided[sid] = _Decision(
                unit=u, element_type="page_number", reason="matched_pattern",
                remove=True, kept_due_to_ambiguity=False,
            )

    # -- authentication / protocol marks --------------------------------------

    def _detect_auth_protocol(self) -> None:
        for u in self._standalone:
            sid = u.segment_ids[0]
            if sid in self._decided:
                continue
            text = u.text.strip()
            seg = u.segments[0]
            tall_narrow = self._is_tall_narrow(seg)
            # R3: pattern SHAPE alone never authorizes deleting author content. A
            # genuine authentication stamp / protocol hash / OCR barcode sits in a
            # page margin band (the same independent, already-available deterministic
            # geometric signal page-number removal requires). A shape-only match in
            # mid-body — a git commit hash quoted in a technical paragraph, a
            # "Digitally signed…" sentence, an OCR-mangled identifier inside prose —
            # is kept, recorded as ambiguous. Verticality alone remains insufficient.
            in_margin = self._margin_band(u) is not None

            phrase_or_hex = AUTH_PHRASE_RE.match(text) or AUTH_HEX_RE.match(text)
            barcode_shape = (
                seg.source.origin_kind == "ocr"
                and BARCODE_OCR_RUN_RE.match(text)
                and " " not in text
            )

            if phrase_or_hex and in_margin:
                element_type = "vertical_auth_text" if tall_narrow else "auth_stamp"
                self._decided[sid] = _Decision(
                    unit=u, element_type=element_type, reason="matched_pattern",
                    remove=True, kept_due_to_ambiguity=False,
                )
                continue
            if barcode_shape and in_margin:
                self._decided[sid] = _Decision(
                    unit=u, element_type="barcode", reason="matched_pattern",
                    remove=True, kept_due_to_ambiguity=False,
                )
                continue
            if phrase_or_hex or barcode_shape:
                element_type = (
                    "barcode" if barcode_shape and not phrase_or_hex
                    else "vertical_auth_text" if tall_narrow
                    else "auth_stamp"
                )
                self._decided[sid] = _Decision(
                    unit=u, element_type=element_type, reason="matched_pattern",
                    remove=False, kept_due_to_ambiguity=True,
                    note="pattern shape only, not in a page margin band — kept",
                )

    @staticmethod
    def _is_tall_narrow(seg: AcceptedSegment) -> bool:
        box = seg.source.bbox
        if box is None:
            return False
        w = box[2] - box[0]
        h = box[3] - box[1]
        return w > 0 and h / w >= TALL_NARROW_ASPECT_RATIO
