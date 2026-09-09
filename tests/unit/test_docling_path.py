"""T046 — failing-first tests for the Docling extraction path adapter
(GREEN owner: **T046**, ``src/solari_converter/extract/docling_path.py``).

Frozen behaviour under test (research §20, §24; FR-060/FR-060a/FR-060b/FR-061c;
SC-024/SC-026; Constitution V/VI/VII):

* literal fidelity — a text cell's ``.orig`` (never Docling's normalized/merged
  ``TextItem.text``) becomes the segment's stored text, byte/codepoint-for-codepoint,
  with no stripping, normalization, dehyphenation, or ligature repair;
* separation — structural hints are carried, never applied; reading order is evidence,
  never authoritative; no semantic transformation happens here;
* OCR isolation — ``do_ocr`` is always explicitly ``False``;
* offline / fail-closed — ``artifacts_path`` is mandatory; a missing or tampered model
  artifact raises before any Docling component capable of model resolution is built,
  and never triggers a network fetch;
* independence — this module imports neither a sibling extraction path nor
  reconciliation;
* geometry — bbox extraction from a Docling text cell is deterministic;
* provenance — package/model identity is recorded only after digest verification.

Every test here uses lightweight synthetic stand-ins for Docling's own types (plain
objects exposing only the handful of attributes the adapter actually reads) so the
mapping logic is exercised without constructing real Docling models. The one test that
touches a real ``DocumentConverter`` is separated into
``tests/acceptance/test_docling_path_smoke.py`` (run explicitly with ``-m acceptance``).
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "solari_converter" / "extract" / "docling_path.py"
)


def _mod():
    import solari_converter.extract.docling_path as docling_path  # GREEN owner: T046

    return docling_path


# ---------------------------------------------------------------------------------------
# Synthetic Docling-shaped test doubles (duck-typed; not real docling-core instances)
# ---------------------------------------------------------------------------------------


class FakeBBox:
    def __init__(self, l: float, t: float, r: float, b: float) -> None:  # noqa: E741
        self.l, self.t, self.r, self.b = l, t, r, b


class FakeRect:
    """Stands in for a real ``BoundingRectangle`` — only ``to_bounding_box()`` is used."""

    def __init__(self, l: float, t: float, r: float, b: float) -> None:  # noqa: E741
        self._box = FakeBBox(l, t, r, b)

    def to_bounding_box(self) -> FakeBBox:
        return self._box


class FakeCell:
    def __init__(
        self,
        *,
        text: str,
        orig: str | None,
        bbox: tuple[float, float, float, float],
        confidence: float = 1.0,
        from_ocr: bool = False,
    ) -> None:
        self.text = text
        self.orig = orig
        self.rect = FakeRect(*bbox)
        self.confidence = confidence
        self.from_ocr = from_ocr


class FakeCluster:
    def __init__(self, *, label: str, cells: list[FakeCell], confidence: float = 0.9) -> None:
        self.label = label
        self.cells = cells
        self.confidence = confidence


class FakeParsedPage:
    def __init__(self, cells: list[FakeCell]) -> None:
        self.textline_cells = cells


def _fake_page(page_no: int, cells: list[FakeCell], clusters: list[FakeCluster] | None = None):
    return SimpleNamespace(
        page_no=page_no,
        parsed_page=FakeParsedPage(cells),
        predictions=SimpleNamespace(
            layout=SimpleNamespace(clusters=clusters or []) if clusters is not None else None
        ),
    )


def _fake_conv_res(pages: list, status: str = "success"):
    return SimpleNamespace(pages=pages, status=SimpleNamespace(value=status), errors=[])


def _envelope(**overrides) -> dict:
    base = {
        "run_id": "a" * 16,
        "tool_version": "0.1.0",
        "source_pdf": "doc.pdf",
        "source_sha256": "b" * 64,
        "page_selection": "all",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------------------
# Independence — no import of a sibling extraction path or reconciliation (M2 / SC-024)
# ---------------------------------------------------------------------------------------


def test_module_imports_no_sibling_extraction_path_or_reconciliation() -> None:
    tree = ast.parse(MODULE_PATH.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden_substrings = ("plumber_path", "ocr_path", "native_reliability", "reconcile")
    for name in imported:
        for bad in forbidden_substrings:
            assert bad not in name, f"docling_path.py must not import {name!r} (contains {bad!r})"


def test_module_has_no_docling_import_at_top_level() -> None:
    """Docling (and its heavy transitive closure) must only be imported lazily inside
    the methods that actually invoke it, so the pure mapping helpers stay importable
    and testable without constructing any Docling component."""
    tree = ast.parse(MODULE_PATH.read_text())
    top_level_imports: set[str] = set()
    for node in tree.body:  # only module top level, not nested inside functions
        if isinstance(node, ast.Import):
            top_level_imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_imports.add(node.module)
    assert not any(name.startswith("docling") for name in top_level_imports), top_level_imports


# ---------------------------------------------------------------------------------------
# Literal fidelity (Constitution I; Step 9 of the T046 contract)
# ---------------------------------------------------------------------------------------


def test_literal_segment_uses_orig_not_normalized_text() -> None:
    m = _mod()
    cell = FakeCell(
        text="hello world",  # a hypothetically "normalized" value
        orig="hello  world­",  # the untreated original: double space + soft hyphen
        bbox=(10.0, 20.0, 100.0, 30.0),
    )
    seg, used_fallback = m._build_segment(cell, page_no=1)
    assert seg.text == "hello  world­"
    assert seg.text != "hello world"
    assert used_fallback is False


def test_literal_segment_preserves_whitespace_and_unicode_exactly() -> None:
    m = _mod()
    literal = "Café \t naïve—dash nbsp"
    cell = FakeCell(text="normalized version", orig=literal, bbox=(0.0, 0.0, 10.0, 10.0))
    seg, _ = m._build_segment(cell, page_no=1)
    assert seg.text == literal  # codepoint-for-codepoint, no strip/NFC/collapse


def test_literal_segment_preserves_line_final_hyphen() -> None:
    m = _mod()
    cell = FakeCell(text="algorithms", orig="algo-", bbox=(0.0, 0.0, 10.0, 10.0))
    seg, _ = m._build_segment(cell, page_no=1)
    assert seg.text == "algo-"


def test_missing_orig_falls_back_to_text_and_is_recorded() -> None:
    m = _mod()
    cell = FakeCell(text="fallback text", orig="", bbox=(0.0, 0.0, 5.0, 5.0))
    seg, used_fallback = m._build_segment(cell, page_no=1)
    assert used_fallback is True
    assert seg.text == "fallback text"
    # the fallback must be recorded as evidence, never silently presented as literal
    assert any(
        h.kind == "other" and h.payload.get("docling_fallback") for h in seg.structural_hints
    )


def test_missing_orig_none_also_falls_back() -> None:
    m = _mod()
    cell = FakeCell(text="only text available", orig=None, bbox=(0.0, 0.0, 5.0, 5.0))
    seg, used_fallback = m._build_segment(cell, page_no=1)
    assert used_fallback is True
    assert seg.text == "only text available"


def test_candidate_never_contains_normalized_merged_text() -> None:
    """Regression guard for the empirically-observed Docling behaviour: two source
    lines get merged into one normalized ``TextItem.text`` — that merged string must
    never appear as literal segment content."""
    m = _mod()
    cells = [
        FakeCell(
            text="MERGED PARAGRAPH",
            orig="This is the first line of body text.",
            bbox=(10.0, 10.0, 200.0, 20.0),
        ),
        FakeCell(
            text="MERGED PARAGRAPH",
            orig="This is a second wrapped line.",
            bbox=(10.0, 25.0, 200.0, 35.0),
        ),
    ]
    page = _fake_page(1, cells, clusters=[])
    conv_res = _fake_conv_res([page])
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    texts = [s.text for s in candidate.segments]
    assert "This is the first line of body text." in texts
    assert "This is a second wrapped line." in texts
    assert "MERGED PARAGRAPH" not in texts
    assert not any("MERGED" in t for t in texts)


# ---------------------------------------------------------------------------------------
# Geometry (Step 10)
# ---------------------------------------------------------------------------------------


def test_bbox_extraction_is_deterministic_ltrb_tuple() -> None:
    m = _mod()
    cell = FakeCell(text="x", orig="x", bbox=(1.5, 2.5, 3.5, 4.5))
    bbox = m._cell_bbox(cell)
    assert bbox == (1.5, 2.5, 3.5, 4.5)
    assert bbox == m._cell_bbox(cell)  # stable across repeated calls


def test_segment_id_is_derived_from_untransformed_geometry_and_literal_text() -> None:
    """Two cells at the same page/bbox/orig text must yield the same segment_id;
    changing the bbox must change it — the id is never derived from a transformed
    representation."""
    m = _mod()
    a = FakeCell(text="ignored", orig="same text", bbox=(1.0, 2.0, 3.0, 4.0))
    b = FakeCell(text="also ignored but different", orig="same text", bbox=(1.0, 2.0, 3.0, 4.0))
    seg_a, _ = m._build_segment(a, page_no=1)
    seg_b, _ = m._build_segment(b, page_no=1)
    assert seg_a.segment_id == seg_b.segment_id

    c = FakeCell(text="ignored", orig="same text", bbox=(9.0, 9.0, 20.0, 20.0))
    seg_c, _ = m._build_segment(c, page_no=1)
    assert seg_c.segment_id != seg_a.segment_id


def test_segment_source_ref_is_native_text_docling_with_no_ocr_fields() -> None:
    m = _mod()
    cell = FakeCell(text="x", orig="x", bbox=(0.0, 0.0, 1.0, 1.0))
    seg, _ = m._build_segment(cell, page_no=3)
    assert seg.source.physical_page == 3
    assert seg.source.origin_kind == "native_text"
    assert seg.source.extraction_technique == "docling"
    assert seg.source.ocr_languages == []
    assert seg.source.ocr_confidence is None
    assert seg.source.bbox == (0.0, 0.0, 1.0, 1.0)


# ---------------------------------------------------------------------------------------
# Separation — structural hints carried, not applied; reading order evidence-only
# ---------------------------------------------------------------------------------------


def test_heading_cluster_is_carried_as_hint_not_applied() -> None:
    m = _mod()
    heading_cell = FakeCell(text="H", orig="Section Heading", bbox=(0.0, 0.0, 50.0, 10.0))
    body_cell = FakeCell(text="B", orig="body text", bbox=(0.0, 15.0, 50.0, 25.0))
    clusters = [
        FakeCluster(label="section_header", cells=[heading_cell], confidence=0.8),
        FakeCluster(label="text", cells=[body_cell], confidence=0.9),
    ]
    page = _fake_page(1, [heading_cell, body_cell], clusters=clusters)
    conv_res = _fake_conv_res([page])
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    heading_seg = next(s for s in candidate.segments if s.text == "Section Heading")
    body_seg = next(s for s in candidate.segments if s.text == "body text")

    assert any(h.kind == "heading" for h in heading_seg.structural_hints)
    assert heading_seg.structural_hints[0].source_technique == "docling"
    assert not any(h.kind == "heading" for h in body_seg.structural_hints)

    # the hint is carried as evidence — the segment's own literal text is untouched,
    # and nothing in the candidate model marks it as an applied heading
    assert heading_seg.text == "Section Heading"


def test_list_item_and_table_and_caption_clusters_map_to_declared_hint_kinds() -> None:
    m = _mod()
    li = FakeCell(text="li", orig="- item one", bbox=(0.0, 0.0, 20.0, 10.0))
    tbl = FakeCell(text="t", orig="42", bbox=(0.0, 20.0, 20.0, 30.0))
    cap = FakeCell(text="c", orig="Figure 1: a caption", bbox=(0.0, 40.0, 20.0, 50.0))
    clusters = [
        FakeCluster(label="list_item", cells=[li]),
        FakeCluster(label="table", cells=[tbl]),
        FakeCluster(label="caption", cells=[cap]),
    ]
    page = _fake_page(1, [li, tbl, cap], clusters=clusters)
    conv_res = _fake_conv_res([page])
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    kinds_by_text = {s.text: {h.kind for h in s.structural_hints} for s in candidate.segments}
    assert "list_item" in kinds_by_text["- item one"]
    assert "table" in kinds_by_text["42"]
    assert "caption" in kinds_by_text["Figure 1: a caption"]


def test_page_header_and_footer_are_carried_as_other_not_removed() -> None:
    """A page header/footer is furniture evidence only — T046 must not remove it, only
    record it (removal is a later semantic-transformation concern, FR-064)."""
    m = _mod()
    header_cell = FakeCell(text="h", orig="Running Header", bbox=(0.0, 0.0, 50.0, 10.0))
    footer_cell = FakeCell(text="f", orig="Page 3", bbox=(0.0, 90.0, 50.0, 100.0))
    clusters = [
        FakeCluster(label="page_header", cells=[header_cell]),
        FakeCluster(label="page_footer", cells=[footer_cell]),
    ]
    page = _fake_page(1, [header_cell, footer_cell], clusters=clusters)
    conv_res = _fake_conv_res([page])
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    texts = [s.text for s in candidate.segments]
    assert "Running Header" in texts  # never removed here
    assert "Page 3" in texts
    header_seg = next(s for s in candidate.segments if s.text == "Running Header")
    assert any(
        h.kind == "other" and h.payload.get("docling_label") == "page_header"
        for h in header_seg.structural_hints
    )


def test_plain_text_cluster_gets_no_noise_hint() -> None:
    m = _mod()
    cell = FakeCell(text="p", orig="ordinary paragraph text", bbox=(0.0, 0.0, 50.0, 10.0))
    clusters = [FakeCluster(label="text", cells=[cell])]
    page = _fake_page(1, [cell], clusters=clusters)
    conv_res = _fake_conv_res([page])
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    seg = candidate.segments[0]
    assert seg.structural_hints == []


def test_reading_order_is_a_separate_field_never_reordering_segments_list() -> None:
    m = _mod()
    a = FakeCell(text="a", orig="first", bbox=(0.0, 0.0, 10.0, 10.0))
    b = FakeCell(text="b", orig="second", bbox=(0.0, 20.0, 10.0, 30.0))
    # clusters visit them in reverse order deliberately
    clusters = [FakeCluster(label="text", cells=[b]), FakeCluster(label="text", cells=[a])]
    page = _fake_page(1, [a, b], clusters=clusters)
    conv_res = _fake_conv_res([page])
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    # segments list preserves cell encounter order (never silently re-ordered)
    assert [s.text for s in candidate.segments] == ["first", "second"]
    # the reading order (evidence only) reflects the cluster-visit order instead
    seg_by_text = {s.text: s for s in candidate.segments}
    assert candidate.reading_order.order == [
        seg_by_text["second"].segment_id,
        seg_by_text["first"].segment_id,
    ]
    assert candidate.reading_order.technique == "docling"


def test_reading_order_index_matches_position_in_reading_order() -> None:
    m = _mod()
    a = FakeCell(text="a", orig="first", bbox=(0.0, 0.0, 10.0, 10.0))
    b = FakeCell(text="b", orig="second", bbox=(0.0, 20.0, 10.0, 30.0))
    clusters = [FakeCluster(label="text", cells=[b]), FakeCluster(label="text", cells=[a])]
    page = _fake_page(1, [a, b], clusters=clusters)
    conv_res = _fake_conv_res([page])
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    for idx, sid in enumerate(candidate.reading_order.order):
        seg = next(s for s in candidate.segments if s.segment_id == sid)
        assert seg.reading_order_index == idx


def test_unclustered_cell_still_gets_an_order_position() -> None:
    """A cell that no cluster claimed must still appear in the reading order (no data
    loss) — appended after the clustered cells on its page."""
    m = _mod()
    clustered = FakeCell(text="c", orig="clustered", bbox=(0.0, 0.0, 10.0, 10.0))
    orphan = FakeCell(text="o", orig="orphan", bbox=(0.0, 50.0, 10.0, 60.0))
    clusters = [FakeCluster(label="text", cells=[clustered])]
    page = _fake_page(1, [clustered, orphan], clusters=clusters)
    conv_res = _fake_conv_res([page])
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    assert len(candidate.reading_order.order) == 2
    seg_by_text = {s.text: s for s in candidate.segments}
    assert seg_by_text["orphan"].segment_id in candidate.reading_order.order
    # orphan comes after the clustered cell
    order = candidate.reading_order.order
    assert order.index(seg_by_text["clustered"].segment_id) < order.index(
        seg_by_text["orphan"].segment_id
    )


def test_no_docling_export_markdown_or_text_reachable_from_candidate_building() -> None:
    """`_build_candidate` must never call an export/markdown/text method on anything --
    only read cell/cluster attributes. Simulated by a conv_res whose `.document` would
    raise if any export-shaped attribute were ever accessed."""
    m = _mod()

    class BoobyTrappedDocument:
        def __getattr__(self, name: str):
            raise AssertionError(f"docling_path touched forbidden document API: {name}")

    cell = FakeCell(text="x", orig="literal", bbox=(0.0, 0.0, 10.0, 10.0))
    page = _fake_page(1, [cell], clusters=[])
    conv_res = SimpleNamespace(
        pages=[page],
        status=SimpleNamespace(value="success"),
        errors=[],
        document=BoobyTrappedDocument(),
    )
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    assert candidate.segments[0].text == "literal"


# ---------------------------------------------------------------------------------------
# Candidate envelope / technique / status
# ---------------------------------------------------------------------------------------


def test_candidate_technique_and_envelope_fields() -> None:
    m = _mod()
    cell = FakeCell(text="x", orig="x", bbox=(0.0, 0.0, 1.0, 1.0))
    page = _fake_page(1, [cell], clusters=[])
    conv_res = _fake_conv_res([page])
    env = _envelope(page_selection="all")
    candidate = m._build_candidate(conv_res, envelope=env, expected_pages={1}, model_identity={})
    assert candidate.technique == "docling"
    assert candidate.record_type == "extraction_candidate"
    assert candidate.run_id == env["run_id"]
    assert candidate.tool_version == env["tool_version"]
    assert candidate.source_pdf == env["source_pdf"]
    assert candidate.source_sha256 == env["source_sha256"]
    assert candidate.page_selection == env["page_selection"]


def test_candidate_status_ok_on_docling_success() -> None:
    m = _mod()
    cell = FakeCell(text="x", orig="x", bbox=(0.0, 0.0, 1.0, 1.0))
    page = _fake_page(1, [cell], clusters=[])
    conv_res = _fake_conv_res([page], status="success")
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    assert candidate.status == "ok"
    assert candidate.status_detail is None
    assert candidate.pages_covered == [1]


def test_candidate_status_partial_on_docling_partial_success() -> None:
    m = _mod()
    cell = FakeCell(text="x", orig="x", bbox=(0.0, 0.0, 1.0, 1.0))
    page = _fake_page(1, [cell], clusters=[])
    conv_res = _fake_conv_res([page], status="partial_success")
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    assert candidate.status == "partial"


def test_candidate_status_failed_on_docling_failure() -> None:
    m = _mod()
    conv_res = _fake_conv_res([], status="failure")
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1},
        model_identity={},
    )
    assert candidate.status == "failed"


def test_candidate_status_partial_when_a_requested_page_is_missing() -> None:
    """FR-060 edge case: if Docling silently drops a page path A was asked to cover
    (e.g. an internal per-page failure), the candidate must not claim full success."""
    m = _mod()
    cell = FakeCell(text="x", orig="x", bbox=(0.0, 0.0, 1.0, 1.0))
    page = _fake_page(1, [cell], clusters=[])
    conv_res = _fake_conv_res([page], status="success")  # doc-level success...
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(),
        expected_pages={1, 2},
        model_identity={},  # ...but page 2 never came back
    )
    assert candidate.status == "partial"
    assert "2" in (candidate.status_detail or "")


def test_page_selection_token_parsing_all_and_ranges() -> None:
    m = _mod()
    assert m._requested_pages("all", page_count=10) is None
    assert m._requested_pages(None, page_count=10) is None
    assert m._requested_pages("2_5-7_10-12", page_count=20) == {2, 5, 6, 7, 10, 11, 12}
    assert m._requested_pages("3", page_count=5) == {3}


def test_docling_page_range_from_requested_pages() -> None:
    m = _mod()
    assert m._docling_page_range(None, page_count=10) == (1, 10)
    assert m._docling_page_range({2, 5, 7}, page_count=10) == (2, 7)
    assert m._docling_page_range({4}, page_count=10) == (4, 4)


def test_pages_outside_requested_selection_are_excluded_from_segments() -> None:
    m = _mod()
    cell1 = FakeCell(text="1", orig="page one text", bbox=(0.0, 0.0, 10.0, 10.0))
    cell2 = FakeCell(text="2", orig="page two text", bbox=(0.0, 0.0, 10.0, 10.0))
    page1 = _fake_page(1, [cell1], clusters=[])
    page2 = _fake_page(2, [cell2], clusters=[])
    conv_res = _fake_conv_res([page1, page2])
    candidate = m._build_candidate(
        conv_res,
        envelope=_envelope(page_selection="1"),
        expected_pages={1},
        model_identity={},
    )
    assert [s.text for s in candidate.segments] == ["page one text"]
    assert candidate.pages_covered == [1]


# ---------------------------------------------------------------------------------------
# OCR isolation (Step 13)
# ---------------------------------------------------------------------------------------


def test_pipeline_options_disable_ocr_explicitly() -> None:
    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path="/tmp/does-not-need-to-exist-for-this-check")
    opts = path._build_pipeline_options()
    assert opts.do_ocr is False


def test_pipeline_options_disable_remote_services_and_plugins() -> None:
    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path="/tmp/does-not-need-to-exist-for-this-check")
    opts = path._build_pipeline_options()
    assert opts.enable_remote_services is False
    assert opts.allow_external_plugins is False


def test_pipeline_options_generate_parsed_pages_true() -> None:
    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path="/tmp/does-not-need-to-exist-for-this-check")
    opts = path._build_pipeline_options()
    assert opts.generate_parsed_pages is True


def test_pipeline_options_device_is_explicit_cpu_by_default() -> None:
    m = _mod()
    from docling.datamodel.accelerator_options import AcceleratorDevice

    path = m.DoclingExtractionPath(artifacts_path="/tmp/does-not-need-to-exist-for-this-check")
    opts = path._build_pipeline_options()
    assert opts.accelerator_options.device == AcceleratorDevice.CPU.value or (
        opts.accelerator_options.device == AcceleratorDevice.CPU
    )


def test_pipeline_options_artifacts_path_is_never_none() -> None:
    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path="/tmp/does-not-need-to-exist-for-this-check")
    opts = path._build_pipeline_options()
    assert opts.artifacts_path is not None


# ---------------------------------------------------------------------------------------
# Offline / fail-closed (Step 6, Step 15 "Offline")
# ---------------------------------------------------------------------------------------


def test_artifacts_path_is_mandatory() -> None:
    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path=None)
    with pytest.raises(m.DoclingModelUnavailable):
        path._verify_artifacts()


def test_artifacts_path_from_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    m = _mod()
    monkeypatch.setenv(m.ENV_ARTIFACTS_PATH, str(tmp_path))
    path = m.DoclingExtractionPath()
    assert path._artifacts_path == tmp_path.resolve()


def test_missing_model_artifact_fails_closed(tmp_path: Path) -> None:
    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path=tmp_path)  # empty directory
    with pytest.raises(m.DoclingModelUnavailable):
        path._verify_artifacts()


def test_tampered_model_digest_fails_closed(tmp_path: Path) -> None:
    m = _mod()
    # Every required file exists but none matches its pinned digest.
    for rel_path in m.REQUIRED_ARTIFACT_DIGESTS:
        dest = tmp_path / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"definitely not the pinned artifact")
    path = m.DoclingExtractionPath(artifacts_path=tmp_path)
    with pytest.raises(m.DoclingModelUnavailable, match="digest|checksum|sha256"):
        path._verify_artifacts()


def test_verified_artifacts_match_pinned_digests_exactly(tmp_path: Path) -> None:
    """A directory whose files genuinely match every pinned digest verifies cleanly and
    reports the exact digests -- proving the check is a real byte comparison, not a
    name/size heuristic."""
    m = _mod()
    # Forging a preimage for the real pinned sha256 values is infeasible, so the
    # *mechanism* is verified with a controlled single-file digest map instead.
    fake_digest_map = {"only/file.bin": hashlib.sha256(b"hello docling").hexdigest()}
    (tmp_path / "only").mkdir()
    (tmp_path / "only" / "file.bin").write_bytes(b"hello docling")
    digests = m._verify_artifact_digests(tmp_path, fake_digest_map)
    assert digests == fake_digest_map


def test_verify_artifact_digests_rejects_mismatch(tmp_path: Path) -> None:
    m = _mod()
    (tmp_path / "f.bin").write_bytes(b"actual content")
    wrong = {"f.bin": hashlib.sha256(b"different content").hexdigest()}
    with pytest.raises(m.DoclingModelUnavailable):
        m._verify_artifact_digests(tmp_path, wrong)


def test_verify_artifact_digests_rejects_missing_file(tmp_path: Path) -> None:
    m = _mod()
    wrong = {"missing.bin": "0" * 64}
    with pytest.raises(m.DoclingModelUnavailable):
        m._verify_artifact_digests(tmp_path, wrong)


def test_model_identity_raises_before_verification_succeeds(tmp_path: Path) -> None:
    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path=tmp_path)  # empty -> will fail verification
    with pytest.raises(m.DoclingModelUnavailable):
        _ = path.model_identity


def test_no_download_helper_is_ever_called_by_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verification failure must never be "solved" by fetching -- there is no code path
    in the adapter that imports a download function at all (this module has none to
    monkeypatch away, which is itself the assertion)."""
    m = _mod()
    assert not hasattr(m, "download_models")
    assert not hasattr(m, "hf_hub_download")
    assert not hasattr(m, "snapshot_download")


# ---------------------------------------------------------------------------------------
# Provenance (Step 14)
# ---------------------------------------------------------------------------------------


def test_model_identity_records_pinned_model_repos_and_revisions(tmp_path: Path) -> None:
    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path=tmp_path)

    def _fake_verify() -> dict[str, str]:
        return dict(m.REQUIRED_ARTIFACT_DIGESTS)

    path._verify_artifacts = _fake_verify  # type: ignore[method-assign]
    identity = path.model_identity
    assert identity["layout_model"]["repo_id"] == "docling-project/docling-layout-heron"
    assert identity["layout_model"]["revision"] == "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"
    assert identity["tableformer_model"]["repo_id"] == "docling-project/docling-models"
    assert identity["tableformer_model"]["revision"] == "v2.3.0"
    assert identity["artifact_digests"] == m.REQUIRED_ARTIFACT_DIGESTS
    assert identity["do_ocr"] is False
    assert identity["device"] == "cpu"


def test_model_identity_includes_installed_package_versions(tmp_path: Path) -> None:
    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path=tmp_path)
    path._verify_artifacts = lambda: dict(m.REQUIRED_ARTIFACT_DIGESTS)  # type: ignore[method-assign]
    identity = path.model_identity
    assert "package_versions" in identity
    assert "docling-slim" in identity["package_versions"]


# ---------------------------------------------------------------------------------------
# run_path() integration (extract/base.py, T043 — already frozen)
# ---------------------------------------------------------------------------------------


def test_run_path_converts_model_unavailable_into_failed_candidate(tmp_path: Path) -> None:
    from solari_converter.extract.base import run_path

    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path=tmp_path)  # empty -> fails verification
    envelope = _envelope()
    candidate = run_path(
        path, source=SimpleNamespace(path="doc.pdf", page_count=1), envelope=envelope
    )
    assert candidate.status == "failed"
    assert candidate.technique == "docling"
    assert candidate.segments == []


def test_run_path_never_falls_back_to_a_different_extraction_technique(tmp_path: Path) -> None:
    """A failed Docling path must be recorded as a failed `docling` candidate — never
    silently relabelled as another technique or silently dropped."""
    from solari_converter.extract.base import run_path

    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path=tmp_path)
    candidate = run_path(
        path, source=SimpleNamespace(path="doc.pdf", page_count=1), envelope=_envelope()
    )
    assert candidate.technique == "docling"


# ---------------------------------------------------------------------------------------
# Network — the autouse no-egress guard (conftest.py) covers every test in this file;
# a network call anywhere above would already have raised. This test only documents
# that expectation explicitly for a full `extract()` call driven off a monkeypatched
# `_run_docling` (never touching a real DocumentConverter).
# ---------------------------------------------------------------------------------------


def test_extract_with_stubbed_docling_makes_no_network_call(tmp_path: Path) -> None:
    m = _mod()
    path = m.DoclingExtractionPath(artifacts_path=tmp_path)
    path._verify_artifacts = lambda: dict(m.REQUIRED_ARTIFACT_DIGESTS)  # type: ignore[method-assign]

    cell = FakeCell(text="x", orig="literal text", bbox=(0.0, 0.0, 10.0, 10.0))
    page = _fake_page(1, [cell], clusters=[])
    fake_conv_res = _fake_conv_res([page])
    path._run_docling = lambda pdf_path, page_range: fake_conv_res  # type: ignore[method-assign]

    source = SimpleNamespace(path="doc.pdf", page_count=1)
    candidate = path.extract(source, envelope=_envelope())
    assert candidate.status == "ok"
    assert candidate.segments[0].text == "literal text"
    # if this test reached here without the autouse socket guard raising, no non-loopback
    # connection was attempted anywhere in the call chain above.
