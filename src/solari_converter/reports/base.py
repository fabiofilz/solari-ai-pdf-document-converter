"""Persisted-record envelope base (T028).

Every persisted record (data-model.md — *Common envelope*) carries exactly these seven
fields and **nothing time- or randomness-derived** (FR-053a): the record body is a pure
function of the inputs, so an unchanged re-run is a byte-identical no-op rather than a
collision. ``run_id`` is defined authoritatively in research §14 (``run_identity`` — T025);
this module never recomputes it.

* ``render_markdown()`` — the FR-057 dual-emit hook. **Audit records** (reconciliation log,
  removal log, validation report, correction log, traceability record, the Human Review
  records) override it; extraction candidates and the CED do not (M1 — JSON is their sole
  authoritative representation, ``artifacts_io.write_record(..., emit_md=False)``).
* ``json_schema()`` — the committed-schema comparison helper the T015 drift guard / the
  T128 generator use.

Existing Phase-3 record models (``ExtractionCandidate`` — T020, ``CanonicalExtractedDocument``
— T022, the Human Review models — T024) currently declare the envelope fields inline; they
are aligned onto this base by the schema-generation consolidation (T128) rather than in this
tranche.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["RecordEnvelope"]

_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"


class RecordEnvelope(BaseModel):
    """Common envelope for every persisted record."""

    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(description="discriminant — set by each subclass")
    schema_version: str = Field(default="2.0", description='"2.0" | "2.1" — set by each subclass')
    run_id: str = Field(pattern=r"^[a-f0-9]{16}$",
                        description="research §14 (authoritative); no wall-clock, no randomness")
    tool_version: str = Field(min_length=1, description="human-readable; also a run_id input")
    source_pdf: str = Field(min_length=1, description="filename only")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_selection: str = Field(min_length=1, description="canonical selector token, or 'all'")

    # --- FR-057 dual-emit hook -------------------------------------------------

    def render_markdown(self) -> str:
        """Human-readable rendering for the ``.md`` companion of an audit record. The base
        raises — a record that gets a dual emit MUST override this; a JSON-only record
        (candidate / CED — M1) simply never calls it."""
        raise NotImplementedError(
            f"{type(self).__name__} has no Markdown rendering — either it is a JSON-only "
            "record (M1) or its renderer task has not landed yet"
        )

    # --- schema helper ------------------------------------------------------

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        """``model_json_schema()`` with the draft-2020-12 ``$schema`` key, for comparison
        against the committed ``contracts/*.schema.json`` (T015 / T128)."""
        schema = cls.model_json_schema()
        schema.setdefault("$schema", _DRAFT_2020_12)
        return schema
