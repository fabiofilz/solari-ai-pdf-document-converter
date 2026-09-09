"""T066 [US1] — failing-first tests for Stage-3 reflow + de-hyphenation.

GREEN owner: **T067** (``src/solari_converter/transform/reflow.py``).

Frozen references: spec FR-013 / FR-014 / FR-016, research §27 (authoritative v1
de-hyphenation policy), §25.2 (`dehyphenate` / `reflow_whitespace` transform vocabulary),
the S1 block brief.

Stage 3 consumes the **CED only**, is deterministic (no LLM / network / dictionary /
randomness), and never mutates a source literal except at a line boundary covered by a
recorded ``dehyphenate`` | ``reflow_whitespace`` transform. De-hyphenation keeps the
trailing ``U+002D`` by default and removes it only on positive document-internal
evidence (the joined token attested elsewhere in the same CED as a complete token) with
every §27 structural guard satisfied.
"""

from __future__ import annotations

from ._semantic_fixtures import Seg, ced


def _reflow():
    import solari_converter.transform.reflow as reflow  # GREEN owner: T067

    return reflow


def _line(sid, text, x0, top, *, page=1, width=380.0, height=12.0, **kw):
    return Seg(sid, text, (x0, top, x0 + width, top + height), page=page, **kw)


# --------------------------------------------------------------------------------------
# de-wrap / paragraph boundaries (FR-013 / FR-016)
# --------------------------------------------------------------------------------------


def test_visually_wrapped_lines_join_into_one_paragraph():
    r = _reflow()
    doc = ced([
        _line("s1", "This is a single logical paragraph that has been hard", 72, 100),
        _line("s2", "wrapped across several visual lines of the same block.", 72, 114),
    ])
    result = r.reflow(doc)
    assert len(result.units) == 1
    u = result.units[0]
    assert u.text == (
        "This is a single logical paragraph that has been hard "
        "wrapped across several visual lines of the same block."
    )
    assert u.segment_ids == ("s1", "s2")
    assert [t.kind for t in u.transforms] == ["reflow_whitespace"]
    assert u.transforms[0].permitted_by == "FR-013"
    assert u.transforms[0].stage == 3


def test_a_large_vertical_gap_starts_a_new_paragraph():
    r = _reflow()
    doc = ced([
        _line("s1", "First paragraph, one line.", 72, 100),
        _line("s2", "Second paragraph, well separated below.", 72, 180),
    ])
    result = r.reflow(doc)
    assert [u.segment_ids for u in result.units] == [("s1",), ("s2",)]
    assert result.transforms == ()  # nothing joined, no transform


def test_a_heading_hint_boundary_is_never_crossed_when_joining():
    r = _reflow()
    doc = ced([
        _line("h1", "Section Title", 72, 100, hints=[("heading", 1, "docling")]),
        _line("b1", "First body line of the section that", 72, 116),
        _line("b2", "wraps onto a second visual line.", 72, 130),
    ])
    result = r.reflow(doc)
    assert [u.segment_ids for u in result.units] == [("h1",), ("b1", "b2")]


def test_reflow_does_not_normalise_whitespace_inside_a_source_literal():
    r = _reflow()
    doc = ced([_line("s1", "spaced   out    text\tkept as-is", 72, 100)])
    result = r.reflow(doc)
    assert result.units[0].text == "spaced   out    text\tkept as-is"
    assert result.transforms == ()


def test_a_page_boundary_alone_neither_forces_a_break_nor_proves_continuation():
    r = _reflow()
    # identical geometry, consecutive in accepted order, but different physical pages
    doc = ced([
        Seg("p1", "text ending page one", (72, 700, 452, 712), page=1),
        Seg("p2", "text starting page two", (72, 60, 452, 72), page=2),
    ])
    result = r.reflow(doc)
    # conservative: a cross-page pair is not merged into one paragraph by default
    assert [u.segment_ids for u in result.units] == [("p1",), ("p2",)]


def test_flattening_units_preserves_the_accepted_reading_order():
    r = _reflow()
    doc = ced([
        _line("a", "alpha line one that", 72, 100),
        _line("b", "wraps here", 72, 114),
        _line("c", "Gamma new paragraph", 72, 170),
    ])
    result = r.reflow(doc)
    flat = [sid for u in result.units for sid in u.segment_ids]
    assert flat == list(doc.accepted_reading_order)
    assert flat == result.source_order()


def test_reflow_is_deterministic_across_repeated_calls():
    r = _reflow()
    doc = ced([
        _line("a", "one line that", 72, 100),
        _line("b", "continues here", 72, 114),
    ])
    first, second = r.reflow(doc), r.reflow(doc)
    assert [u.text for u in first.units] == [u.text for u in second.units]
    assert [t.kind for t in first.transforms] == [t.kind for t in second.transforms]


# --------------------------------------------------------------------------------------
# de-hyphenation — research §27 (authoritative)
# --------------------------------------------------------------------------------------


def _wrap(left, right, *, attest=None, right_ocr=None, left_hint=None):
    """A hyphenated wrap: ``left`` ends with '-', ``right`` starts the next line.
    ``attest`` (if given) is a later body segment that contains the joined token."""
    segs = [
        _line("L", left, 72, 100),
        _line("R", right, 72, 114, ocr_conf=right_ocr,
              origin="ocr" if right_ocr is not None else "native_text",
              technique="ocr:tesseract" if right_ocr is not None else "pdfplumber"),
    ]
    if left_hint:
        segs[0].hints = [left_hint]
    if attest:
        segs.append(_line("A", attest, 72, 300))
    return ced(segs)


def test_wrapped_token_with_no_in_document_attestation_keeps_the_hyphen():
    r = _reflow()
    result = r.reflow(_wrap("the term hard-", "wrapped stays hyphenated"))
    u = result.units[0]
    assert "hard-wrapped" in u.text or "hard- wrapped" in u.text
    assert "hardwrapped" not in u.text
    assert all(t.kind != "dehyphenate" for t in u.transforms)


def test_wrapped_token_attested_elsewhere_is_dehyphenated():
    r = _reflow()
    result = r.reflow(_wrap(
        "a maintenance sched-", "ule applies to each phase",
        attest="the delivery schedule was revised twice",
    ))
    u = result.units[0]
    assert "schedule applies to each phase" in u.text
    assert "sched-ule" not in u.text and "sched- ule" not in u.text
    d = [t for t in u.transforms if t.kind == "dehyphenate"]
    assert len(d) == 1
    assert d[0].permitted_by == "FR-014"
    assert d[0].joined_with == "R"
    assert "L" in d[0].segment_ids and "R" in d[0].segment_ids
    assert d[0].evidence and "A" in d[0].evidence  # names the attesting occurrence


def test_compound_hyphen_is_retained_even_when_it_looks_like_a_wrap():
    r = _reflow()
    # "IGP-M" split across a line; "IGPM" is NOT attested anywhere -> keep the hyphen
    result = r.reflow(_wrap("adjusted by IGP-", "M annually", attest="index IGP-M table"))
    assert "IGPM" not in result.units[0].text


def test_a_numbering_or_range_hyphen_is_never_removed():
    r = _reflow()
    result = r.reflow(_wrap("clauses 3-", "5 inclusive", attest="see 35 below"))
    assert "35 inclusive" not in result.units[0].text
    assert all(t.kind != "dehyphenate" for t in result.units[0].transforms)


def test_en_dash_and_em_dash_are_never_treated_as_line_break_hyphens():
    r = _reflow()
    for dash in ("–", "—", "‐", "‑"):
        result = r.reflow(_wrap(f"the scope{dash}", "extends further",
                                attest="the scopeextends clause"))
        assert f"scope{dash}" in result.units[0].text
        assert all(t.kind != "dehyphenate" for t in result.units[0].transforms)


def test_right_fragment_beginning_uppercase_blocks_dehyphenation():
    r = _reflow()
    result = r.reflow(_wrap("the Vice-", "President signed",
                            attest="the VicePresident was absent"))
    assert "VicePresident" not in result.units[0].text


def test_left_fragment_shorter_than_two_letters_blocks_dehyphenation():
    r = _reflow()
    result = r.reflow(_wrap("a-", "typical case here", attest="an atypical clause"))
    assert "atypical case here" not in result.units[0].text


def test_a_heading_boundary_blocks_dehyphenation():
    r = _reflow()
    doc = _wrap("depart-", "mental policy text", attest="the departmental review",
               left_hint=("heading", 1, "docling"))
    result = r.reflow(doc)
    # the heading segment is never joined into the next segment
    assert result.units[0].segment_ids == ("L",)
    assert result.units[0].text == "depart-"
    assert all(t.kind != "dehyphenate" for u in result.units for t in u.transforms)


def test_low_confidence_ocr_right_fragment_keeps_the_hyphen():
    r = _reflow()
    result = r.reflow(_wrap(
        "a mainten-", "ance window", right_ocr=25.0,
        attest="the maintenance window opens",
    ))
    assert "maintenance window" not in result.units[0].text
    assert all(t.kind != "dehyphenate" for t in result.units[0].transforms)


def test_dehyphenation_changes_no_character_other_than_the_boundary_hyphen():
    r = _reflow()
    doc = _wrap("the sub-", "section applies", attest="each subsection is numbered")
    result = r.reflow(doc)
    u = result.units[0]
    # exactly the '-' at the boundary was removed; everything else verbatim + one join
    assert u.text == "the subsection applies"


def test_a_transform_record_is_created_only_when_a_literal_actually_changes():
    r = _reflow()
    # no wrap, no join -> zero transforms
    plain = r.reflow(ced([_line("s", "an ordinary standalone line.", 72, 100)]))
    assert plain.transforms == ()


def test_clean_transform_style_fixture_follows_the_pinned_conservative_expectation():
    r = _reflow()
    # the historical clean_transform shape: wrapped tokens 'hardwrapped' / 'linebreak'
    # are NOT attested in-document -> those line-break hyphens are RETAINED; the
    # compound hyphen 'compound-word' is kept as always.
    doc = ced([
        _line("s1", "This is a single logical paragraph that has been hard-", 72, 100),
        _line("s2", "wrapped across several visual lines and also contains a com-", 72, 114),
        _line("s3", "pound-word hyphen that must be preserved, unlike the line-", 72, 128),
        _line("s4", "break hyphens above it.", 72, 142),
    ])
    text = r.reflow(doc).units[0].text
    # every hyphen retained: the two line-break hyphens are unattested, the middle one
    # is a genuine compound hyphen
    assert "hard-wrapped" in text
    assert "com-pound-word" in text
    assert "line-break" in text
    assert "hardwrapped" not in text and "linebreak" not in text
