"""T066 [US1] — failing-first tests for Stage-3 structural / heading inference.

GREEN owner: **T068** (``src/solari_converter/transform/structure.py``).

Frozen references: spec FR-016 / FR-017 / FR-017a, FR-064 / SC-026 (structural-hint
audit — every carried hint is recorded applied / not-applied), the S1 block brief §17–§20.

Deterministic, no LLM. A carried Docling/extraction heading hint is **evidence**, not
truth: it is applied only with at least one corroborating deterministic signal, and
every hint decision is recorded either way. No fabricated hierarchy; levels deeper than
6 are flagged (not rendered) for the later ``[L{n}]`` treatment.
"""

from __future__ import annotations

from ._semantic_fixtures import Seg, ced


def _structure():
    import solari_converter.transform.structure as structure  # GREEN owner: T068

    return structure


def _reflow(doc):
    import solari_converter.transform.reflow as reflow  # GREEN owner: T067

    return reflow.reflow(doc)


def _seg(sid, text, top, *, x0=72.0, width=380.0, height=12.0, hints=(), page=1):
    s = Seg(sid, text, (x0, top, x0 + width, top + height), page=page)
    s.hints = list(hints)
    return s


def _run(segs):
    st = _structure()
    doc = ced(segs)
    return st.infer_structure(doc, _reflow(doc))


# --------------------------------------------------------------------------------------


def test_a_heading_hint_with_a_corroborating_signal_is_applied():
    res = _run([
        _seg("h", "Scope of the Agreement", 100,
             hints=[("heading", 1, "docling")], height=16),
        _seg("b", "The parties agree as follows in this section.", 130),
    ])
    h = res.units[0]
    assert h.role == "heading" and h.level == 1
    assert res.units[1].role == "body"
    d = [x for x in res.hint_decisions if x.applied]
    assert d and d[0].kind == "heading"


def test_a_bare_heading_hint_with_no_other_signal_is_not_applied_but_is_recorded():
    res = _run([
        # long, sentence-like, terminal punctuation -> not heading-shaped
        _seg("x", "This paragraph was mislabelled as a heading by one extractor "
                  "even though it is plainly a full sentence of running body text.", 100,
             hints=[("heading", 2, "docling")]),
    ])
    assert res.units[0].role == "body"
    decs = [x for x in res.hint_decisions if x.kind == "heading"]
    assert len(decs) == 1 and decs[0].applied is False and decs[0].reason


def test_no_headings_document_stays_flat():
    res = _run([
        _seg("a", "First plain paragraph of the document body.", 100),
        _seg("b", "Second plain paragraph, also just running text.", 140),
    ])
    assert {u.role for u in res.units} == {"body"}
    assert all(u.level is None for u in res.units)


def test_contradictory_hints_for_one_segment_are_both_recorded_one_applied_at_most():
    res = _run([
        _seg("h", "Article 1 — Definitions", 100, height=15, hints=[
            ("heading", 1, "docling"),
            ("heading", 3, "pdfplumber"),
        ]),
    ])
    heading_decs = [x for x in res.hint_decisions if x.kind == "heading"]
    assert len(heading_decs) == 2
    assert sum(1 for x in heading_decs if x.applied) <= 1


def test_numbering_depth_drives_the_inferred_level():
    res = _run([
        _seg("a", "1 Introduction", 100, height=15, hints=[("heading", None, "docling")]),
        _seg("b", "1.2 Background and Prior Work", 130, height=14,
             hints=[("heading", None, "docling")]),
        _seg("c", "1.2.3 A Narrow Sub-topic", 160, height=13,
             hints=[("heading", None, "docling")]),
    ])
    levels = [u.level for u in res.units]
    assert levels == [1, 2, 3]
    assert [u.numbering for u in res.units] == ["1", "1.2", "1.2.3"]


def test_levels_deeper_than_six_are_flagged_not_dropped_and_not_rendered():
    hints = [("heading", None, "docling")]
    res = _run([
        _seg(f"h{n}", f"{'.'.join(['1'] * n)} Deep heading {n}", 100 + 30 * n,
             height=13, hints=hints)
        for n in range(1, 9)
    ])
    deep = [u for u in res.units if u.level and u.level > 6]
    assert [u.level for u in deep] == [7, 8]
    assert all(u.deep for u in deep)
    # T068 produces semantic structure, not Markdown — no '#' and no '[L{n}]' text yet
    for u in res.units:
        assert not u.text.startswith("#")
        assert "[L7]" not in u.text and "[L8]" not in u.text


def test_structure_preserves_contributing_segment_ids_and_source_order():
    res = _run([
        _seg("h", "Overview", 100, height=16, hints=[("heading", 1, "docling")]),
        _seg("p1", "A body sentence that then", 130),
        _seg("p2", "wraps onto a second line.", 144),
    ])
    flat = [sid for u in res.units for sid in u.segment_ids]
    assert flat == ["h", "p1", "p2"]


def test_structure_inference_is_deterministic():
    segs = [
        _seg("h", "Definitions", 100, height=16, hints=[("heading", 1, "docling")]),
        _seg("b", "The following terms have the meanings set out below.", 130),
    ]
    a, b = _run(list(segs)), _run(list(segs))
    assert [(u.role, u.level) for u in a.units] == [(u.role, u.level) for u in b.units]
