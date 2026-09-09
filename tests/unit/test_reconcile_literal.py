"""T054 — failing-first tests for literal-content reconciliation.

Split ownership:

* **T057** (``src/solari_converter/reconcile/confidence.py``) owns the deterministic
  comparison-key, the materiality policy, the deterministic confidence functions, and
  the M2 technique-precedence policy — these tests turn **GREEN** in Block 1.
* **T060** (``src/solari_converter/reconcile/literal.py``) owns per-group dispatch:
  emitting the ``ReconciliationDecision``, the < 0.75 → HUMAN_REVIEW_REQUIRED /
  ≥ 0.75 → LLM ``select`` routing, the post-LLM guard, and the double-call flip check.
  Those live in ``class TestFutureOwnerT060`` and stay **RED** until Block ≥ 2.

Frozen references: research §21b / §21d, data-model.md ``ReconciliationDecision``
(SC-020), the block brief §4–§7.
"""

from __future__ import annotations

import pytest


def _conf():
    import solari_converter.reconcile.confidence as confidence  # GREEN owner: T057

    return confidence


# --------------------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------------------


def _seg(sid, bbox, text, idx, *, origin="native_text", technique="pdfplumber",
         ocr_conf=None):
    from solari_converter.model.provenance import SourceRef
    from solari_converter.model.segment import SourceBackedSegment

    return SourceBackedSegment(
        segment_id=sid,
        text=text,
        reading_order_index=idx,
        source=SourceRef(
            physical_page=1,
            bbox=bbox,
            origin_kind=origin,
            extraction_technique=technique,
            ocr_confidence=ocr_conf,
        ),
    )


def _group(align, *members):
    """Build an AlignedSegmentGroup straight from the T056 constructors."""
    bbox = (100.0, 100.0, 300.0, 120.0)
    return align.AlignedSegmentGroup(
        group_id="g-test",
        physical_page=1,
        region_bbox=bbox,
        members=tuple(
            align.AlignedMember(
                technique=s.source.extraction_technique,
                segment_id=s.segment_id,
                text=s.text,
                source=s.source,
                reading_order_index=s.reading_order_index,
            )
            for s in members
        ),
    )


def _align():
    import solari_converter.reconcile.align as align  # GREEN owner: T056

    return align


# --------------------------------------------------------------------------------------
# comparison key — frozen transformations only (block brief §4)
# --------------------------------------------------------------------------------------


def test_comparison_key_applies_nfc():
    c = _conf()
    assert c.comparison_key("café") == c.comparison_key("café")


def test_comparison_key_collapses_unicode_whitespace_including_nbsp_cr_lf():
    c = _conf()
    assert c.comparison_key("A B\r\nC\tD") == c.comparison_key("A B C D")


def test_comparison_key_folds_smart_quotes():
    c = _conf()
    assert c.comparison_key("“hi” ‘there’") == c.comparison_key('"hi" \'there\'')


def test_comparison_key_does_not_apply_nfkc_or_ligature_expansion():
    c = _conf()
    assert c.comparison_key("ﬁle") != c.comparison_key("file")
    assert "ﬁ" in c.comparison_key("ﬁle")


def test_comparison_key_does_not_remove_soft_hyphen():
    c = _conf()
    assert "­" in c.comparison_key("cad­astro")


def test_comparison_key_does_not_repair_replacement_character():
    c = _conf()
    assert "�" in c.comparison_key("val�or")


def test_comparison_key_is_not_case_folding():
    c = _conf()
    assert c.comparison_key("ABC") != c.comparison_key("abc")


def test_comparison_key_never_mutates_input_or_leaks_into_stored_text():
    c = _conf()
    raw = "R$ 1.234,56  “x”"
    _ = c.comparison_key(raw)
    assert raw == "R$ 1.234,56  “x”"


# --------------------------------------------------------------------------------------
# materiality policy (block brief §5, T054 wording)
# --------------------------------------------------------------------------------------


def test_whitespace_only_difference_is_not_material():
    c = _conf()
    assert c.is_material("foo bar", "foo  bar") is False
    assert c.is_material("foo bar", "foo bar") is False


def test_case_only_difference_is_not_material():
    c = _conf()
    assert c.is_material("Total", "total") is False
    assert c.is_material("CLÁUSULA", "cláusula") is False


def test_digit_difference_is_material():
    c = _conf()
    assert c.is_material("R$ 100", "R$ 108") is True


def test_letter_or_diacritic_difference_is_material():
    c = _conf()
    assert c.is_material("cláusula", "clausula") is True


def test_punctuation_only_difference_is_material():
    # frozen policy names only whitespace + case as non-material
    c = _conf()
    assert c.is_material("art. 12", "art 12") is True


def test_equal_values_are_not_material():
    c = _conf()
    assert c.is_material("identical", "identical") is False


# --------------------------------------------------------------------------------------
# Unicode-safe case classification — no str.casefold() (block brief §2)
# --------------------------------------------------------------------------------------


def test_ascii_case_only_pair_is_classified_case_not_material():
    c = _conf()
    assert c.classify_diff("Total", "total") == "case"
    assert c.is_material("Total", "TOTAL") is False


def test_ligature_versus_expanded_letters_is_material():
    c = _conf()
    assert c.classify_diff("ﬁle", "file") == "material"
    assert c.is_material("ﬁle", "file") is True


def test_eszett_versus_double_s_is_material():
    c = _conf()
    assert c.is_material("ß", "SS") is True
    assert c.is_material("STRASSE", "STRAßE") is True


def test_long_s_fold_equivalence_remains_material():
    # ſ (U+017F) casefolds to "s" but is not a simple 1:1 letter-case distinction
    c = _conf()
    assert c.is_material("ſ", "s") is True


def test_length_changing_fold_equivalence_remains_material():
    # ﬀ (U+FB00) casefolds to "ff"
    c = _conf()
    assert c.is_material("ﬀ", "ff") is True


# --------------------------------------------------------------------------------------
# group-level materiality — native/native vs native+OCR case policy (block brief §3)
# --------------------------------------------------------------------------------------


def test_native_vs_native_case_only_disagreement_is_material_at_group_level():
    c, align = _conf(), _align()

    def build(first_docling: bool):
        d = _seg("d1", (100.0, 100.0, 300.0, 120.0), "Total", 0, technique="docling")
        p = _seg("p1", (100.0, 100.0, 300.0, 120.0), "total", 0, technique="pdfplumber")
        return _group(align, d, p) if first_docling else _group(align, p, d)

    for g in (build(True), build(False)):
        assert c.classify_group_diff(g) == "material"
        assert c.group_material_disagreement(g) is True


def test_native_agreement_plus_ocr_case_difference_is_not_material():
    c, align = _conf(), _align()
    g = _group(
        align,
        _seg("d1", (100.0, 100.0, 300.0, 120.0), "Total", 0, technique="docling"),
        _seg("p1", (100.0, 100.0, 300.0, 120.0), "Total", 0, technique="pdfplumber"),
        _seg("o1", (100.0, 100.0, 300.0, 120.0), "total", 0, origin="ocr",
             technique="ocr:tesseract", ocr_conf=70.0),
    )
    assert c.classify_group_diff(g) == "case"
    assert c.group_material_disagreement(g) is False


def test_group_whitespace_only_difference_stays_non_material():
    c, align = _conf(), _align()
    g = _group(
        align,
        _seg("d1", (100.0, 100.0, 300.0, 120.0), "foo bar", 0, technique="docling"),
        _seg("p1", (100.0, 100.0, 300.0, 120.0), "foo  bar", 0, technique="pdfplumber"),
    )
    assert c.group_material_disagreement(g) is False


def test_native_vs_native_case_disagreement_confidence_stays_below_threshold():
    c, align = _conf(), _align()
    g = _group(
        align,
        _seg("d1", (100.0, 100.0, 300.0, 120.0), "Total", 0, technique="docling"),
        _seg("p1", (100.0, 100.0, 300.0, 120.0), "total", 0, technique="pdfplumber"),
    )
    # flows through the material-confidence path and stays < 0.75 (→ HUMAN_REVIEW in T060)
    assert c.literal_confidence(g) < 0.75


def test_classification_never_mutates_stored_literal_values():
    c, align = _conf(), _align()
    g = _group(
        align,
        _seg("d1", (100.0, 100.0, 300.0, 120.0), "Total", 0, technique="docling"),
        _seg("p1", (100.0, 100.0, 300.0, 120.0), "total", 0, technique="pdfplumber"),
    )
    c.classify_group_diff(g)
    c.literal_confidence(g)
    c.is_material("Total", "total")
    assert {m.text for m in g.members} == {"Total", "total"}


# --------------------------------------------------------------------------------------
# technique precedence — M2 resolution (block brief §6)
# --------------------------------------------------------------------------------------


def test_native_precedence_constant_is_frozen_order():
    c = _conf()
    assert c.NATIVE_TECHNIQUE_PRECEDENCE == ("docling", "pdfplumber")


def test_native_outranks_ocr_for_a_non_material_difference():
    c = _conf()
    assert c.preferred_technique(["ocr:tesseract", "pdfplumber"]) == "pdfplumber"
    assert c.preferred_technique(["docling", "ocr:tesseract"]) == "docling"


def test_docling_outranks_pdfplumber():
    c = _conf()
    assert c.preferred_technique(["pdfplumber", "docling"]) == "docling"


def test_precedence_does_not_depend_on_input_order():
    c = _conf()
    a = c.preferred_technique(["ocr:tesseract", "pdfplumber", "docling"])
    b = c.preferred_technique(["docling", "pdfplumber", "ocr:tesseract"])
    assert a == b == "docling"


def test_ocr_is_used_only_when_no_native_candidate_exists():
    c = _conf()
    assert c.preferred_technique(["ocr:tesseract"]) == "ocr:tesseract"


def test_two_ocr_paths_resolve_deterministically_not_by_iteration_order():
    c = _conf()
    a = c.preferred_technique(["ocr:tesseract", "ocr:rapidocr"])
    b = c.preferred_technique(["ocr:rapidocr", "ocr:tesseract"])
    assert a == b


def test_pick_verbatim_returns_a_stored_literal_not_the_comparison_form():
    c = _conf()
    align = _align()
    g = _group(
        align,
        _seg("d1", (100.0, 100.0, 300.0, 120.0), "foo  bar", 0, technique="docling"),
        _seg("p1", (100.0, 100.0, 300.0, 120.0), "foo bar", 0, technique="pdfplumber"),
    )
    picked = c.pick_verbatim(g)
    assert picked in {"foo  bar", "foo bar"}      # a real stored value
    assert picked == "foo  bar"                   # docling wins the native tie-break, verbatim


# --------------------------------------------------------------------------------------
# confidence — deterministic, no LLM (block brief §5)
# --------------------------------------------------------------------------------------


def test_literal_confidence_is_deterministic():
    c = _conf()
    align = _align()
    g = _group(
        align,
        _seg("d1", (100.0, 100.0, 300.0, 120.0), "R$ 100", 0, technique="docling"),
        _seg("p1", (100.0, 100.0, 300.0, 120.0), "R$ 108", 0, technique="pdfplumber"),
    )
    assert c.literal_confidence(g) == c.literal_confidence(g)


def test_literal_confidence_module_imports_no_llm_client():
    import ast
    import pathlib

    src = pathlib.Path(
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "solari_converter" / "reconcile" / "confidence.py"
    ).read_text()
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any("llm" in m for m in imported), imported
    assert "random" not in imported


def test_full_agreement_scores_confidence_one():
    c = _conf()
    align = _align()
    g = _group(
        align,
        _seg("d1", (100.0, 100.0, 300.0, 120.0), "agreed", 0, technique="docling"),
        _seg("p1", (100.0, 100.0, 300.0, 120.0), "agreed", 0, technique="pdfplumber"),
        _seg("o1", (100.0, 100.0, 300.0, 120.0), "agreed", 0, origin="ocr",
             technique="ocr:tesseract", ocr_conf=80.0),
    )
    assert c.literal_confidence(g) == pytest.approx(1.0)


def test_native_presence_raises_confidence_versus_all_ocr():
    c = _conf()
    align = _align()
    native_vs_ocr = _group(
        align,
        _seg("p1", (100.0, 100.0, 300.0, 120.0), "R$ 100", 0, technique="pdfplumber"),
        _seg("o1", (100.0, 100.0, 300.0, 120.0), "R$ 108", 0, origin="ocr",
             technique="ocr:tesseract", ocr_conf=75.0),
    )
    all_ocr = _group(
        align,
        _seg("o1", (100.0, 100.0, 300.0, 120.0), "R$ 100", 0, origin="ocr",
             technique="ocr:rapidocr", ocr_conf=75.0),
        _seg("o2", (100.0, 100.0, 300.0, 120.0), "R$ 108", 0, origin="ocr",
             technique="ocr:tesseract", ocr_conf=75.0),
    )
    assert c.literal_confidence(native_vs_ocr) > c.literal_confidence(all_ocr)


def test_confidence_is_bounded_zero_to_one():
    c = _conf()
    align = _align()
    g = _group(
        align,
        _seg("o1", (100.0, 100.0, 300.0, 120.0), "wildly", 0, origin="ocr",
             technique="ocr:rapidocr", ocr_conf=1.0),
        _seg("o2", (100.0, 100.0, 300.0, 120.0), "different 4271", 0, origin="ocr",
             technique="ocr:tesseract", ocr_conf=2.0),
    )
    v = c.literal_confidence(g)
    assert 0.0 <= v <= 1.0


def test_higher_ocr_confidence_raises_the_score():
    c = _conf()
    align = _align()

    def g(conf):
        return _group(
            align,
            _seg("p1", (100.0, 100.0, 300.0, 120.0), "R$ 100", 0, technique="pdfplumber"),
            _seg("o1", (100.0, 100.0, 300.0, 120.0), "R$ 108", 0, origin="ocr",
                 technique="ocr:tesseract", ocr_conf=conf),
        )

    assert c.literal_confidence(g(95.0)) > c.literal_confidence(g(40.0))


# --------------------------------------------------------------------------------------
# T060 — per-group dispatch. RED until Block >= 2.
# --------------------------------------------------------------------------------------


class TestFutureOwnerT060:
    """GREEN owner: **T060** — ``reconcile/literal.py`` (NOT in Block 1).

    Block 1 deliberately does not create ``reconcile/literal.py``; every test here
    fails at import until T060 lands. They pin the frozen dispatch contract:
    ``deterministic_agreement`` emission, the 0.75 threshold routing, the post-LLM
    guard, and the double-call flip check (research §21b / §21d, SC-020).
    """

    def _literal(self):
        import solari_converter.reconcile.literal as literal  # GREEN owner: T060

        return literal

    def test_full_agreement_emits_deterministic_agreement_decision(self):
        literal = self._literal()
        align = _align()
        g = _group(
            align,
            _seg("d1", (100.0, 100.0, 300.0, 120.0), "agreed", 0, technique="docling"),
            _seg("p1", (100.0, 100.0, 300.0, 120.0), "agreed", 0, technique="pdfplumber"),
        )
        decision = literal.reconcile_literal(g)
        assert decision.method == "deterministic_agreement"
        assert decision.selected["value"] == "agreed"

    def test_below_threshold_material_disagreement_requires_human_review(self):
        literal = self._literal()
        align = _align()
        g = _group(
            align,
            _seg("o1", (100.0, 100.0, 300.0, 120.0), "R$ 100", 0, origin="ocr",
                 technique="ocr:rapidocr", ocr_conf=30.0),
            _seg("o2", (100.0, 100.0, 300.0, 120.0), "R$ 188", 0, origin="ocr",
                 technique="ocr:tesseract", ocr_conf=30.0),
        )
        assert literal.reconcile_literal(g).outcome == "HUMAN_REVIEW_REQUIRED"

    def test_at_or_above_threshold_routes_to_llm_select(self):
        literal = self._literal()
        assert hasattr(literal, "reconcile_literal")
        raise AssertionError("T060: >= 0.75 -> llm_select selection-only path not built yet")

    def test_guard_rejects_a_non_candidate_llm_value_to_human_review(self):
        assert hasattr(self._literal(), "reconcile_literal")
        raise AssertionError("T060: post-LLM guard dispatch not built yet")

    def test_llm_flip_across_the_two_calls_requires_human_review(self):
        assert hasattr(self._literal(), "reconcile_literal")
        raise AssertionError("T060: double-call flip detection not built yet")
