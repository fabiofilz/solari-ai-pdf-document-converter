"""T066 [US1] — failing-first tests for Stage-3 non-semantic artifact removal.

GREEN owner: **T071** (``src/solari_converter/transform/artifacts.py``) + **T072**
(``src/solari_converter/reports/removal_log.py``) — **NOT** part of Semantic Block S1.
These stay **RED** until T071/T072 land; S1 (T067–T069) must not remove any source
content on the theory that it looks like page furniture (block brief §25).

Frozen references: spec FR-006–FR-011, SC-004, data-model.md ``RemovalLog`` /
``RemovalEntry``.
"""

from __future__ import annotations

from ._semantic_fixtures import Seg, ced


def _artifacts():
    import solari_converter.transform.artifacts as artifacts  # GREEN owner: T071 (post-S1)

    return artifacts


def _reflow(doc):
    import solari_converter.transform.reflow as reflow

    return reflow.reflow(doc)


def _header(sid, page):
    return Seg(sid, "ACME CORP — CONFIDENTIAL", (72, 30, 452, 42), page=page)


def _footer(sid, page, n):
    return Seg(sid, f"Page {n}", (250, 760, 340, 772), page=page)


def test_repeated_running_header_and_footer_and_page_number_are_removed_and_logged():
    a = _artifacts()
    segs = []
    for page in (1, 2, 3):
        segs += [
            _header(f"h{page}", page),
            Seg(f"body{page}", f"Body content of page {page}.", (72, 100, 452, 130), page=page),
            _footer(f"f{page}", page, page),
        ]
    doc = ced(segs)
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert kept == {"body1", "body2", "body3"}
    assert {e.entry_type for e in result.removal_log.entries} >= {"running_header", "page_number"}


def test_a_header_string_that_is_also_body_content_is_kept_and_recorded():
    a = _artifacts()
    doc = ced([
        Seg("h1", "Master Services Agreement", (72, 30, 452, 42), page=1),
        Seg("h2", "Master Services Agreement", (72, 30, 452, 42), page=2),
        Seg("body", "This Master Services Agreement is entered into by the parties.",
            (72, 100, 452, 130), page=1),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert "body" in kept
    assert any(e.ambiguous for e in result.removal_log.entries)


def test_meaningful_vertical_text_is_preserved():
    a = _artifacts()
    doc = ced([
        Seg("v", "SIGNED IN COUNTERPART", (30, 200, 42, 400), page=1),  # tall + narrow
        Seg("body", "Ordinary paragraph.", (72, 100, 452, 130), page=1),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert "v" in kept
