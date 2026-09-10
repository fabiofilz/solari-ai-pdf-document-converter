"""T073 [US1] — failing-first tests for ``SemanticDocument`` orchestration.

GREEN owner: **T073** (``src/solari_converter/model/semantic.py`` +
``src/solari_converter/transform/build_semantic.py``).

Frozen post-T070/S2-remediation Stage-3 orchestration order:

    tables = build_tables(ced)                                        # table ownership
    non_table = reflow(ced, excluded_segment_ids=tables.consumed_segment_ids)
    artifacts = remove_artifacts(ced, non_table)                       # T071
    structure = infer_structure(ced, kept_reflow)                      # T068
    lists = reconstruct_lists(ced, kept_reflow)                        # T069
    # assemble table + non-table blocks in accepted-source order

The non-negotiable invariant this module proves: every id in
``set(ced.accepted_reading_order)`` is accounted for **exactly once** across retained
semantic content, collapsed table-header lineage, or explicit non-ambiguous artifact
removal — with table-owned, non-table-retained, and removed id sets pairwise disjoint.
"""

from __future__ import annotations

import solari_converter.transform.tables as tables

from ._semantic_fixtures import Seg, ced


def _build_semantic():
    import solari_converter.transform.build_semantic as build_semantic

    return build_semantic


def _cell(sid, text, x0, top, *, page=1, w=80.0, h=12.0, hint=True):
    return Seg(
        sid, text, (x0, top, x0 + w, top + h), page=page,
        hints=[("table_cell", None, "pdfplumber")] if hint else [],
    )


def _table_owned_ids(doc):
    tr = tables.build_tables(doc)
    return tr.consumed_segment_ids


# --- orchestration order: table ownership before non-table reflow --------------------


def test_table_ownership_is_determined_before_non_table_reflow():
    bs = _build_semantic()
    # a hint-less table-absorbed cell that would otherwise be swept into a prose unit
    doc = ced([
        Seg("p", "Prose line above the table", (72, 84, 300, 96)),
        _cell("h0", "Item", 72, 100, hint=False),
        _cell("h1", "Qty", 162, 100),
        _cell("c0", "Widget", 72, 114), _cell("c1", "3", 162, 114),
        _cell("d0", "Gadget", 72, 128), _cell("d1", "1", 162, 128),
        Seg("q", "Prose line below", (72, 146, 300, 158)),
    ])
    doc_sem = bs.build_semantic(doc)
    table_block = next(b for b in doc_sem.blocks if b.kind == "table")
    non_table_ids = {
        sid for b in doc_sem.blocks if b.kind != "table" for sid in b.provenance
    }
    assert "h0" not in non_table_ids  # never leaks into a paragraph/heading/list block
    assert "h0" in table_block.provenance
    assert "p" in non_table_ids and "q" in non_table_ids


# --- no duplicate ownership / no silent loss ------------------------------------------


def _full_fixture():
    """table + heading + paragraph + list + a removable running header/footer."""
    return ced([
        Seg("h1", "ACME CORP — CONFIDENTIAL", (72, 30, 452, 42), page=1),  # header (removed)
        Seg("title", "Overview", (72, 60, 200, 74), page=1,
            hints=[("heading", 1, "docling")]),
        _cell("th0", "Item", 72, 100), _cell("th1", "Qty", 162, 100),
        _cell("tc0", "Widget", 72, 114), _cell("tc1", "3", 162, 114),
        Seg("intro", "Below is the applicable clause.", (72, 140, 452, 154), page=1),
        Seg("li1", "- First point.", (72, 168, 452, 182), page=1),
        Seg("li2", "- Second point.", (72, 186, 452, 200), page=1),
        Seg("f1", "Page 1", (250, 760, 340, 772), page=1),  # footer (removed)
        # further pages' identical running header — R2 requires at least 3 qualifying
        # occurrences before generic repetition-based furniture removal is authorised
        # (2 contiguous occurrences are ambiguous, kept).
        Seg("h2", "ACME CORP — CONFIDENTIAL", (72, 30, 452, 42), page=2),
        Seg("body2", "Continuation body content on page two.", (72, 100, 452, 130), page=2),
        Seg("h3", "ACME CORP — CONFIDENTIAL", (72, 30, 452, 42), page=3),
        Seg("body3", "Continuation body content on page three.", (72, 100, 452, 130), page=3),
    ])


def test_no_table_and_non_table_duplicate_ownership():
    bs = _build_semantic()
    doc = _full_fixture()
    doc_sem = bs.build_semantic(doc)
    table_ids = {
        sid for b in doc_sem.blocks if b.kind == "table" for sid in b.provenance
    }
    non_table_ids = {
        sid for b in doc_sem.blocks if b.kind != "table" for sid in b.provenance
    }
    assert table_ids & non_table_ids == set()


def test_final_source_coverage_equation():
    bs = _build_semantic()
    doc = _full_fixture()
    doc_sem = bs.build_semantic(doc)

    all_block_ids = {sid for b in doc_sem.blocks for sid in b.provenance}
    collapsed_ids = doc_sem.collapsed_segment_ids
    removed_ids = doc_sem.removed_segment_ids
    # provenance on a table block already includes collapsed ids (T070 lineage) — the
    # accounting equation counts each id exactly once, so subtract collapsed out of the
    # "retained content" side before the union.
    retained_ids = all_block_ids - collapsed_ids

    accepted = set(doc.accepted_reading_order)
    assert retained_ids | collapsed_ids | removed_ids == accepted
    assert retained_ids.isdisjoint(collapsed_ids)
    assert retained_ids.isdisjoint(removed_ids)
    assert collapsed_ids.isdisjoint(removed_ids)
    # no id silently vanished, none duplicated across the three buckets, none invented
    assert len(retained_ids) + len(collapsed_ids) + len(removed_ids) == len(accepted)


def test_artifact_removed_ids_never_appear_in_any_block():
    bs = _build_semantic()
    doc = _full_fixture()
    doc_sem = bs.build_semantic(doc)
    assert "h1" in doc_sem.removed_segment_ids
    assert "f1" in doc_sem.removed_segment_ids
    all_block_ids = {sid for b in doc_sem.blocks for sid in b.provenance}
    assert "h1" not in all_block_ids
    assert "f1" not in all_block_ids


def test_table_owned_ids_are_disjoint_from_non_table_and_removed():
    bs = _build_semantic()
    doc = _full_fixture()
    doc_sem = bs.build_semantic(doc)
    table_owned = doc_sem.table_owned_segment_ids
    non_table_retained = {
        sid for b in doc_sem.blocks if b.kind != "table" for sid in b.provenance
    }
    assert table_owned.isdisjoint(non_table_retained)
    assert table_owned.isdisjoint(doc_sem.removed_segment_ids)


# --- collapsed header + wrapped-cell multi-id accounting ------------------------------


def _stitched_fixture():
    def grid(rows, page, top0):
        return [
            _cell(f"p{page}r{r}c{c}", v, 72 + 90 * c, top0 + 14 * r, page=page)
            for r, row in enumerate(rows) for c, v in enumerate(row)
        ]

    return ced(
        [Seg("intro", "Statement follows.", (72, 60, 300, 72), page=1)]
        + grid([["Date", "Amount"], ["2026-01-01", "100.00"]], 1, 100)
        + grid([["Date", "Amount"], ["2026-02-01", "200.00"]], 2, 60)
        + [Seg("outro", "End of statement.", (72, 100, 300, 112), page=2)]
    )


def test_collapsed_header_ids_are_accounted_as_collapsed_not_retained_twice():
    bs = _build_semantic()
    doc = _stitched_fixture()
    doc_sem = bs.build_semantic(doc)
    assert doc_sem.collapsed_segment_ids == {"p2r0c0", "p2r0c1"}
    table_block = next(b for b in doc_sem.blocks if b.kind == "table")
    # collapsed ids are represented via table provenance/lineage, not duplicated into
    # a second block
    other_block_ids = {
        sid for b in doc_sem.blocks if b is not table_block for sid in b.provenance
    }
    assert doc_sem.collapsed_segment_ids.isdisjoint(other_block_ids)


def test_wrapped_cell_multiple_segment_ids_are_all_accounted():
    bs = _build_semantic()
    doc = ced([
        _cell("h0", "Desc", 72, 100), _cell("h1", "Amt", 162, 100),
        _cell("a0", "line one", 72, 114), _cell("a1", "9.99", 162, 114),
        Seg("wrap", "line two", (72, 126, 152, 138),
            hints=[("table_cell", None, "pdfplumber")]),
    ])
    doc_sem = bs.build_semantic(doc)
    table_block = next(b for b in doc_sem.blocks if b.kind == "table")
    assert {"a0", "wrap"} <= set(table_block.provenance)
    accepted = set(doc.accepted_reading_order)
    all_block_ids = {sid for b in doc_sem.blocks for sid in b.provenance}
    assert all_block_ids | doc_sem.collapsed_segment_ids | doc_sem.removed_segment_ids \
        == accepted


# --- source-order merge (not by kind, not by table_id) --------------------------------


def test_blocks_are_ordered_by_accepted_source_position_not_by_kind():
    bs = _build_semantic()
    # table first, heading second, paragraph third — kind-alphabetical ("heading" <
    # "table") would get this backwards if the merge sorted by kind.
    doc = ced([
        _cell("h0", "Item", 72, 100), _cell("h1", "Qty", 162, 100),
        _cell("c0", "Widget", 72, 114), _cell("c1", "3", 162, 114),
        Seg("title", "Notes", (72, 140, 200, 154), hints=[("heading", 1, "docling")]),
        Seg("body", "Ordinary paragraph text follows.", (72, 168, 452, 182)),
    ])
    doc_sem = bs.build_semantic(doc)
    assert [b.kind for b in doc_sem.blocks] == ["table", "heading", "paragraph"]


def test_table_block_identity_is_reused_verbatim_from_t070():
    bs = _build_semantic()
    doc = ced([
        _cell("h0", "Item", 72, 100), _cell("h1", "Qty", 162, 100),
        _cell("c0", "Widget", 72, 114), _cell("c1", "3", 162, 114),
    ])
    tr = tables.build_tables(doc)
    doc_sem = bs.build_semantic(doc)
    table_block = next(b for b in doc_sem.blocks if b.kind == "table")
    assert table_block.block_id == tr.blocks[0].block_id
    assert table_block.table.table_id == tr.blocks[0].table.table_id


# --- FR-021 stitch-placement StructuralReorder -----------------------------------------


def _stitch_with_displaced_furniture_fixture():
    def grid(rows, page, top0):
        return [
            _cell(f"p{page}r{r}c{c}", v, 72 + 90 * c, top0 + 14 * r, page=page)
            for r, row in enumerate(rows) for c, v in enumerate(row)
        ]

    # tail1/tail2 sit geometrically below "note"/"note2" on their own pages (so
    # neither note is its page's bottom-margin extreme) but come AFTER note2 in
    # accepted order — outside the fragment1→fragment2 intervening range, so they
    # never need to satisfy T070's stitch-transparency test themselves.
    return ced([
        *grid([["Date", "Amount"], ["2026-01-01", "100.00"]], 1, 60),
        Seg("note", "Continued below.", (72, 200, 300, 212), page=1),
        *grid([["Date", "Amount"], ["2026-02-01", "200.00"]], 2, 60),
        Seg("note2", "Continued below.", (72, 200, 300, 212), page=2),
        Seg("tail1", "Trailing paragraph on page one.", (72, 400, 452, 412), page=1),
        Seg("tail2", "Trailing paragraph on page two.", (72, 400, 452, 412), page=2),
    ])


def test_fr021_reorder_emitted_when_stitched_table_has_surviving_displaced_furniture():
    bs = _build_semantic()
    doc = _stitch_with_displaced_furniture_fixture()
    doc_sem = bs.build_semantic(doc)

    # "note" must have survived T071 (mid-page, not margin-positioned) as retained prose
    non_table_ids = {
        sid for b in doc_sem.blocks if b.kind != "table" for sid in b.provenance
    }
    assert "note" in non_table_ids
    assert "note" not in doc_sem.removed_segment_ids

    fr021 = [r for r in doc_sem.structural_reorder if r.permitted_by == "FR-021"]
    assert len(fr021) == 1
    entry = fr021[0]
    assert "note" in entry.affected_segment_ids
    assert set(entry.from_order) == set(entry.to_order) == set(entry.affected_segment_ids)
    assert entry.from_order != entry.to_order
    assert entry.reason

    # the table's own retained cells stay contiguous in the final order, "note" after
    final_order = [
        sid for b in doc_sem.blocks for sid in b.provenance
        if sid in entry.affected_segment_ids
    ]
    assert final_order == list(entry.to_order)
    assert final_order.index("note") == len(final_order) - 1


def test_no_fr021_reorder_when_no_furniture_survives_between_fragments():
    bs = _build_semantic()
    doc = _stitched_fixture()  # intro/outro sit OUTSIDE the table's own span, not between
    doc_sem = bs.build_semantic(doc)
    fr021 = [r for r in doc_sem.structural_reorder if r.permitted_by == "FR-021"]
    assert fr021 == []


# --- no LLM / network -------------------------------------------------------------


def test_semantic_modules_import_no_llm_or_network_symbol():
    import ast
    from pathlib import Path

    src_root = Path(__file__).resolve().parents[2] / "src" / "solari_converter"
    for rel in ("model/semantic.py", "transform/build_semantic.py"):
        tree = ast.parse((src_root / rel).read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        blocked = {"llm", "openai", "litellm", "ollama", "httpx", "requests", "urllib"}
        assert not any(
            any(part in blocked for part in n.split(".")) for n in names
        ), (rel, names)
