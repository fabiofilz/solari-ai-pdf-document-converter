"""Docling extraction path A adapter (T046).

Path A (research §20; FR-060/FR-060a/FR-060b) processes the **original PDF directly**
through Docling and produces one :class:`~solari_converter.model.candidate.ExtractionCandidate`
with three separable outputs, exactly like every other extraction path:

1. **Literal content** — verbatim text, taken from Docling/docling-parse's *lowest-level*
   parsed-page evidence (``page.parsed_page.textline_cells[*].orig``), **never** from
   Docling's normalized, dehyphenated, ligature-expanded, merged ``DoclingDocument``
   item text (``TextItem.text``) and never from ``export_to_markdown()`` /
   ``export_to_text()``. An empirically observed example of why this boundary matters:
   two separate source lines on a real page were merged by Docling's document-assembly
   stage into one normalized string — that merged string must never become a segment's
   literal content (see ``test_candidate_never_contains_normalized_merged_text``).
2. **Candidate reading order** — evidence only (FR-060b), never authoritative. Derived
   from Docling's own per-page layout clusters (``page.predictions.layout.clusters``),
   which live in the **same coordinate space** as the parsed-page cells (both
   ``CoordOrigin.TOPLEFT`` after the docling-parse backend normalizes them) and whose
   ``.cells`` are — empirically verified against a real Docling 2.124.0 run — the exact
   same ``TextCell`` objects as ``parsed_page.textline_cells`` (matched here by Python
   object identity, never by a bbox/text heuristic). ``DoclingDocument.iterate_items()``
   is deliberately **not** used for ordering: its provenance bboxes live in the PDF's
   native ``BOTTOMLEFT`` coordinate space (a different space from the cells above), and
   its items already carry Docling's merged/normalized text — mixing that in here would
   reintroduce exactly the fidelity risk this module exists to avoid.
3. **Structural hints** — carried, never applied (FR-061c). One hint per matching
   layout-cluster label: ``title``/``section_header`` -> ``heading``; ``list_item`` ->
   ``list_item``; ``table`` -> ``table`` (region-level only — TableFormer's per-cell grid
   is *not* mapped here; row/column reconstruction is a later transform-stage concern);
   ``caption`` -> ``caption``; ``page_header``/``page_footer`` -> ``other`` (furniture
   evidence — **never removed here**, FR-064 owns that decision). A plain "text"/
   "picture"/etc. cluster gets no hint at all (no manufactured noise).

**Independence** (M2 / SC-024): this module imports neither ``extract/plumber_path``,
``extract/ocr_path``, ``extract/native_reliability``, nor anything under ``reconcile/``.
Docling itself is imported **lazily**, inside the methods that actually construct a
Docling component — every pure mapping function below (``_build_segment``,
``_build_candidate``, ``_cell_bbox``, ``_requested_pages``, ``_docling_page_range``,
``_verify_artifact_digests``) needs no Docling import at all and is exercised in
``tests/unit/test_docling_path.py`` against lightweight duck-typed stand-ins.

**OCR isolation** (path C, T050, remains the sole OCR authority): ``do_ocr`` is always
explicitly set ``False`` on every ``PdfPipelineOptions`` this module builds. No Docling
OCR engine of any kind is installed (see the ``docling-slim[...]`` extras chosen in
``pyproject.toml`` / the plan.md ledger) or ever instantiated by this module.

**Offline / fail-closed** (Principle V; SC-008): a project-controlled ``artifacts_path``
is mandatory — never ``None`` (Docling's own default is to auto-download on first use).
Before constructing any Docling component capable of model resolution,
:meth:`DoclingExtractionPath._verify_artifacts` SHA256-verifies every required model
file against the pinned digests below (mirroring
``benchmarks/ocr/models/README.md`` / ``rapidocr_engine.py``'s ``APPROVED_V1_REC_*``
pattern — this constant pair IS the runtime policy, kept consistent with
``scripts/docling_models/SHA256SUMS`` and the plan.md Justified-Dependency Ledger). A
missing artifacts path, a missing file, or a digest mismatch raises
:class:`DoclingModelUnavailable` — never a network fetch, never a silently-disabled
structural pass pretending to have run. ``HF_HUB_OFFLINE`` / ``HF_HUB_DISABLE_TELEMETRY``
are also set before any Docling import, as defence in depth.

Model preparation (setup-time only, never at processing runtime):
``scripts/fetch_docling_models.py`` (see ``scripts/docling_models/README.md``).
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
from pathlib import Path
from typing import Any

from solari_converter.model.candidate import CandidateReadingOrder, ExtractionCandidate
from solari_converter.model.provenance import SourceRef
from solari_converter.model.segment import SourceBackedSegment, StructuralHint, segment_id

from .base import EnvelopeFields

__all__ = [
    "TECHNIQUE",
    "LAYOUT_MODEL",
    "TABLEFORMER_MODEL",
    "REQUIRED_ARTIFACT_DIGESTS",
    "ENV_ARTIFACTS_PATH",
    "DoclingModelUnavailable",
    "DoclingExtractionPath",
]

TECHNIQUE = "docling"

# ---------------------------------------------------------------------------------------
# Pinned model identity + the authoritative runtime policy (mirrors
# extract/ocr_engines/rapidocr_engine.py's APPROVED_V1_REC_* pattern). Kept consistent
# with scripts/docling_models/README.md, scripts/docling_models/SHA256SUMS, and the
# "docling" entry in specs/001-pdf-markdown-converter/plan.md's Justified-Dependency
# Ledger. Nothing here is read from mutable external state at runtime.
# ---------------------------------------------------------------------------------------
LAYOUT_MODEL: dict[str, str] = {
    "repo_id": "docling-project/docling-layout-heron",
    "revision": "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8",  # immutable commit, not "main"
    "local_dir": "docling-project--docling-layout-heron",
    "license": "Apache-2.0",
}
TABLEFORMER_MODEL: dict[str, str] = {
    "repo_id": "docling-project/docling-models",
    "revision": "v2.3.0",  # tag; pinned commit fc0f2d45e2218ea24bce5045f58a389aed16dc23
    "local_dir": "docling-project--docling-models",
    "license": "CDLA-Permissive-2.0",
}

#: path relative to the artifacts root -> pinned SHA256. Recorded at acquisition
#: 2026-09-09 (scripts/docling_models/README.md has the full provenance record).
REQUIRED_ARTIFACT_DIGESTS: dict[str, str] = {
    "docling-project--docling-layout-heron/config.json": (
        "fdea30805ce2f5666b147fca941dcdd27ad468e27d6ed21902207d3da056a97d"
    ),
    "docling-project--docling-layout-heron/preprocessor_config.json": (
        "cd38cd59999e7a95d68e487fbe5132df3d4e5c32a0836add57e6126ba0c4eaf1"
    ),
    "docling-project--docling-layout-heron/model.safetensors": (
        "00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c"
    ),
    "docling-project--docling-models/model_artifacts/tableformer/accurate/tm_config.json": (
        "984e122ceb8ccf84d84c9d2882f6f2302a44b4f1e577babd6289892c36f3cffd"
    ),
    "docling-project--docling-models/model_artifacts/tableformer/accurate/"
    "tableformer_accurate.safetensors": (
        "2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9"
    ),
}

#: Same name ``scripts/fetch_docling_models.py`` reads — a shared contract, not a
#: coincidence: fetching and running against a mismatched directory is a setup mistake
#: this shared name is meant to prevent.
ENV_ARTIFACTS_PATH = "SOLARI_DOCLING_ARTIFACTS_PATH"

_PACKAGES_FOR_PROVENANCE: tuple[str, ...] = (
    "docling-slim",
    "docling-core",
    "docling-parse",
    "docling-ibm-models",
    "torch",
    "transformers",
    "huggingface-hub",
)

#: Layout-cluster label (DocItemLabel value) -> StructuralHint kind, for the labels that
#: carry real structural meaning (research §20 / FR-060b). Anything not listed here and
#: not in _FURNITURE_LABELS gets no hint at all — a plain "text"/"picture"/... cluster is
#: not manufactured evidence.
_HINT_KIND_BY_LABEL: dict[str, str] = {
    "title": "heading",
    "section_header": "heading",
    "list_item": "list_item",
    "table": "table",
    "caption": "caption",
}
#: Furniture labels carried as "other" evidence — never removed here (FR-064 owns that).
_FURNITURE_LABELS = frozenset({"page_header", "page_footer"})


class DoclingModelUnavailable(RuntimeError):
    """Required local Docling model artifacts are missing, unreadable, or fail digest
    verification. Always raised **before** any Docling component capable of model
    resolution is constructed — this type never triggers a network fetch itself.
    ``extract/base.py``'s ``run_path()`` catches it like any other path failure and
    records a ``status="failed"`` candidate; it never falls back to downloading, and
    never silently disables structural extraction while pretending it ran (Step 6 of
    the T046 implementation contract)."""


# =========================================================================================
# Pure helpers — no Docling import, fully unit-testable with duck-typed stand-ins
# =========================================================================================


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_artifact_digests(root: Path, digest_map: dict[str, str]) -> dict[str, str]:
    """Verify every ``root / rel_path`` against its pinned digest. Returns the verified
    digests (identical to ``digest_map`` on success). Raises
    :class:`DoclingModelUnavailable` on the first missing file or mismatch — no partial
    / best-effort acceptance."""
    verified: dict[str, str] = {}
    for rel_path, expected in digest_map.items():
        full = root / rel_path
        if not full.is_file():
            raise DoclingModelUnavailable(
                f"Docling model artifact missing: {full} (expected sha256 {expected}). "
                "Run `python scripts/fetch_docling_models.py` at setup time — path A "
                "refuses to download a model at document-processing runtime."
            )
        got = _sha256(full)
        if got != expected:
            raise DoclingModelUnavailable(
                f"Docling model artifact {full} does not match its pinned digest "
                f"(expected {expected}, got {got}). No silent substitution — re-run "
                "`python scripts/fetch_docling_models.py`."
            )
        verified[rel_path] = got
    return verified


def _resolve_artifacts_path(explicit: str | os.PathLike[str] | None) -> Path | None:
    raw = explicit if explicit is not None else os.environ.get(ENV_ARTIFACTS_PATH)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _package_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for pkg in _PACKAGES_FOR_PROVENANCE:
        try:
            out[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            out[pkg] = "unknown"
    return out


def _cell_bbox(cell: Any) -> tuple[float, float, float, float]:
    """Deterministic ``(l, t, r, b)`` extraction from a Docling text cell's
    ``BoundingRectangle`` — ``CoordOrigin.TOPLEFT`` after docling-parse backend
    normalization (empirically confirmed against a real Docling 2.124.0 conversion:
    every ``parsed_page.textline_cells[*].rect`` and every
    ``page.predictions.layout.clusters[*].bbox`` share this same space). This is the
    single coordinate convention ``SourceRef.bbox`` uses for path A; a future path B
    (pdfplumber's native bottom-left PDF user-space) must convert explicitly when
    aligning against this candidate."""
    box = cell.rect.to_bounding_box()
    return (float(box.l), float(box.t), float(box.r), float(box.b))


def _build_segment(cell: Any, *, page_no: int) -> tuple[SourceBackedSegment, bool]:
    """One literal segment from one Docling text cell.

    ``cell.orig`` — "original, untreated text ... before any downstream normalization"
    per docling-core's own field description — is the literal source. It is used
    **verbatim**: no ``.strip()``, no Unicode normalization, no whitespace collapsing,
    no dehyphenation, no ligature repair. Only when ``orig`` is empty/``None`` (never
    observed in practice for a native-text PDF, but not guaranteed by the type) does
    this fall back to ``cell.text`` — and that fallback is recorded as a
    ``StructuralHint`` on the segment itself, never silently presented as literal
    evidence (Step 9 of the T046 implementation contract).

    Returns ``(segment, used_fallback)``.
    """
    orig = getattr(cell, "orig", None)
    used_fallback = not orig
    literal_text: str = orig if orig else cell.text
    bbox = _cell_bbox(cell)
    sid = segment_id(page=page_no, bbox=bbox, text=literal_text)

    hints: list[StructuralHint] = []
    if used_fallback:
        hints.append(
            StructuralHint(
                kind="other",
                source_technique=TECHNIQUE,
                payload={
                    "docling_fallback": "text_used_because_orig_was_empty",
                    "docling_text": cell.text,
                },
            )
        )

    segment = SourceBackedSegment(
        segment_id=sid,
        text=literal_text,
        source=SourceRef(
            physical_page=page_no,
            bbox=bbox,
            origin_kind="native_text",
            extraction_technique=TECHNIQUE,
            ocr_languages=[],
            ocr_confidence=None,
        ),
        reading_order_index=0,  # patched once the candidate's global order is known
        structural_hints=hints,
    )
    return segment, used_fallback


def _cluster_label_str(cluster: Any) -> str:
    label = getattr(cluster, "label", None)
    value = getattr(label, "value", None)
    return value if value is not None else str(label)


def _order_and_hints_for_page(
    page: Any,
    cell_to_segment: dict[int, SourceBackedSegment],
    page_cells: list[Any],
) -> list[str]:
    """This page's block of segment_ids, in Docling's per-page layout-cluster order
    (clusters visited in the order Docling returned them; a cluster's own cells in the
    order Docling assigned them). A cell no cluster claimed is appended at the end of
    the page's block, in raw per-page order — no segment is ever left out of the
    reading order (evidence-only; FR-060b / FR-015). Structural hints are attached to
    the matching segments **in place** as a side effect (each segment's own
    ``structural_hints`` list is mutated, never its literal ``text``)."""
    order: list[str] = []
    seen: set[str] = set()

    predictions = getattr(page, "predictions", None)
    layout = getattr(predictions, "layout", None) if predictions is not None else None
    clusters = getattr(layout, "clusters", None) or []

    for cluster in clusters:
        label = _cluster_label_str(cluster)
        kind = _HINT_KIND_BY_LABEL.get(label)
        is_furniture = label in _FURNITURE_LABELS
        confidence = float(getattr(cluster, "confidence", 0.0))
        for cell in getattr(cluster, "cells", None) or []:
            segment = cell_to_segment.get(id(cell))
            if segment is None:  # a cell this cluster claims that isn't one of ours
                continue
            if kind is not None or is_furniture:
                segment.structural_hints.append(
                    StructuralHint(
                        kind=kind if kind is not None else "other",
                        source_technique=TECHNIQUE,
                        payload={"docling_label": label, "confidence": confidence},
                    )
                )
            if segment.segment_id not in seen:
                order.append(segment.segment_id)
                seen.add(segment.segment_id)

    for cell in page_cells:
        segment = cell_to_segment.get(id(cell))
        if segment is not None and segment.segment_id not in seen:
            order.append(segment.segment_id)
            seen.add(segment.segment_id)

    return order


def _requested_pages(page_selection_token: str | None, page_count: int) -> set[int] | None:
    """Decode the already-validated canonical page-selection token (research §14 /
    ``model/page_selection.py``'s ``normalized_token()`` — ``"all"`` or e.g.
    ``"2_5-7_10-12"``) into a concrete page set, purely so this adapter can build
    Docling's own contiguous ``page_range`` and filter which pages it reports evidence
    for. ``None`` means "the whole document" — this function does not re-validate the
    selection (that already happened upstream); it only decodes an already-trusted,
    frozen wire format."""
    if not page_selection_token or page_selection_token == "all":
        return None
    pages: set[int] = set()
    for part in page_selection_token.split("_"):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, _, hi_s = part.partition("-")
            pages.update(range(int(lo_s), int(hi_s) + 1))
        else:
            pages.add(int(part))
    resolved = {p for p in pages if 1 <= p <= page_count}
    return resolved or None


def _docling_page_range(requested: set[int] | None, page_count: int) -> tuple[int, int]:
    """Docling's ``DocumentConverter.convert(page_range=...)`` only accepts one
    contiguous inclusive range — the smallest range covering every requested page.
    Pages inside that range but not actually requested are filtered back out in
    :func:`_build_candidate` (Docling still has to process the gaps internally; this
    adapter simply does not report evidence for pages the caller did not ask for)."""
    if not requested:
        return (1, page_count)
    return (min(requested), max(requested))


def _build_candidate(
    conv_res: Any,
    *,
    envelope: EnvelopeFields,
    expected_pages: set[int],
    model_identity: dict[str, Any],
) -> ExtractionCandidate:
    """Pure mapping from a Docling ``ConversionResult``-shaped object to one
    :class:`ExtractionCandidate`. Reads only ``conv_res.pages[*].{page_no, parsed_page,
    predictions.layout.clusters}`` and ``conv_res.status`` — never
    ``conv_res.document`` (the normalized, merged, hint-applying representation is
    forbidden as a literal source; see the module docstring and
    ``test_no_docling_export_markdown_or_text_reachable_from_candidate_building``)."""
    del model_identity  # recorded by the caller via provenance channels T046 owns
    # (the ledger / setup-time record — see the module docstring); not a per-candidate
    # JSON field, since neither the frozen schema nor data-model.md defines one and
    # `extraction-candidate.schema.json` forbids additional properties (architecture
    # change is out of T046's scope — see Step 14 of the implementation contract).

    pages = list(getattr(conv_res, "pages", None) or [])
    segments: list[SourceBackedSegment] = []
    order: list[str] = []
    pages_covered: set[int] = set()
    fallback_count = 0

    for page in sorted(pages, key=lambda p: p.page_no):
        page_no = page.page_no
        if page_no not in expected_pages:
            continue
        pages_covered.add(page_no)

        parsed_page = getattr(page, "parsed_page", None)
        cells = list(getattr(parsed_page, "textline_cells", None) or []) if parsed_page else []
        if not cells:
            continue

        cell_to_segment: dict[int, SourceBackedSegment] = {}
        for cell in cells:
            segment, used_fallback = _build_segment(cell, page_no=page_no)
            segments.append(segment)
            cell_to_segment[id(cell)] = segment
            if used_fallback:
                fallback_count += 1

        order.extend(_order_and_hints_for_page(page, cell_to_segment, cells))

    index_by_segment_id = {sid: idx for idx, sid in enumerate(order)}
    for segment in segments:
        segment.reading_order_index = index_by_segment_id.get(segment.segment_id, len(order))

    conv_status = str(getattr(getattr(conv_res, "status", None), "value", "")).lower()
    status_details: list[str] = []
    if conv_status == "success":
        status = "ok"
    elif conv_status == "partial_success":
        status = "partial"
        status_details.append(f"docling ConversionStatus={conv_status}")
    else:
        status = "failed"
        status_details.append(f"docling ConversionStatus={conv_status or 'unknown'}")

    missing_pages = sorted(expected_pages - pages_covered)
    if missing_pages and status == "ok":
        status = "partial"
    if missing_pages:
        status_details.append(f"pages not covered: {missing_pages}")

    env = {
        k: envelope[k]
        for k in ("run_id", "tool_version", "source_pdf", "source_sha256", "page_selection")
    }
    return ExtractionCandidate(
        **env,
        technique=TECHNIQUE,
        status=status,
        status_detail="; ".join(status_details) or None,
        segments=segments,
        reading_order=CandidateReadingOrder(technique=TECHNIQUE, order=order),
        pages_covered=sorted(pages_covered),
    )


# =========================================================================================
# DoclingExtractionPath — the ExtractionPath implementation (extract/base.py's protocol)
# =========================================================================================


class DoclingExtractionPath:
    """Path A: Docling, operating directly on the original source PDF
    (``PdfSource.path`` — never another path's output, never another candidate;
    FR-060). Implements the ``ExtractionPath`` protocol from ``extract/base.py``.

    No import of ``extract/plumber_path``, ``extract/ocr_path``,
    ``extract/native_reliability``, or anything under ``reconcile/`` anywhere in this
    module (verified by ``test_module_imports_no_sibling_extraction_path_or_reconciliation``).
    """

    technique = TECHNIQUE

    def __init__(
        self,
        *,
        artifacts_path: str | os.PathLike[str] | None = None,
        device: str = "cpu",
        num_threads: int = 4,
    ) -> None:
        self._artifacts_path = _resolve_artifacts_path(artifacts_path)
        self._device = device
        self._num_threads = num_threads
        self._verified_digests: dict[str, str] | None = None

    # -- artifact verification (fail-closed, before any Docling model-resolution code
    #    is ever constructed) ---------------------------------------------------------

    def _verify_artifacts(self) -> dict[str, str]:
        if self._verified_digests is not None:
            return dict(self._verified_digests)
        if self._artifacts_path is None:
            raise DoclingModelUnavailable(
                "Docling artifacts_path is not configured (pass artifacts_path=... or "
                f"set {ENV_ARTIFACTS_PATH}). Run `python scripts/fetch_docling_models.py` "
                "at setup time — path A refuses to fall back to Docling's own "
                "auto-download-on-first-use behaviour."
            )
        self._verified_digests = _verify_artifact_digests(
            self._artifacts_path, REQUIRED_ARTIFACT_DIGESTS
        )
        return dict(self._verified_digests)

    @property
    def model_identity(self) -> dict[str, Any]:
        """Full provenance record. Raises :class:`DoclingModelUnavailable` — never
        describes an unverified model — until :meth:`_verify_artifacts` succeeds."""
        digests = self._verify_artifacts()
        return {
            "technique": TECHNIQUE,
            "layout_model": dict(LAYOUT_MODEL),
            "tableformer_model": dict(TABLEFORMER_MODEL),
            "artifact_digests": digests,
            "package_versions": _package_versions(),
            "device": self._device,
            "num_threads": self._num_threads,
            "do_ocr": False,
            "generate_parsed_pages": True,
            "enable_remote_services": False,
            "allow_external_plugins": False,
        }

    # -- Docling configuration (offline / local-only; OCR isolated) -------------------

    def _build_pipeline_options(self) -> Any:
        # Defence in depth: even though _verify_artifacts() + an explicit
        # artifacts_path already make a network model-fetch unreachable in practice,
        # these env vars ensure huggingface_hub itself refuses any request it might
        # otherwise attempt (Principle V / SC-008).
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        device_map = {
            "cpu": AcceleratorDevice.CPU,
            "cuda": AcceleratorDevice.CUDA,
            "mps": AcceleratorDevice.MPS,
            "xpu": AcceleratorDevice.XPU,
        }
        device = device_map.get(self._device, AcceleratorDevice.CPU)

        options = PdfPipelineOptions()
        options.do_ocr = False  # path C (T050) is the sole OCR authority
        options.do_table_structure = True
        options.generate_parsed_pages = True  # the literal-evidence layer this adapter reads
        options.generate_page_images = False
        options.generate_picture_images = False
        options.do_picture_classification = False
        options.do_picture_description = False
        options.do_code_enrichment = False
        options.do_formula_enrichment = False
        options.do_chart_extraction = False
        options.enable_remote_services = False
        options.allow_external_plugins = False
        options.artifacts_path = str(self._artifacts_path)
        options.accelerator_options = AcceleratorOptions(
            device=device, num_threads=self._num_threads
        )
        return options

    def _run_docling(self, pdf_path: Path, page_range: tuple[int, int]) -> Any:
        """Thin glue around the real Docling API — isolated so unit tests can
        monkeypatch this one method and exercise the pure mapping functions above
        without constructing a real ``DocumentConverter`` (which loads real model
        weights). This is the **only** place in this module that imports
        ``docling.document_converter`` / ``docling.datamodel.base_models``."""
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_options = self._build_pipeline_options()
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
        return converter.convert(str(pdf_path), page_range=page_range, raises_on_error=False)

    # -- ExtractionPath protocol --------------------------------------------------------

    def extract(self, source: Any, *, envelope: EnvelopeFields) -> ExtractionCandidate:
        """Read ``source`` (a ``pdf/loader.PdfSource`` handle) directly — never another
        path's output — and return path A's candidate. May raise; ``extract/base.py``'s
        ``run_path()`` converts any raise (including :class:`DoclingModelUnavailable`)
        into a ``status="failed"`` candidate (FR-060 edge case)."""
        self._verify_artifacts()  # fail closed BEFORE constructing anything Docling

        page_count = source.page_count
        requested = _requested_pages(envelope.get("page_selection"), page_count)
        page_range = _docling_page_range(requested, page_count)
        expected_pages = (
            requested if requested is not None else set(range(page_range[0], page_range[1] + 1))
        )

        conv_res = self._run_docling(Path(source.path), page_range)
        return _build_candidate(
            conv_res,
            envelope=envelope,
            expected_pages=expected_pages,
            model_identity=self.model_identity,
        )
