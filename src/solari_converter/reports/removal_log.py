"""``RemovalLog`` audit-record model + Markdown renderer (T072 / FR-011).

The removal log **is an audit record** (FR-057) — it gets the ``.json`` + ``.md`` dual
emit. This module owns the pydantic model and ``render_markdown()``. The *detection* of
what to remove — running headers/footers, page numbers, watermarks, authentication
artifacts — is ``transform/artifacts.py`` (T071); this module is the persisted record it
writes into, matching ``contracts/removal-log.schema.json`` (record_type ``removal_log``,
schema_version ``2.0``) field-for-field. The exact ``model_json_schema()`` regeneration
into the committed file remains T128's job — this module does not touch the committed
schema.

FR-011 requires every entry to identify *what* was removed and *from which source page*;
SC-004 requires 100% of stage-3 removed elements to appear here. The committed schema has
no ``segment_ids`` field (M1-style JSON-only minimalism) — ``entry_type`` /
``ambiguous`` below are **read-only, non-serialized** convenience properties for callers
that spell the concepts differently; they never appear in ``model_dump()`` /
``model_dump_json()`` and are not part of the schema contract. Richer in-memory
segment-id lineage for a removed entry, when T073's source-accounting needs it, is kept
by ``transform/artifacts.py`` alongside the ``RemovalLog`` it returns — never folded into
the committed schema.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ElementType", "RemovalReason", "RemovalEntry", "RemovalLog", "removal_entry_id"]

ElementType = Literal[
    "running_header", "running_footer", "page_number", "watermark", "background",
    "auth_stamp", "barcode", "qr_code", "vertical_auth_text", "other",
]

RemovalReason = Literal["matched_repeated", "matched_pattern", "classifier"]


def removal_entry_id(
    *, page: int, element_type: str, segment_ids: list[str] | tuple[str, ...],
) -> str:
    """The deterministic ``rm-`` + 12-hex-digest entry id (content-derived — no uuid,
    no wall-clock timestamp, no randomness, FR-053a). Order-independent in
    ``segment_ids``: the digest input sorts them first."""
    payload = f"{page}:{element_type}:{sorted(segment_ids)}"
    return "rm-" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


class RemovalEntry(BaseModel):
    """One removed (or ambiguously-kept) element. Matches ``entries[]`` in the committed
    schema exactly — every serialized field name is a schema name."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    page: int = Field(ge=1)
    element_type: ElementType
    text_excerpt: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    reason: RemovalReason
    kept_due_to_ambiguity: bool = False
    note: str | None = None

    @property
    def entry_type(self) -> ElementType:
        """Read-only alias for ``element_type`` — not a serialized field."""
        return self.element_type

    @property
    def ambiguous(self) -> bool:
        """Read-only alias for ``kept_due_to_ambiguity`` — not a serialized field."""
        return self.kept_due_to_ambiguity


class RemovalLog(BaseModel):
    """The FR-011 removal log. Matches ``contracts/removal-log.schema.json``."""

    model_config = ConfigDict(extra="forbid")

    # --- envelope ---
    record_type: Literal["removal_log"] = "removal_log"
    schema_version: Literal["2.0"] = "2.0"
    run_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    tool_version: str = Field(min_length=1)
    source_pdf: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_selection: str = Field(min_length=1)
    # --- body ---
    entries: list[RemovalEntry] = Field(default_factory=list)

    def render_markdown(self) -> str:
        """FR-057 human-readable companion. Deterministic: entries render in the exact
        order given (never resorted), and nothing here depends on wall-clock time,
        randomness, or dict/set iteration order."""
        kept = sum(1 for e in self.entries if e.kept_due_to_ambiguity)
        out = [
            f"# Removal log — run `{self.run_id}`",
            "",
            f"- source: `{self.source_pdf}` (`{self.source_sha256[:12]}…`)",
            f"- pages: `{self.page_selection}`",
            f"- {len(self.entries)} entrie(s); {kept} kept due to ambiguity",
            "",
        ]
        if self.entries:
            out += [
                "| id | page | element type | reason | kept (ambiguous) | excerpt |",
                "|---|---|---|---|---|---|",
            ]
            for e in self.entries:
                excerpt = (e.text_excerpt or "").replace("|", "\\|")
                out.append(
                    f"| `{e.id}` | {e.page} | {e.element_type} | {e.reason} "
                    f"| {e.kept_due_to_ambiguity} | {excerpt} |"
                )
            out.append("")
        return "\n".join(out)
