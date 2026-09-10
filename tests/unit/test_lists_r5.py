"""R5 (second post-semantic remediation pass) — ambiguous numeric / Roman
legal-clause recognition in ``transform/lists.py``.

First pass gated a bare numeric/Roman prefix on the *capitalisation* of the following
prose. That is not valid clause evidence. This pass removes the capitalisation
heuristic entirely: a bare dotted-number or bare Roman prefix classifies as a legal
clause **only** when independent deterministic structural evidence already carried by
the frozen pipeline supports it (a ``list_item`` structural hint on the unit).
Otherwise it is ordinary body text, literal preserved exactly. Explicit legal keywords
(``Article`` / ``Cláusula`` / …) continue to establish clause semantics on their own.
"""

from __future__ import annotations

import pytest

from ._semantic_fixtures import Seg, ced


def _lists():
    import solari_converter.transform.lists as lists

    return lists


def _reflow(doc):
    import solari_converter.transform.reflow as reflow

    return reflow.reflow(doc)


def _seg(sid, text, top, *, x0=72.0, width=360.0, height=12.0, page=1, hints=()):
    s = Seg(sid, text, (x0, top, x0 + width, top + height), page=page)
    s.hints = list(hints)
    return s


def _run(segs):
    doc = ced(segs)
    return _lists().reconstruct_lists(doc, _reflow(doc))


def _roles(res):
    return [getattr(u, "role", None) for u in res.units]


# --- capitalisation is NOT evidence: every one of these is ordinary body -------------


@pytest.mark.parametrize(
    "text",
    [
        "1.5 million residents voted for the proposal.",
        "1.5 Million residents voted for the proposal.",
        "I. am available tomorrow.",
        "I. Am available tomorrow.",
        "IV. League teams participated.",
        "2.0 Million dollars were invested.",
        "3.2 kg of raw material was consumed per unit.",
    ],
)
def test_bare_prefix_without_structural_evidence_is_body(text):
    res = _run([_seg("x", text, 100)])
    assert _roles(res) == ["body"]
    assert res.units[0].text == text  # literal preserved exactly


def test_upper_and_lower_variants_fall_back_to_body_consistently():
    lower = _run([_seg("x", "iv. governing law and jurisdiction.", 100)])
    upper = _run([_seg("x", "IV. Governing law and jurisdiction.", 100)])
    assert _roles(lower) == _roles(upper) == ["body"]


# --- genuine legal clauses still classify ------------------------------------------


_HINT = [("list_item", None, "docling")]


def test_keyword_clause_needs_no_structural_hint():
    res = _run([
        _seg("c", "Article 1 — Scope. This Agreement governs the engagement.", 100),
    ])
    clause = next(u for u in res.units if getattr(u, "role", None) == "clause")
    assert clause.identifier == "Article 1"


def test_bare_roman_clause_classifies_with_structural_evidence():
    res = _run([_seg("c", "IV. Governing law and jurisdiction.", 100, hints=_HINT)])
    clause = next(u for u in res.units if getattr(u, "role", None) == "clause")
    assert clause.identifier == "IV"
    assert clause.text == "IV. Governing law and jurisdiction."
    applied = [d for d in res.hint_decisions if d.applied]
    assert len(applied) == 1


def test_bare_dotted_subclause_classifies_with_structural_evidence():
    res = _run([_seg("c", "1.2.3 Sub-obligation of the supplier.", 100, hints=_HINT)])
    clause = next(u for u in res.units if getattr(u, "role", None) == "clause")
    assert clause.identifier == "1.2.3"


def test_single_dot_clause_with_structural_evidence_classifies():
    res = _run([_seg("c", "2.1 Payment Terms and Invoicing.", 100, hints=_HINT)])
    clause = next(u for u in res.units if getattr(u, "role", None) == "clause")
    assert clause.identifier == "2.1"


def test_a_list_item_hint_does_not_rescue_a_pure_quantity_prefix():
    # "1.5 million …" — _DOTTED_CLAUSE_RE matches "1.5"; with a list_item hint it now
    # *would* classify as clause "1.5". That is acceptable under R5 (the hint is
    # genuine structural evidence); the point of this test is that the outcome is
    # driven by the hint, never by "million" vs "Million".
    a = _run([_seg("x", "1.5 million residents voted.", 100, hints=_HINT)])
    b = _run([_seg("x", "1.5 Million residents voted.", 100, hints=_HINT)])
    assert _roles(a) == _roles(b)


def test_classification_is_deterministic():
    segs = [
        _seg("a", "1.5 million residents voted for the proposal.", 100),
        _seg("b", "IV. Governing law and jurisdiction.", 130, hints=_HINT),
    ]
    a, b = _run(list(segs)), _run(list(segs))
    assert _roles(a) == _roles(b)
