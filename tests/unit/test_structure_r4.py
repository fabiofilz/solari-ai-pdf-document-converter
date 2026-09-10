"""R4 (post-semantic remediation audit of ``70aa0cf``) — contradictory heading
evidence in ``transform/structure.py`` ``infer_structure``.

Conflicting *explicit* heading levels must not be resolved just because one extractor
name sorts first. Only the source's own numbering depth may break the tie; otherwise
no hint is applied and no heading level is invented. Duplicate ``None``-level hints
must not each be recorded as a separate applied semantic decision — one deterministic
decision per source block.
"""

from __future__ import annotations

from ._semantic_fixtures import Seg, ced


def _structure():
    import solari_converter.transform.structure as structure

    return structure


def _reflow(doc):
    import solari_converter.transform.reflow as reflow

    return reflow.reflow(doc)


def _seg(sid, text, top, *, x0=72.0, width=380.0, height=12.0, hints=(), page=1):
    s = Seg(sid, text, (x0, top, x0 + width, top + height), page=page)
    s.hints = list(hints)
    return s


def _run(segs):
    doc = ced(segs)
    return _structure().infer_structure(doc, _reflow(doc))


_L1_L6 = [("heading", 1, "docling"), ("heading", 6, "pdfplumber")]


def test_conflicting_explicit_levels_without_numbering_apply_no_hint():
    res = _run([_seg("h", "Scope and Objectives", 100, height=16, hints=_L1_L6)])
    u = res.units[0]
    assert u.role == "body"          # preserved conservatively
    assert u.level is None           # no heading level invented
    decs = [d for d in res.hint_decisions if d.kind == "heading"]
    assert len(decs) == 2 and all(not d.applied for d in decs)
    assert all("conflicting explicit heading levels" in d.reason for d in decs)


def test_conflict_outcome_is_independent_of_hint_input_order():
    a = _run([_seg("h", "Scope and Objectives", 100, height=16, hints=_L1_L6)])
    b = _run([_seg("h", "Scope and Objectives", 100, height=16,
                   hints=list(reversed(_L1_L6)))])

    def key(r):
        return [(d.hint_ref, d.applied, d.reason) for d in r.hint_decisions]

    assert key(a) == key(b)
    assert [(u.role, u.level) for u in a.units] == [(u.role, u.level) for u in b.units]


def test_numbering_depth_breaks_a_level_conflict_not_the_extractor_name():
    # "1.2 …" → dotted numbering depth 2 → the level-2 hint wins even though its
    # extractor name ("zzz…") sorts last.
    res = _run([_seg("h", "1.2 Governance Model", 100, height=15, hints=[
        ("heading", 5, "aaa_extractor"), ("heading", 2, "zzz_extractor"),
    ])])
    u = res.units[0]
    assert u.role == "heading" and u.level == 2
    applied = [d for d in res.hint_decisions if d.applied]
    assert len(applied) == 1 and applied[0].hint_ref.endswith(":2")


def test_multiple_corroborating_none_level_hints_yield_one_applied_decision():
    res = _run([_seg("h", "Definitions", 100, height=16, hints=[
        ("heading", None, "docling"), ("heading", None, "pdfplumber"),
    ])])
    u = res.units[0]
    assert u.role == "heading"
    heading_decs = [d for d in res.hint_decisions if d.kind == "heading"]
    assert len(heading_decs) == 2
    assert sum(1 for d in heading_decs if d.applied) == 1


def test_result_is_stable_across_repeated_and_reversed_runs():
    segs = [
        _seg("h", "1.2 Governance Model", 100, height=15, hints=[
            ("heading", 5, "aaa_extractor"), ("heading", 2, "zzz_extractor")]),
        _seg("b", "Following paragraph text of the section.", 130),
    ]
    r1 = _run(list(segs))
    r2 = _run(list(segs))
    r3 = _run(list(reversed(segs)))
    for r in (r2, r3):
        ha = next(u for u in r1.units if u.segment_ids == ("h",))
        hb = next(u for u in r.units if u.segment_ids == ("h",))
        assert (ha.role, ha.level, ha.numbering) == (hb.role, hb.level, hb.numbering)
        assert [d.hint_decisions for d in (ha,)] == [d.hint_decisions for d in (hb,)]


def test_agreeing_explicit_levels_are_not_treated_as_a_conflict():
    res = _run([_seg("h", "Scope and Objectives", 100, height=16, hints=[
        ("heading", 2, "docling"), ("heading", 2, "pdfplumber"),
    ])])
    u = res.units[0]
    assert u.role == "heading" and u.level == 2
    assert sum(1 for d in res.hint_decisions if d.applied) == 1
