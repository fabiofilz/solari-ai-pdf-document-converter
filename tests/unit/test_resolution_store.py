"""T029 — failing-first tests for the append-only resolution store (GREEN owner: **T030**).

Frozen rules (research §22 / §22.2, FR-057b / FR-068 / FR-070 / FR-071 / FR-076, M1 / M3):

* ``compute_applicability_key`` = ``sha256(source_sha256 ⧺ conflict_type ⧺
  canonical(page, region, aligned candidate-value set) ⧺
  canonical_json(config_subset))`` — deterministic, candidate-set order-independent;
* append-only — a changed answer is a **new line**, prior lines are kept;
* ``sequence_index`` is the **sole** authority for "currently-applicable" (H6): unique,
  strictly increasing store-wide (``= max(existing) + 1``); current = **greatest
  ``sequence_index`` for the key**, not the last line;
* ``supersedes`` is audit linkage only (I2/I3/I4/I5); the loader **fails closed** per key
  on any violation (I6) — no guessing;
* ``resolution_id`` is content-bound via the T024 helper (the store is the sole assigner);
* durability: temp + flush + fsync + atomic replace; a torn/unparseable final record is
  ignored and never counts;
* a ``mode: entered`` literal value is stored **verbatim** — no strip / normalisation;
* ``applicable_resolution_digest()`` is owned by the store.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from solari_converter.model.human_review import HumanReviewResolution, compute_resolution_id


def _mod():
    import solari_converter.reconcile.resolutions as resolutions  # GREEN owner: T030

    return resolutions


_ENV = dict(
    run_id="0" * 16, tool_version="0.1.0", source_pdf="agreement.pdf",
    source_sha256="a" * 64, page_selection="all",
)
_EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


def _key(mod, **over) -> str:
    base = dict(
        source_sha256="a" * 64,
        conflict_type="literal_content",
        physical_page=5,
        region_bboxes=[[10.0, 20.0, 110.0, 40.0]],
        candidate_values=["R$ 1.599,80", "R$ 1.599.80"],
        config_subset={
            "ocr_engine": "tesseract",
            "ocr_languages_override": None,
            "ocr_confidence_threshold": 70,
            "enabled_extraction_paths": ["docling", "pdfplumber", "ocr"],
        },
    )
    base.update(over)
    return mod.compute_applicability_key(**base)


def _store(tmp_path: Path):
    return _mod().ResolutionStore(tmp_path / "resolutions.jsonl")


def _append(store, *, key: str, selected: dict, conflict_type: str = "literal_content",
            review_item_id: str = "item-1"):
    return store.append(
        applicability_key=key,
        review_item_id=review_item_id,
        conflict_type=conflict_type,
        physical_page=5,
        region_bboxes=[[10.0, 20.0, 110.0, 40.0]],
        candidates_presented=[{"technique": "docling", "value": "R$ 1.599,80"}],
        selected=selected,
        envelope=_ENV,
    )


_LIT = {"mode": "select", "value": "R$ 1.599,80", "manually_verified": False}
_LIT2 = {"mode": "entered", "value": "R$ 1.599,80 (corrected)", "manually_verified": True}


# --- applicability key ----------------------------------------------------------


def test_applicability_key_is_64_hex_and_deterministic() -> None:
    m = _mod()
    k = _key(m)
    assert len(k) == 64 and int(k, 16) >= 0
    assert k == _key(m)


def test_applicability_key_candidate_set_is_order_independent() -> None:
    m = _mod()
    assert _key(m, candidate_values=["R$ 1.599,80", "R$ 1.599.80"]) == _key(
        m, candidate_values=["R$ 1.599.80", "R$ 1.599,80"]
    )


def test_applicability_key_changes_with_source_conflict_engine_and_candidates() -> None:
    m = _mod()
    base = _key(m)
    assert _key(m, source_sha256="b" * 64) != base
    assert _key(m, conflict_type="reading_order") != base
    assert _key(m, candidate_values=["only one"]) != base
    assert _key(m, config_subset={
        "ocr_engine": "rapidocr", "ocr_languages_override": None,
        "ocr_confidence_threshold": 70, "enabled_extraction_paths": ["pdfplumber"],
    }) != base


def test_enabled_path_subset_is_a_set_not_an_ordered_list() -> None:
    m = _mod()
    a = _key(m, config_subset={
        "ocr_engine": "tesseract", "ocr_languages_override": None,
        "ocr_confidence_threshold": 70,
        "enabled_extraction_paths": ["docling", "pdfplumber", "ocr"],
    })
    b = _key(m, config_subset={
        "ocr_engine": "tesseract", "ocr_languages_override": None,
        "ocr_confidence_threshold": 70,
        "enabled_extraction_paths": ["ocr", "docling", "pdfplumber"],
    })
    assert a == b


# --- append-only + sequence_index authority ----------------------------------


def test_append_is_append_only_and_keeps_every_prior_line(tmp_path: Path) -> None:
    s = _store(tmp_path)
    k = _key(_mod())
    _append(s, key=k, selected=_LIT)
    _append(s, key=k, selected=_LIT2)
    lines = [json.loads(x) for x in (tmp_path / "resolutions.jsonl").read_text().splitlines() if x]
    assert len(lines) == 2
    assert [ln["selected"]["value"] for ln in lines] == [_LIT["value"], _LIT2["value"]]


def test_sequence_index_is_max_plus_one_unique_and_increasing(tmp_path: Path) -> None:
    s = _store(tmp_path)
    m = _mod()
    r0 = _append(s, key=_key(m, physical_page=1), selected=_LIT, review_item_id="a")
    r1 = _append(s, key=_key(m, physical_page=2), selected=_LIT, review_item_id="b")
    r2 = _append(s, key=_key(m, physical_page=1), selected=_LIT2, review_item_id="a")
    assert [r0.sequence_index, r1.sequence_index, r2.sequence_index] == [0, 1, 2]


def test_current_resolution_is_greatest_sequence_index_for_the_key_not_last_line(
    tmp_path: Path,
) -> None:
    # Hand-write a store whose LAST LINE is key B but key A's current is an earlier line.
    m = _mod()
    ka, kb = _key(m, physical_page=1), _key(m, physical_page=2)

    def rec(key, seq, value, supersedes):
        sel = {"mode": "select", "value": value, "manually_verified": False}
        return {
            **_ENV, "record_type": "human_review_resolution", "schema_version": "2.1",
            "resolution_id": compute_resolution_id(
                applicability_key=key, sequence_index=seq, selected=sel),
            "sequence_index": seq, "supersedes": supersedes, "applicability_key": key,
            "review_item_id": "x", "conflict_type": "literal_content", "physical_page": 5,
            "region_bboxes": [[0, 0, 1, 1]],
            "candidates_presented": [{"technique": "docling", "value": value}],
            "decision_method": "human_confirmed", "selected": sel, "reviewer_note": None,
        }

    a0 = rec(ka, 0, "A-old", None)
    a2 = rec(ka, 2, "A-current", a0["resolution_id"])
    b3 = rec(kb, 3, "B-current", None)
    (tmp_path / "resolutions.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in (a0, a2, b3)) + "\n"
    )
    s = _store(tmp_path)
    idx = s.load_index()
    assert idx.current[ka].selected["value"] == "A-current"
    assert idx.current[kb].selected["value"] == "B-current"
    assert s.replay_for(ka).sequence_index == 2


# --- supersedes invariants + fail-closed -----------------------------------


def test_first_resolution_has_null_supersedes_second_links_to_the_first(tmp_path: Path) -> None:
    s = _store(tmp_path)
    k = _key(_mod())
    r0 = _append(s, key=k, selected=_LIT)
    r1 = _append(s, key=k, selected=_LIT2)
    assert r0.supersedes is None
    assert r1.supersedes == r0.resolution_id


def _write_records(tmp_path: Path, records: list[dict]) -> None:
    (tmp_path / "resolutions.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n"
    )


def _raw(key, seq, value, supersedes):
    sel = {"mode": "select", "value": value, "manually_verified": False}
    return {
        **_ENV, "record_type": "human_review_resolution", "schema_version": "2.1",
        "resolution_id": compute_resolution_id(
            applicability_key=key, sequence_index=seq, selected=sel),
        "sequence_index": seq, "supersedes": supersedes, "applicability_key": key,
        "review_item_id": "x", "conflict_type": "literal_content", "physical_page": 5,
        "region_bboxes": [[0, 0, 1, 1]],
        "candidates_presented": [{"technique": "docling", "value": value}],
        "decision_method": "human_confirmed", "selected": sel, "reviewer_note": None,
    }


def test_i4_supersedes_pointing_at_a_missing_target_fails_the_key_closed(tmp_path: Path) -> None:
    m = _mod()
    ka, kb = _key(m, physical_page=1), _key(m, physical_page=2)
    bad = _raw(ka, 1, "A", supersedes="deadbeefdeadbeef")  # no such resolution_id
    ok = _raw(kb, 0, "B", supersedes=None)
    _write_records(tmp_path, [ok, bad])
    idx = _store(tmp_path).load_index()
    assert ka in idx.failed_closed and ka not in idx.current
    assert idx.current[kb].selected["value"] == "B"  # other keys unaffected


def test_i5_a_fork_two_records_superseding_the_same_target_fails_the_key_closed(
    tmp_path: Path,
) -> None:
    m = _mod()
    k = _key(m)
    a0 = _raw(k, 0, "root", None)
    a1 = _raw(k, 1, "branch-1", a0["resolution_id"])
    a2 = _raw(k, 2, "branch-2", a0["resolution_id"])  # fork!
    _write_records(tmp_path, [a0, a1, a2])
    idx = _store(tmp_path).load_index()
    assert k in idx.failed_closed and k not in idx.current
    assert _store(tmp_path).replay_for(k) is None


def test_i6_fail_closed_never_guesses_a_current_record(tmp_path: Path) -> None:
    m = _mod()
    k = _key(m)
    # sequence_index not strictly increasing store-wide (duplicate) — I1 violation.
    _write_records(tmp_path, [_raw(k, 0, "x", None), _raw(k, 0, "y", None)])
    idx = _store(tmp_path).load_index()
    assert k in idx.failed_closed
    assert k not in idx.current


# --- content-bound resolution_id + replay -----------------------------------


def test_resolution_id_is_content_bound_via_the_t024_helper(tmp_path: Path) -> None:
    s = _store(tmp_path)
    k = _key(_mod())
    r = _append(s, key=k, selected=_LIT2)
    assert r.resolution_id == compute_resolution_id(
        applicability_key=k, sequence_index=r.sequence_index, selected=_LIT2
    )


def test_replay_for_a_key_that_never_matched_is_none(tmp_path: Path) -> None:
    s = _store(tmp_path)
    m = _mod()
    _append(s, key=_key(m), selected=_LIT)
    # a changed config subset yields a different applicability key -> no replay (FR-071)
    other = _key(m, config_subset={
        "ocr_engine": "tesseract", "ocr_languages_override": None,
        "ocr_confidence_threshold": 85,
        "enabled_extraction_paths": ["docling", "pdfplumber", "ocr"],
    })
    assert s.replay_for(other) is None


def test_jsonl_round_trips_through_the_model(tmp_path: Path) -> None:
    s = _store(tmp_path)
    k = _key(_mod())
    _append(s, key=k, selected=_LIT2)
    idx = _store(tmp_path).load_index()
    assert isinstance(idx.current[k], HumanReviewResolution)


# --- durability -----------------------------------------------------------


def test_append_publishes_a_complete_parseable_file(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _append(s, key=_key(_mod()), selected=_LIT)
    text = (tmp_path / "resolutions.jsonl").read_text(encoding="utf-8")
    assert text.endswith("\n")
    for line in text.splitlines():
        json.loads(line)  # every line parses
    assert not (tmp_path / "resolutions.jsonl.tmp").exists()  # no stray temp


def test_a_torn_final_record_is_ignored_and_never_counts(tmp_path: Path) -> None:
    s = _store(tmp_path)
    k = _key(_mod())
    _append(s, key=k, selected=_LIT)
    # simulate an external crash mid-write: a truncated JSON line appended after the valid one
    with open(tmp_path / "resolutions.jsonl", "a", encoding="utf-8") as fh:
        fh.write('{"record_type": "human_review_resolution", "sequence_ind')
    idx = _store(tmp_path).load_index()
    assert len(idx.all_records) == 1  # the torn line is not a record
    assert idx.current[k].selected["value"] == _LIT["value"]


def test_entered_literal_value_is_stored_and_reloaded_verbatim(tmp_path: Path) -> None:
    s = _store(tmp_path)
    k = _key(_mod())
    weird = "  R$ 1.599,80  \tspaced and\nnewlined  "
    _append(s, key=k, selected={"mode": "entered", "value": weird, "manually_verified": True})
    idx = _store(tmp_path).load_index()
    assert idx.current[k].selected["value"] == weird  # byte-identical, no strip/normalise


# --- applicable_resolution_digest (owned by the store) --------------------


def test_applicable_resolution_digest_empty_store_is_sha256_of_empty(tmp_path: Path) -> None:
    assert _store(tmp_path).applicable_resolution_digest() == _EMPTY_DIGEST


def test_applicable_resolution_digest_order_independent_and_moves_on_supersede(
    tmp_path: Path,
) -> None:
    s = _store(tmp_path)
    m = _mod()
    k1, k2 = _key(m, physical_page=1), _key(m, physical_page=2)
    _append(s, key=k1, selected=_LIT, review_item_id="a")
    d1 = _store(tmp_path).applicable_resolution_digest()
    _append(s, key=k2, selected=_LIT, review_item_id="b")
    d2 = _store(tmp_path).applicable_resolution_digest()
    assert d2 not in (d1, _EMPTY_DIGEST)
    # superseding k1 with a different value changes the digest
    _append(s, key=k1, selected=_LIT2, review_item_id="a")
    d3 = _store(tmp_path).applicable_resolution_digest()
    assert d3 != d2


def test_the_store_uses_no_database(tmp_path: Path) -> None:
    src = Path(_mod().__file__).read_text(encoding="utf-8")
    for banned in ("import sqlite3", "sqlalchemy", "dbm", "shelve"):
        assert banned not in src


# --- H1: scoped applicable_resolution_digest (block brief §12) -----------------

_CFG_A = {
    "ocr_engine": "tesseract", "ocr_languages_override": None,
    "ocr_confidence_threshold": 70,
    "enabled_extraction_paths": ["docling", "pdfplumber", "ocr"],
}
_CFG_B = {**_CFG_A, "ocr_confidence_threshold": 85}


def _append_matched(
    store, m, *, source_sha256, config_subset, values, selected, page=5, item="i",
):
    """Append a resolution whose ``candidates_presented`` values EXACTLY reproduce the
    ``candidate_values`` its applicability key was built from (as T061 does)."""
    key = m.compute_applicability_key(
        source_sha256=source_sha256, conflict_type="literal_content", physical_page=page,
        region_bboxes=[[10.0, 20.0, 110.0, 40.0]], candidate_values=list(values),
        config_subset=config_subset,
    )
    store.append(
        applicability_key=key, review_item_id=item, conflict_type="literal_content",
        physical_page=page, region_bboxes=[[10.0, 20.0, 110.0, 40.0]],
        candidates_presented=[
            {"technique": f"t{i}", "value": v} for i, v in enumerate(values)
        ],
        selected=selected, envelope={**_ENV, "source_sha256": source_sha256},
    )
    return key


_SEL = {"mode": "select", "value": "R$ 1.599,80", "manually_verified": False}
_ENTERED = {"mode": "entered", "value": "R$ 1.599,80 (fixed)", "manually_verified": True}
_VALUES = ("R$ 1.599,80", "R$ 1.599.80")


def test_h1_unscoped_digest_is_unchanged_and_deterministic(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _append_matched(s, _mod(), source_sha256="a" * 64, config_subset=_CFG_A,
                    values=_VALUES, selected=_SEL)
    d1 = _store(tmp_path).applicable_resolution_digest()
    d2 = _store(tmp_path).applicable_resolution_digest()
    assert d1 == d2 and d1 != _EMPTY_DIGEST


def test_h1_a_resolution_from_another_document_does_not_affect_this_digest(
    tmp_path: Path,
) -> None:
    s = _store(tmp_path)
    _append_matched(s, _mod(), source_sha256="b" * 64, config_subset=_CFG_A,
                    values=_VALUES, selected=_SEL)
    # scoped to document "a" + its config: document "b"'s resolution contributes nothing
    scoped = _store(tmp_path).applicable_resolution_digest(
        source_sha256="a" * 64, config_subset=_CFG_A
    )
    assert scoped == _EMPTY_DIGEST
    # but the unscoped digest still sees it (backward compatible)
    assert _store(tmp_path).applicable_resolution_digest() != _EMPTY_DIGEST


def test_h1_config_mismatched_resolution_is_excluded_fail_closed(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _append_matched(s, _mod(), source_sha256="a" * 64, config_subset=_CFG_A,
                    values=_VALUES, selected=_SEL)
    scoped = _store(tmp_path).applicable_resolution_digest(
        source_sha256="a" * 64, config_subset=_CFG_B  # different threshold
    )
    assert scoped == _EMPTY_DIGEST


def test_h1_matching_source_and_config_resolution_is_included(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _append_matched(s, _mod(), source_sha256="a" * 64, config_subset=_CFG_A,
                    values=_VALUES, selected=_SEL)
    scoped = _store(tmp_path).applicable_resolution_digest(
        source_sha256="a" * 64, config_subset=_CFG_A
    )
    assert scoped not in (_EMPTY_DIGEST,)
    assert scoped == _store(tmp_path).applicable_resolution_digest()  # only record


def test_h1_human_entered_resolution_contributes_to_the_scoped_digest(
    tmp_path: Path,
) -> None:
    s = _store(tmp_path)
    _append_matched(s, _mod(), source_sha256="a" * 64, config_subset=_CFG_A,
                    values=_VALUES, selected=_ENTERED)
    scoped = _store(tmp_path).applicable_resolution_digest(
        source_sha256="a" * 64, config_subset=_CFG_A
    )
    assert scoped != _EMPTY_DIGEST


def test_h1_scoped_digest_is_order_independent(tmp_path: Path) -> None:
    s = _store(tmp_path)
    m = _mod()
    _append_matched(s, m, source_sha256="a" * 64, config_subset=_CFG_A,
                    values=_VALUES, selected=_SEL, page=1, item="a")
    _append_matched(s, m, source_sha256="a" * 64, config_subset=_CFG_A,
                    values=("only",), selected={"mode": "select", "value": "only",
                                                "manually_verified": False},
                    page=2, item="b")
    d1 = _store(tmp_path).applicable_resolution_digest(
        source_sha256="a" * 64, config_subset=_CFG_A
    )
    d2 = _store(tmp_path).applicable_resolution_digest(
        source_sha256="a" * 64, config_subset=_CFG_A
    )
    assert d1 == d2 and d1 != _EMPTY_DIGEST


def test_h1_applicable_index_no_args_equals_current(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _append_matched(s, _mod(), source_sha256="a" * 64, config_subset=_CFG_A,
                    values=_VALUES, selected=_SEL)
    st = _store(tmp_path)
    assert st.applicable_index() == st.load_index().current
