"""T072 — failing-first tests for the ``RemovalLog`` model + report (beyond the
schema-conformance pair already pinned in ``tests/contract/test_removal_log_schema.py``).

GREEN owner: **T072** (``src/solari_converter/reports/removal_log.py``).

Pins: deterministic content-derived entry ids (no uuid / timestamp / randomness);
schema-name fields (``element_type`` / ``kept_due_to_ambiguity``) with **non-serialized**
read-only convenience properties (``entry_type`` / ``ambiguous``) some call sites use;
deterministic ``render_markdown()``; entries kept in the order given (no silent resort).
"""

from __future__ import annotations

import json

from tests.contract._schema_subset import assert_valid


def _model():
    import solari_converter.reports.removal_log as removal_log

    return removal_log


_ENV = dict(
    run_id="0" * 16, tool_version="0.1.0", source_pdf="a.pdf",
    source_sha256="a" * 64, page_selection="all",
)


def test_removal_entry_id_is_deterministic_and_content_derived():
    m = _model()
    a = m.removal_entry_id(page=2, element_type="running_header", segment_ids=["h2", "h1"])
    b = m.removal_entry_id(page=2, element_type="running_header", segment_ids=["h1", "h2"])
    assert a == b  # order-independent (sorted internally)
    assert a.startswith("rm-")
    c = m.removal_entry_id(page=2, element_type="running_footer", segment_ids=["h1", "h2"])
    assert c != a  # element_type participates in the digest
    d = m.removal_entry_id(page=3, element_type="running_header", segment_ids=["h1", "h2"])
    assert d != a  # page participates in the digest
    # no wall-clock / random component: repeated calls are byte-identical
    assert m.removal_entry_id(page=2, element_type="running_header",
                               segment_ids=["h1", "h2"]) == a


def test_entry_convenience_properties_mirror_schema_fields_without_serializing():
    m = _model()
    entry = m.RemovalEntry(
        id="rm-abc123", page=1, element_type="page_number",
        reason="matched_pattern", kept_due_to_ambiguity=False,
    )
    assert entry.entry_type == entry.element_type == "page_number"
    assert entry.ambiguous == entry.kept_due_to_ambiguity is False
    dumped = entry.model_dump()
    assert "entry_type" not in dumped
    assert "ambiguous" not in dumped
    assert set(dumped) <= {
        "id", "page", "element_type", "text_excerpt", "bbox",
        "reason", "kept_due_to_ambiguity", "note",
    }


def test_removal_log_conforms_to_schema_with_populated_entries():
    from pathlib import Path

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "specs/001-pdf-markdown-converter/contracts/removal-log.schema.json"
        ).read_text(encoding="utf-8")
    )
    m = _model()
    log = m.RemovalLog(
        **_ENV,
        entries=[
            m.RemovalEntry(
                id=m.removal_entry_id(page=1, element_type="running_header",
                                       segment_ids=["h1"]),
                page=1, element_type="running_header", text_excerpt="ACME CORP",
                bbox=(72.0, 30.0, 452.0, 42.0), reason="matched_repeated",
                kept_due_to_ambiguity=False, note=None,
            ),
            m.RemovalEntry(
                id=m.removal_entry_id(page=1, element_type="running_header",
                                       segment_ids=["h2"]),
                page=1, element_type="running_header", text_excerpt="Master Services Agreement",
                bbox=None, reason="matched_repeated", kept_due_to_ambiguity=True,
                note="also appears as body content",
            ),
        ],
    )
    assert_valid(json.loads(log.model_dump_json()), schema)


def test_removal_log_entries_preserve_given_order():
    m = _model()
    log = m.RemovalLog(
        **_ENV,
        entries=[
            m.RemovalEntry(id="rm-b", page=2, element_type="page_number",
                            reason="matched_pattern", kept_due_to_ambiguity=False),
            m.RemovalEntry(id="rm-a", page=1, element_type="page_number",
                            reason="matched_pattern", kept_due_to_ambiguity=False),
        ],
    )
    assert [e.id for e in log.entries] == ["rm-b", "rm-a"]  # not silently sorted


def test_render_markdown_is_deterministic_and_covers_every_entry():
    m = _model()
    log = m.RemovalLog(
        **_ENV,
        entries=[
            m.RemovalEntry(id="rm-a", page=1, element_type="running_header",
                            text_excerpt="ACME CORP", reason="matched_repeated",
                            kept_due_to_ambiguity=False),
            m.RemovalEntry(id="rm-b", page=1, element_type="page_number",
                            text_excerpt="1", reason="matched_pattern",
                            kept_due_to_ambiguity=False),
        ],
    )
    first = log.render_markdown()
    second = log.render_markdown()
    assert first == second
    assert isinstance(first, str) and first
    assert "rm-a" in first and "rm-b" in first
    assert "ACME CORP" in first


def test_render_markdown_handles_an_empty_log():
    m = _model()
    log = m.RemovalLog(**_ENV, entries=[])
    out = log.render_markdown()
    assert isinstance(out, str)
    assert out  # never raises / never empty even with zero entries
