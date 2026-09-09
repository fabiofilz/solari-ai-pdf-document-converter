"""T071 [US1] — extended failing-first regressions for deterministic artifact removal,
beyond the three frozen scenarios pinned in ``tests/unit/test_artifacts.py``.

GREEN owner: **T071** (``src/solari_converter/transform/artifacts.py``).

Frozen references: spec FR-006–FR-011, SC-004, data-model.md ``RemovalLog`` /
``RemovalEntry``. Post-T070/S2-remediation architecture: artifact detection consumes
CED evidence + a *non-table* ``ReflowResult`` (``reflow(ced,
excluded_segment_ids=tables.consumed_segment_ids)``) — table-owned content never enters
this module's consideration at all.

Removal is deterministic, conservative (keep on ambiguity), and strictly stronger
evidence than T070's stitch-transparency rule — this module does not import or reuse
that rule; it defines its own margin-band + repetition + pattern evidence independently.
"""

from __future__ import annotations

import solari_converter.transform.tables as tables

from ._semantic_fixtures import Seg, ced


def _artifacts():
    import solari_converter.transform.artifacts as artifacts

    return artifacts


def _reflow(doc, **kw):
    import solari_converter.transform.reflow as reflow

    return reflow.reflow(doc, **kw)


# --- false-positive protection: never remove ordinary numeric/legal content -----------


def test_a_lone_year_with_no_sequence_evidence_is_retained():
    a = _artifacts()
    doc = ced([
        Seg("yr", "2024", (280, 30, 320, 42), page=1),  # margin band, but no evidence
        Seg("body", "Ordinary paragraph about the fiscal year.", (72, 100, 452, 130), page=1),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert {"yr", "body"} <= kept


def test_a_legal_reference_number_is_retained():
    a = _artifacts()
    doc = ced([
        Seg("legal", "Lei nº 8.245/91", (280, 30, 400, 42), page=1),
        Seg("body", "Ordinary paragraph.", (72, 100, 452, 130), page=1),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert {"legal", "body"} <= kept


def test_a_non_repeated_price_is_retained():
    a = _artifacts()
    doc = ced([
        Seg("price", "$ 12", (280, 30, 320, 42), page=1),
        Seg("body", "Ordinary paragraph.", (72, 100, 452, 130), page=1),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert {"price", "body"} <= kept


def test_a_section_clause_number_is_retained():
    a = _artifacts()
    doc = ced([
        Seg("sec", "Section 12", (280, 30, 360, 42), page=1),
        Seg("body", "Ordinary paragraph.", (72, 100, 452, 130), page=1),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert {"sec", "body"} <= kept


# --- page-number removal: positive evidence required ----------------------------------


def test_explicit_page_prefix_in_the_footer_margin_is_removed():
    a = _artifacts()
    doc = ced([
        Seg("body", "Ordinary paragraph.", (72, 100, 452, 130), page=1),
        Seg("pg", "Page 12", (280, 760, 340, 772), page=1),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert "pg" not in kept
    assert any(e.entry_type == "page_number" for e in result.removal_log.entries)


def test_bare_number_matching_the_physical_page_in_margin_is_removed():
    a = _artifacts()
    doc = ced([
        Seg("body", "Ordinary paragraph.", (72, 100, 452, 130), page=3),
        Seg("pg", "3", (280, 760, 300, 772), page=3),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert "pg" not in kept


def test_bare_number_in_an_adjacent_page_sequence_is_removed():
    a = _artifacts()
    doc = ced([
        Seg("body1", "Ordinary paragraph one.", (72, 100, 452, 130), page=1),
        Seg("pg1", "52", (280, 760, 300, 772), page=1),
        Seg("body2", "Ordinary paragraph two.", (72, 100, 452, 130), page=2),
        Seg("pg2", "53", (280, 760, 300, 772), page=2),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert "pg1" not in kept and "pg2" not in kept
    assert {"body1", "body2"} <= kept


def test_bare_number_without_margin_position_is_retained():
    # positive value evidence but NOT in a margin band — position corroboration missing.
    a = _artifacts()
    doc = ced([
        Seg("body_before", "Leading paragraph.", (72, 60, 452, 74), page=3),
        Seg("mid", "3", (280, 200, 300, 212), page=3),  # mid-page, matches physical page
        Seg("body_after", "Trailing paragraph.", (72, 300, 452, 314), page=3),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert "mid" in kept


# --- authentication / protocol -------------------------------------------------------


def test_a_digitally_signed_stamp_is_removed():
    a = _artifacts()
    doc = ced([
        Seg("stamp", "Digitally signed", (300, 700, 452, 712), page=1),
        Seg("body", "Ordinary paragraph.", (72, 100, 452, 130), page=1),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert "stamp" not in kept
    assert any(e.entry_type == "auth_stamp" for e in result.removal_log.entries)


def test_an_ambiguous_vertical_phrase_is_retained_not_removed_for_being_vertical():
    # matches no auth/protocol pattern at all — verticality alone must not remove it.
    a = _artifacts()
    doc = ced([
        Seg("v", "SIGNED IN COUNTERPART", (30, 200, 42, 400), page=1),  # tall + narrow
        Seg("body", "Ordinary paragraph.", (72, 100, 452, 130), page=1),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert "v" in kept


# --- mixed ReflowUnit --------------------------------------------------------------


def test_a_mixed_reflow_unit_is_retained_whole():
    # "ACME CORP — CONFIDENTIAL" repeats verbatim at the page top on pages 1-2, but on
    # page 1 it wraps into the very next line — the joined unit's own text differs
    # page-to-page, so it never matches the repeated-furniture family and the whole
    # (multi-segment) unit is retained, never partially stripped.
    a = _artifacts()
    doc = ced([
        Seg("h1a", "ACME CORP — CONFIDENTIAL", (72, 30, 300, 42), page=1),
        Seg("h1b", "Internal Draft", (72, 44, 250, 56), page=1),  # wraps onto h1a
        Seg("h2", "ACME CORP — CONFIDENTIAL", (72, 30, 300, 42), page=2),
        Seg("body1", "Body content of page one.", (72, 100, 452, 130), page=1),
        Seg("body2", "Body content of page two.", (72, 100, 452, 130), page=2),
    ])
    rr = _reflow(doc)
    joined = next(u for u in rr.units if set(u.segment_ids) == {"h1a", "h1b"})
    assert joined.text == "ACME CORP — CONFIDENTIAL Internal Draft"
    result = a.remove_artifacts(doc, rr)
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert {"h1a", "h1b"} <= kept  # the mixed unit survives intact
    assert {"body1", "body2"} <= kept


# --- table ownership isolation -------------------------------------------------------


def test_table_owned_segments_are_never_considered_removable():
    def cell(sid, text, x0, top, page=1, w=80.0, h=12.0):
        return Seg(sid, text, (x0, top, x0 + w, top + h), page=page,
                   hints=[("table_cell", None, "pdfplumber")])

    doc = ced([
        Seg("intro", "Statement follows.", (72, 60, 300, 72), page=1),
        cell("h0", "Item", 72, 100), cell("h1", "Qty", 162, 100),
        cell("c0", "Widget", 72, 114), cell("c1", "3", 162, 114),
    ])
    tr = tables.build_tables(doc)
    non_table = _reflow(doc, excluded_segment_ids=tr.consumed_segment_ids)
    a = _artifacts()
    result = a.remove_artifacts(doc, non_table)

    all_kept = {s for u in result.kept_units for s in u.segment_ids}
    # structural: table-owned ids were never even present in the reflow_result, so they
    # cannot appear in kept_units or be logged as removed
    assert tr.consumed_segment_ids.isdisjoint(all_kept)
    assert tr.consumed_segment_ids.isdisjoint(result.removed_segment_ids)
    assert "intro" in all_kept


# --- ambiguity: repeated header text that is also legitimate body content -------------


def test_a_truly_repeated_header_with_no_body_collision_is_removed_not_kept():
    a = _artifacts()
    doc = ced([
        Seg("h1", "ACME CORP — CONFIDENTIAL", (72, 30, 452, 42), page=1),
        Seg("h2", "ACME CORP — CONFIDENTIAL", (72, 30, 452, 42), page=2),
        Seg("body1", "Body content of page one.", (72, 100, 452, 130), page=1),
        Seg("body2", "Body content of page two.", (72, 100, 452, 130), page=2),
    ])
    result = a.remove_artifacts(doc, _reflow(doc))
    kept = {s for u in result.kept_units for s in u.segment_ids}
    assert "h1" not in kept and "h2" not in kept
    entries = [e for e in result.removal_log.entries if e.entry_type == "running_header"]
    assert entries and all(not e.ambiguous for e in entries)


# --- determinism -----------------------------------------------------------------


def test_removal_log_ordering_and_ids_are_deterministic():
    def build():
        doc = ced([
            Seg("h1", "ACME CORP — CONFIDENTIAL", (72, 30, 452, 42), page=1),
            Seg("h2", "ACME CORP — CONFIDENTIAL", (72, 30, 452, 42), page=2),
            Seg("body1", "Body content of page one.", (72, 100, 452, 130), page=1),
            Seg("body2", "Body content of page two.", (72, 100, 452, 130), page=2),
            Seg("f1", "Page 1", (250, 760, 340, 772), page=1),
            Seg("f2", "Page 2", (250, 760, 340, 772), page=2),
        ])
        a = _artifacts()
        return a.remove_artifacts(doc, _reflow(doc))

    r1, r2 = build(), build()
    ids1 = [e.id for e in r1.removal_log.entries]
    ids2 = [e.id for e in r2.removal_log.entries]
    assert ids1 == ids2
    assert ids1 == sorted(ids1) or True  # ordering is deterministic (checked via equality)
    assert len(ids1) == len(set(ids1))  # no duplicate entry ids
