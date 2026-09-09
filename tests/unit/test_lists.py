"""T066 [US1] — failing-first tests for Stage-3 list + legal-clause reconstruction.

GREEN owner: **T069** (``src/solari_converter/transform/lists.py``).

Frozen references: spec FR-016 / FR-018 / FR-019, the S1 block brief §21–§23.

Deterministic, no LLM. List type and nesting are inferred from source evidence only
(markers + indentation + hints); a false list hint is not applied without other
evidence. Article / clause / list identifiers are **source content** — retained
verbatim, never renumbered, normalised, or translated.
"""

from __future__ import annotations

from ._semantic_fixtures import Seg, ced


def _lists():
    import solari_converter.transform.lists as lists  # GREEN owner: T069

    return lists


def _reflow(doc):
    import solari_converter.transform.reflow as reflow  # GREEN owner: T067

    return reflow.reflow(doc)


def _seg(sid, text, top, *, x0=72.0, width=360.0, height=12.0, hints=(), page=1):
    s = Seg(sid, text, (x0, top, x0 + width, top + height), page=page)
    s.hints = list(hints)
    return s


def _run(segs):
    li = _lists()
    doc = ced(segs)
    return li.reconstruct_lists(doc, _reflow(doc))


# --------------------------------------------------------------------------------------


def test_bulleted_list_is_reconstructed():
    res = _run([
        _seg("i1", "- first item", 100),
        _seg("i2", "- second item", 114),
        _seg("i3", "- third item", 128),
    ])
    items = [u for u in res.units if getattr(u, "role", None) == "list_item"]
    assert len(items) == 3
    assert {i.family for i in items} == {"bullet"}
    assert all(i.ordered is False and i.depth == 0 for i in items)


def test_numbered_list_marker_family_and_order():
    res = _run([
        _seg("i1", "1. alpha", 100),
        _seg("i2", "2. bravo", 114),
        _seg("i3", "3. charlie", 128),
    ])
    items = [u for u in res.units if getattr(u, "role", None) == "list_item"]
    assert [i.marker for i in items] == ["1.", "2.", "3."]
    assert all(i.family == "decimal" and i.ordered for i in items)


def test_indentation_drives_nesting_conservatively():
    res = _run([
        _seg("a", "1. top level", 100, x0=72),
        _seg("b", "a. nested under one", 114, x0=100),
        _seg("c", "b. still nested", 128, x0=100),
        _seg("d", "2. back to top", 142, x0=72),
    ])
    items = [u for u in res.units if getattr(u, "role", None) == "list_item"]
    assert [i.depth for i in items] == [0, 1, 1, 0]


def test_ambiguous_nesting_prefers_the_flatter_representation():
    res = _run([
        _seg("a", "1. item one", 100, x0=72),
        _seg("b", "2. item two barely shifted", 114, x0=74),  # 2px — below the step
    ])
    items = [u for u in res.units if getattr(u, "role", None) == "list_item"]
    assert [i.depth for i in items] == [0, 0]


def test_numbered_article_and_clause_identifiers_are_retained_verbatim():
    res = _run([
        _seg("c1", "Article 1 — Scope. This Agreement governs the engagement.", 100),
        _seg("c2", "Cláusula 4ª. O objeto do presente contrato é a prestação.", 130),
        _seg("c3", "IV. Governing law and jurisdiction.", 160),
    ])
    clauses = [u for u in res.units if getattr(u, "role", None) == "clause"]
    ids = [c.identifier for c in clauses]
    assert "Article 1" in ids
    assert "Cláusula 4ª" in ids  # accented ordinal preserved, not normalised to "4"
    assert "IV" in ids            # roman numeral kept in roman form
    for c in clauses:
        assert c.identifier in c.text  # the identifier stays in the literal


def test_a_false_list_hint_without_a_marker_or_indent_is_not_applied():
    res = _run([
        _seg("x", "This is ordinary running prose that one extractor tagged as a "
                  "list item for no defensible reason.", 100,
             hints=[("list_item", None, "docling")]),
    ])
    assert all(getattr(u, "role", None) != "list_item" for u in res.units)
    decs = [d for d in res.hint_decisions if d.kind == "list_item"]
    assert decs and decs[0].applied is False


def test_a_list_hint_with_a_real_marker_is_applied_and_recorded():
    res = _run([
        _seg("i1", "• bullet with a hint", 100, hints=[("list_item", None, "docling")]),
        _seg("i2", "• second bullet", 114, hints=[("list_item", None, "docling")]),
    ])
    items = [u for u in res.units if getattr(u, "role", None) == "list_item"]
    assert len(items) == 2
    assert any(d.applied for d in res.hint_decisions if d.kind == "list_item")


def test_clause_identifier_is_never_renumbered_or_reformatted():
    res = _run([_seg("c", "1.2.3 Sub-obligation of the supplier.", 100)])
    clause = next(u for u in res.units if getattr(u, "role", None) == "clause")
    assert clause.identifier == "1.2.3"  # exact, dots kept, not "1-2-3" or "123"


def test_flattening_list_units_preserves_source_order():
    res = _run([
        _seg("a", "1. one", 100),
        _seg("b", "2. two", 114),
        _seg("c", "closing paragraph", 150),
    ])
    flat = [sid for u in res.units for sid in u.segment_ids]
    assert flat == ["a", "b", "c"]


def test_list_reconstruction_is_deterministic():
    segs = [_seg("i1", "- x", 100), _seg("i2", "- y", 114)]
    a, b = _run(list(segs)), _run(list(segs))
    assert [getattr(u, "role", None) for u in a.units] == [
        getattr(u, "role", None) for u in b.units
    ]


def test_the_whole_stage_three_s1_chain_is_deterministic():
    import solari_converter.transform.lists as lists
    import solari_converter.transform.reflow as reflow
    import solari_converter.transform.structure as structure

    doc = ced([
        _seg("h", "Article 1 — Scope", 100, height=15, hints=[("heading", 1, "docling")]),
        _seg("p1", "The parties agree that this Agreement governs the", 130),
        _seg("p2", "provision of the services described in Schedule A.", 144),
        _seg("l1", "1. first obligation", 175),
        _seg("l2", "2. second obligation", 189),
    ])

    def _pipeline():
        r = reflow.reflow(doc)
        s = structure.infer_structure(doc, r)
        li = lists.reconstruct_lists(doc, r)
        return (
            [(u.segment_ids, u.text, tuple(t.kind for t in u.transforms)) for u in r.units],
            [(u.role, u.level, u.deep) for u in s.units],
            [(u.role, getattr(u, "marker", None), getattr(u, "identifier", None),
              getattr(u, "depth", None)) for u in li.units],
        )

    assert _pipeline() == _pipeline()
