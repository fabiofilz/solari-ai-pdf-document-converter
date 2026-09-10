"""R5 (post-semantic remediation audit of ``70aa0cf``) — ambiguous numeric / Roman
legal-clause recognition in ``transform/lists.py``.

``1.5 million residents voted for the proposal.`` was treated as clause ``1.5``;
``I. am available tomorrow.`` as Roman clause ``I``. Numeric/Roman-looking prefixes
alone must not create legal-clause semantics when ordinary prose is equally plausible;
tied/ambiguous ⇒ ordinary body content, literal text preserved exactly.
"""

from __future__ import annotations

from ._semantic_fixtures import Seg, ced


def _lists():
    import solari_converter.transform.lists as lists

    return lists


def _reflow(doc):
    import solari_converter.transform.reflow as reflow

    return reflow.reflow(doc)


def _seg(sid, text, top, *, x0=72.0, width=360.0, height=12.0, page=1):
    return Seg(sid, text, (x0, top, x0 + width, top + height), page=page)


def _run(segs):
    doc = ced(segs)
    return _lists().reconstruct_lists(doc, _reflow(doc))


def _roles(res):
    return [getattr(u, "role", None) for u in res.units]


# --- reproduced false positives => body, literal preserved ---------------------------


def test_decimal_quantity_prose_is_not_a_clause():
    res = _run([_seg("x", "1.5 million residents voted for the proposal.", 100)])
    assert _roles(res) == ["body"]
    assert res.units[0].text == "1.5 million residents voted for the proposal."


def test_roman_pronoun_prose_is_not_a_clause():
    res = _run([_seg("x", "I. am available tomorrow.", 100)])
    assert _roles(res) == ["body"]
    assert res.units[0].text == "I. am available tomorrow."


def test_another_decimal_quantity_prose_is_not_a_clause():
    res = _run([_seg("x", "3.2 kg of raw material was consumed per unit.", 100)])
    assert _roles(res) == ["body"]


# --- genuine legal clauses still classify ------------------------------------------


def test_genuine_roman_clause_still_classifies():
    res = _run([_seg("c", "IV. Governing law and jurisdiction.", 100)])
    clause = next(u for u in res.units if getattr(u, "role", None) == "clause")
    assert clause.identifier == "IV"
    assert clause.text == "IV. Governing law and jurisdiction."


def test_genuine_dotted_subclause_still_classifies():
    res = _run([_seg("c", "1.2.3 Sub-obligation of the supplier.", 100)])
    clause = next(u for u in res.units if getattr(u, "role", None) == "clause")
    assert clause.identifier == "1.2.3"


def test_genuine_keyword_clause_still_classifies():
    res = _run([
        _seg("c", "Article 1 — Scope. This Agreement governs the engagement.", 100),
    ])
    clause = next(u for u in res.units if getattr(u, "role", None) == "clause")
    assert clause.identifier == "Article 1"


def test_single_dot_clause_with_a_titled_body_still_classifies():
    res = _run([_seg("c", "2.1 Payment Terms and Invoicing.", 100)])
    clause = next(u for u in res.units if getattr(u, "role", None) == "clause")
    assert clause.identifier == "2.1"


def test_classification_is_deterministic():
    segs = [
        _seg("a", "1.5 million residents voted for the proposal.", 100),
        _seg("b", "IV. Governing law and jurisdiction.", 130),
    ]
    a, b = _run(list(segs)), _run(list(segs))
    assert _roles(a) == _roles(b)
