"""R2 + R3 (post-semantic remediation audit of ``70aa0cf``) — conservative artifact
removal.

R2: generic repeated-header/footer detection must not gain removal authority merely
because text repeats across a short or discontinuous page selection; heading/caption
semantics weigh against removal; ambiguity ⇒ KEEP (recorded, never silently dropped).

R3: an authentication phrase / hash / barcode SHAPE alone must not delete author
content — an independent, already-available deterministic signal (a page margin band)
is required; a mid-body shape-only match is kept with ambiguity.

GREEN owner: this remediation pass (``transform/artifacts.py``).
"""

from __future__ import annotations

from ._semantic_fixtures import Seg, ced


def _artifacts():
    import solari_converter.transform.artifacts as artifacts

    return artifacts


def _reflow(doc):
    import solari_converter.transform.reflow as reflow

    return reflow.reflow(doc)


def _run(segs, order=None):
    doc = ced(segs, order=order)
    return _artifacts().remove_artifacts(doc, _reflow(doc)), doc


def _kept(result):
    return {s for u in result.kept_units for s in u.segment_ids}


_HDR = "ACME CORP CONFIDENTIAL"


def _hdr(sid, page, *, y=30.0, hints=()):
    s = Seg(sid, _HDR, (72, y, 452, y + 12), page=page)
    s.hints = list(hints)
    return s


def _body(sid, page, *, y=120.0):
    return Seg(sid, f"Body content of page {page}.", (72, y, 452, y + 12), page=page)


# --- R2 --------------------------------------------------------------------------------


def test_one_page_run_is_not_repetition_and_is_kept():
    result, _ = _run([_hdr("h1", 1), _body("b1", 1)])
    assert "h1" in _kept(result)
    assert not any(e.entry_type == "running_header" for e in result.removal_log.entries)


def test_two_page_contiguous_margin_consistent_run_is_kept_as_ambiguous():
    # R2 (second pass): 2 contiguous, position-consistent margin occurrences are
    # ambiguous — generic repetition-based removal needs >=3 qualifying occurrences.
    result, _ = _run([_hdr("h1", 1), _body("b1", 1), _hdr("h2", 2), _body("b2", 2)])
    assert {"h1", "h2"} <= _kept(result)
    entries = [e for e in result.removal_log.entries if e.entry_type == "running_header"]
    assert entries and all(e.ambiguous for e in entries)
    assert any("at least 3" in (e.note or "") for e in entries)


def test_three_page_contiguous_margin_consistent_run_is_removed():
    result, _ = _run([
        _hdr("h1", 1), _body("b1", 1), _hdr("h2", 2), _body("b2", 2),
        _hdr("h3", 3), _body("b3", 3),
    ])
    assert {"h1", "h2", "h3"}.isdisjoint(_kept(result))
    entries = [e for e in result.removal_log.entries if e.entry_type == "running_header"]
    assert entries and all(not e.ambiguous for e in entries)


def test_two_page_discontinuous_selection_is_kept_with_ambiguity():
    # only physical pages 2 and 9 were selected — the text repeats on both, but a
    # discontinuous selection cannot demonstrate continuous running furniture (R2).
    result, _ = _run([_hdr("h2", 2), _body("b2", 2), _hdr("h9", 9), _body("b9", 9)])
    assert {"h2", "h9"} <= _kept(result)
    entries = [e for e in result.removal_log.entries if e.entry_type == "running_header"]
    assert entries and all(e.ambiguous for e in entries)
    assert any("discontinuous" in (e.note or "") for e in entries)


def test_repeated_legitimate_heading_is_kept_even_across_a_contiguous_run():
    # a recurring section title carries a heading hint — meaningful content, weighs
    # against removal regardless of how many pages it repeats on.
    segs = [
        _hdr("h1", 1, hints=[("heading", 1, "docling")]), _body("b1", 1),
        _hdr("h2", 2, hints=[("heading", 1, "docling")]), _body("b2", 2),
        _hdr("h3", 3, hints=[("heading", 1, "docling")]), _body("b3", 3),
    ]
    result, _ = _run(segs)
    assert {"h1", "h2", "h3"} <= _kept(result)
    entries = [e for e in result.removal_log.entries if e.entry_type == "running_header"]
    assert entries and all(e.ambiguous for e in entries)


def test_repeated_short_body_text_off_the_margin_is_not_a_candidate():
    segs = [
        _body("top1", 1, y=40), Seg("mid1", "see note", (72, 300, 200, 312), page=1),
        _body("bot1", 1, y=700),
        _body("top2", 2, y=40), Seg("mid2", "see note", (72, 300, 200, 312), page=2),
        _body("bot2", 2, y=700),
        _body("top3", 3, y=40), Seg("mid3", "see note", (72, 300, 200, 312), page=3),
        _body("bot3", 3, y=700),
    ]
    result, _ = _run(segs)
    assert {"mid1", "mid2", "mid3"} <= _kept(result)
    assert not any(
        e.entry_type in {"running_header", "running_footer"}
        for e in result.removal_log.entries
    )


def test_genuine_running_header_across_a_sufficiently_evidenced_run_is_removed():
    segs = [
        _hdr("h1", 1), _body("b1", 1),
        _hdr("h2", 2), _body("b2", 2),
        _hdr("h3", 3), _body("b3", 3),
    ]
    result, _ = _run(segs)
    assert {"h1", "h2", "h3"}.isdisjoint(_kept(result))
    entries = [e for e in result.removal_log.entries if e.entry_type == "running_header"]
    assert entries and all(not e.ambiguous for e in entries)


def _repeat(sid_prefix, text, pages, *, y=30.0):
    segs = []
    for p in pages:
        segs.append(Seg(f"{sid_prefix}{p}", text, (72, y, 452, y + 12), page=p))
        segs.append(_body(f"body{p}", p))
    return segs


def test_same_heading_text_on_2_contiguous_pages_without_hints_is_kept():
    result, _ = _run(_repeat("hd", "Chapter Four", [1, 2]))
    assert {"hd1", "hd2"} <= _kept(result)
    entries = [e for e in result.removal_log.entries if e.entry_type == "running_header"]
    assert entries and all(e.ambiguous for e in entries)


def test_same_year_on_2_contiguous_pages_is_kept():
    result, _ = _run(_repeat("yr", "2026", [1, 2]))
    assert {"yr1", "yr2"} <= _kept(result)


def test_same_bare_number_on_2_contiguous_pages_is_kept():
    result, _ = _run(_repeat("n", "123", [1, 2]))
    assert {"n1", "n2"} <= _kept(result)


def test_three_occurrences_with_a_body_collision_are_kept():
    segs = _repeat("hd", "Master Services Agreement", [1, 2, 3])
    segs.append(Seg("prose", "This Master Services Agreement is binding.",
                    (72, 300, 452, 312), page=1))
    result, _ = _run(segs)
    assert {"hd1", "hd2", "hd3"} <= _kept(result)
    entries = [e for e in result.removal_log.entries if e.entry_type == "running_header"]
    assert entries and all(e.ambiguous for e in entries)
    assert any("body" in (e.note or "") for e in entries)


def test_r2_decisions_are_deterministic_under_container_permutation():
    segs = [_hdr("h2", 2), _body("b2", 2), _hdr("h9", 9), _body("b9", 9)]
    order = [s.sid for s in segs]
    r1, _ = _run(segs, order=order)
    r2, _ = _run(list(reversed(segs)), order=order)
    assert [e.id for e in r1.removal_log.entries] == [e.id for e in r2.removal_log.entries]
    assert _kept(r1) == _kept(r2)


# --- R3 --------------------------------------------------------------------------------

_HEX32 = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
_BARCODE = "ABC123DEF456GHI7"


def _mid_body(sid, text, *, page=1, origin="native_text"):
    return Seg(sid, text, (200, 240, 360, 252), page=page, origin=origin)


def _framed():
    return [
        Seg("lead", "Leading paragraph.", (72, 60, 452, 72), page=1),
        Seg("tail", "Trailing paragraph.", (72, 500, 452, 512), page=1),
    ]


def test_digitally_signed_phrase_in_mid_body_is_kept_with_ambiguity():
    result, _ = _run(_framed() + [_mid_body("s", "Digitally signed")])
    assert "s" in _kept(result)
    entries = [e for e in result.removal_log.entries if e.entry_type == "auth_stamp"]
    assert entries and all(e.ambiguous for e in entries)


def test_legitimate_hex_value_in_body_survives():
    result, _ = _run(_framed() + [_mid_body("h", _HEX32)])
    assert "h" in _kept(result)


def test_ocr_alphanumeric_identifier_in_body_survives():
    result, _ = _run(_framed() + [_mid_body("bc", _BARCODE, origin="ocr")])
    assert "bc" in _kept(result)


def test_tall_narrow_auth_phrase_at_the_page_edge_is_kept_not_removed():
    # verticality is not independent evidence; the auth phrase pattern is shape-only.
    result, _ = _run(_framed() + [
        Seg("v", "assinado digitalmente", (28, 200, 40, 520), page=1),
    ])
    assert "v" in _kept(result)
    entries = [e for e in result.removal_log.entries
               if e.entry_type in {"auth_stamp", "vertical_auth_text"}]
    assert entries and all(e.ambiguous for e in entries)


def test_auth_phrase_at_a_content_extreme_is_retained_not_removed():
    # R3 (second pass): accepted-content extremity (``_margin_band``) is NOT physical
    # margin evidence and NOT independent artifact-specific evidence — a shape-only
    # auth phrase is retained everywhere, logged ambiguous.
    doc_segs = [
        Seg("body", "Ordinary paragraph.", (72, 100, 452, 130), page=1),
        Seg("stamp", "Digitally signed", (300, 760, 452, 772), page=1),
    ]
    result, _ = _run(doc_segs)
    assert "stamp" in _kept(result)
    entries = [e for e in result.removal_log.entries if e.entry_type == "auth_stamp"]
    assert entries and all(e.ambiguous for e in entries)


def test_hex_hash_at_a_content_extreme_is_retained_not_removed():
    doc_segs = [
        Seg("body", "Ordinary paragraph.", (72, 100, 452, 130), page=1),
        Seg("hash", _HEX32, (300, 760, 452, 772), page=1),
    ]
    result, _ = _run(doc_segs)
    assert "hash" in _kept(result)
    entries = [e for e in result.removal_log.entries if e.entry_type == "auth_stamp"]
    assert entries and all(e.ambiguous for e in entries)


def test_ocr_barcode_run_at_a_content_extreme_is_retained_not_removed():
    doc_segs = [
        Seg("body", "Ordinary paragraph.", (72, 100, 452, 130), page=1),
        Seg("bar", _BARCODE, (300, 760, 452, 772), page=1, origin="ocr"),
    ]
    result, _ = _run(doc_segs)
    assert "bar" in _kept(result)
    entries = [e for e in result.removal_log.entries if e.entry_type == "barcode"]
    assert entries and all(e.ambiguous for e in entries)
