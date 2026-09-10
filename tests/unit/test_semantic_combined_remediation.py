"""Combined interaction regression for the second narrow semantic remediation pass.

One ``build_semantic`` run that exercises, together:

* a same-anchor table literal collision → fragment rejected, region falls back to prose;
* a normal 2x2 table elsewhere → still built;
* a stitched multi-page table whose repeated continuation header collapses, with the
  explicit singular ``collapsed_into`` edge;
* authentication/hash-like text → retained, logged ambiguous (R3);
* ordinary wrapped prose → reflowed;
* a heading (carried hint, corroborated);
* legal-looking bare-number body text → stays body (R5).

Asserted: the accepted-ID partition is exact; no silent literal loss; no table /
non-table duplicate ownership; no unsafe artifact removal; the result is deterministic;
collapsed edges are singular and traceable.
"""

from __future__ import annotations

import solari_converter.transform.build_semantic as build_semantic

from ._semantic_fixtures import Seg, ced

_HASH = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


def _cell(sid, text, x0, top, *, page, w=80.0):
    return Seg(sid, text, (x0, top, x0 + w, top + 12), page=page,
              hints=[("table_cell", None, "pdfplumber")])


def _fixture():
    segs = [
        # -- page 1: heading + wrapped prose + legal-looking body -------------------
        Seg("title", "Quarterly Report", (72, 40, 260, 56), page=1,
            hints=[("heading", 1, "docling")]),
        Seg("pr0", "This paragraph starts on one line and", (72, 66, 452, 78), page=1),
        Seg("pr1", "continues onto the following line.", (72, 80, 452, 92), page=1),
        Seg("legal", "1.5 million shares were issued during the period.",
            (72, 104, 452, 116), page=1),
        # -- page 1: a normal 2x2 table -------------------------------------------
        _cell("n_h0", "Item", 72, 140, page=1), _cell("n_h1", "Qty", 162, 140, page=1),
        _cell("n_a0", "Widget", 72, 154, page=1), _cell("n_a1", "5", 162, 154, page=1),
        # -- page 1: first fragment of the stitched table ------------------------
        _cell("s1_h0", "Date", 72, 210, page=1), _cell("s1_h1", "Amount", 162, 210, page=1),
        _cell("s1_a0", "2026-01-01", 72, 224, page=1),
        _cell("s1_a1", "100.00", 162, 224, page=1),
        # -- page 2: continuation fragment (repeated header collapses) ----------
        _cell("s2_h0", "Date", 72, 40, page=2), _cell("s2_h1", "Amount", 162, 40, page=2),
        _cell("s2_a0", "2026-02-01", 72, 54, page=2),
        _cell("s2_a1", "200.00", 162, 54, page=2),
        # -- page 2: same-anchor collision region (two distinct literals) -------
        _cell("z_h0", "C1", 72, 120, page=2), _cell("z_h1", "C2", 162, 120, page=2),
        _cell("z_alpha", "Alpha", 72, 134, page=2),
        _cell("z_beta", "Beta", 72, 134, page=2),   # same anchor as z_alpha
        _cell("z_b", "Bval", 162, 134, page=2),
        # -- page 2: authentication / hash-like text ---------------------------
        Seg("auth", "Digitally signed", (300, 200, 452, 212), page=2),
        Seg("hash", _HASH, (300, 220, 452, 232), page=2),
    ]
    return ced(segs)


def test_combined_remediation_interaction_holds():
    doc = _fixture()
    sem = build_semantic.build_semantic(doc)  # raises on any invariant breach

    kinds = [b.kind for b in sem.blocks]
    assert kinds.count("table") == 2                       # normal + stitched; NOT the collision
    assert "heading" in kinds

    # -- collision region fell back to prose: every literal delivered, no table --
    rendered = " ".join(
        t for b in sem.blocks for t, _p in build_semantic._carrier_units(b)
    )
    for lit in ("C1", "C2", "Alpha", "Beta", "Bval"):
        assert lit in rendered
    collision_ids = {"z_h0", "z_h1", "z_alpha", "z_beta", "z_b"}
    table_ids = {sid for b in sem.blocks if b.kind == "table" for sid in b.provenance}
    assert collision_ids.isdisjoint(table_ids)

    # -- authentication / hash-like text retained, never removed ----------------
    assert "auth" not in sem.removed_segment_ids
    assert "hash" not in sem.removed_segment_ids
    assert {"auth", "hash"} <= {sid for b in sem.blocks for sid in b.provenance}

    # -- legal-looking bare number stays body ----------------------------------
    legal_block = next(
        b for b in sem.blocks
        if b.kind in {"paragraph", "clause"} and "1.5 million" in getattr(b, "text", "")
    )
    assert legal_block.kind == "paragraph"

    # -- wrapped prose reflowed -----------------------------------------------
    assert any(
        b.kind == "paragraph"
        and b.text == "This paragraph starts on one line and continues onto the following line."
        for b in sem.blocks
    )

    # -- collapsed repeated header: singular, traceable edge ------------------
    assert len(sem.collapsed_headers) == 1
    ch = sem.collapsed_headers[0]
    assert set(ch.segment_ids) == {"s2_h0", "s2_h1"}
    edges = dict(ch.collapsed_into)
    assert len(ch.collapsed_into) == len(edges) == 2          # one target per collapsed id
    assert set(edges.values()) <= set(ch.kept_header_segment_ids)
    assert edges == {"s2_h0": "s1_h0", "s2_h1": "s1_h1"}
    assert sem.collapsed_segment_ids == {"s2_h0", "s2_h1"}

    # -- exact accepted-ID partition + zero literal loss ---------------------
    assert build_semantic.accepted_partition_violations(sem, doc) == {}
    assert build_semantic.literal_accounting_violations(sem, doc) == []

    accepted = set(doc.accepted_reading_order)
    retained = {sid for b in sem.blocks for sid in b.provenance} - sem.collapsed_segment_ids
    assert retained | sem.collapsed_segment_ids | sem.removed_segment_ids == accepted
    assert retained.isdisjoint(sem.collapsed_segment_ids)
    assert retained.isdisjoint(sem.removed_segment_ids)

    # -- no table / non-table duplicate ownership --------------------------
    non_table_ids = {
        sid for b in sem.blocks if b.kind != "table" for sid in b.provenance
    }
    assert non_table_ids.isdisjoint(table_ids)


def test_combined_remediation_interaction_is_deterministic():
    a = build_semantic.build_semantic(_fixture())
    b = build_semantic.build_semantic(_fixture())
    assert [x.block_id for x in a.blocks] == [x.block_id for x in b.blocks]
    assert [getattr(x, "text", None) for x in a.blocks] == \
        [getattr(x, "text", None) for x in b.blocks]
    assert a.collapsed_headers == b.collapsed_headers
    assert a.structural_reorder == b.structural_reorder
