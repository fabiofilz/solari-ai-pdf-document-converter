"""``ReconciliationLog`` audit-record model + Markdown renderer (T062 / M5).

The reconciliation log **is an audit record** (FR-057) — it gets the ``.json`` + ``.md``
dual emit. This module owns the pydantic model, its structural validation (summary-count
consistency, every ``unresolved[]`` entry referencing a review item), and
``render_markdown()``. The *pure assembly* of a log from decisions + unresolved items +
alignment summary lives in ``reconcile/log.py`` (no I/O); the completed log is persisted
by ``reconcile/engine.py`` (T064).

Matches ``contracts/reconciliation-log.schema.json`` (record_type ``reconciliation_log``,
schema_version ``2.0``). The exact ``model_json_schema()`` regeneration into the committed
file is T128.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AlignmentSummary",
    "LogDecision",
    "LogUnresolved",
    "LogSummary",
    "ReconciliationLog",
]

_METHODS = ("deterministic_agreement", "llm_selected", "human_confirmed")
_REASONS = ("below_threshold", "guard_rejected", "llm_flip", "no_llm")


class AlignmentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groups: int = Field(ge=0)
    single_candidate_groups: int = Field(ge=0)
    iou_threshold: float = Field(ge=0, le=1)
    jaccard_threshold: float = Field(ge=0, le=1)


class LogRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    bbox: tuple[float, float, float, float] | None = None
    region_bboxes: list[tuple[float, float, float, float]] | None = None


class LogCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    technique: str = Field(min_length=1)
    value: str | None = None
    order: list[str] | None = None
    ocr_confidence: float | None = None


class LogFlipCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calls: Literal[2] = 2
    agreed: bool


class LogDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    conflict_type: Literal["literal_content", "reading_order"]
    scope: LogRegion
    candidates: list[LogCandidate] = Field(min_length=1)
    method: Literal["deterministic_agreement", "llm_selected", "human_confirmed"]
    selected: dict[str, Any]
    confidence: float | None = Field(default=None, ge=0, le=1)
    llm_flip_check: LogFlipCheck | None = None
    resolution_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    replayed: bool | None = None


class LogUnresolved(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    conflict_type: Literal["literal_content", "reading_order"]
    reason: Literal["below_threshold", "guard_rejected", "llm_flip", "no_llm"]
    review_item_id: str = Field(min_length=1)


class LogSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    literal_deterministic: int = Field(ge=0)
    literal_llm: int = Field(ge=0)
    literal_human: int = Field(ge=0)
    order_deterministic: int = Field(ge=0)
    order_llm: int = Field(ge=0)
    order_human: int = Field(ge=0)
    unresolved: int = Field(ge=0)


class ReconciliationLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # --- envelope ---
    record_type: Literal["reconciliation_log"] = "reconciliation_log"
    schema_version: Literal["2.0"] = "2.0"
    run_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    tool_version: str = Field(min_length=1)
    source_pdf: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_selection: str = Field(min_length=1)
    # --- body ---
    alignment_summary: AlignmentSummary
    decisions: list[LogDecision] = Field(default_factory=list)
    unresolved: list[LogUnresolved] = Field(default_factory=list)
    summary: LogSummary

    @model_validator(mode="after")
    def _counts_are_consistent(self) -> ReconciliationLog:
        want = {k: 0 for k in _summary_keys()}
        for d in self.decisions:
            kind = "literal" if d.conflict_type == "literal_content" else "order"
            bucket = {
                "deterministic_agreement": "deterministic",
                "llm_selected": "llm",
                "human_confirmed": "human",
            }[d.method]
            want[f"{kind}_{bucket}"] += 1
        want["unresolved"] = len(self.unresolved)
        got = self.summary.model_dump()
        if got != want:
            raise ValueError(f"reconciliation-log summary {got} does not match decisions {want}")
        return self

    def render_markdown(self) -> str:
        s = self.summary
        out = [
            f"# Reconciliation log — run `{self.run_id}`",
            "",
            f"- source: `{self.source_pdf}` (`{self.source_sha256[:12]}…`)",
            f"- pages: `{self.page_selection}`",
            f"- alignment: {self.alignment_summary.groups} group(s), "
            f"{self.alignment_summary.single_candidate_groups} single-candidate; "
            f"IoU ≥ {self.alignment_summary.iou_threshold}, "
            f"Jaccard tie-break {self.alignment_summary.jaccard_threshold}",
            "",
            "## Summary",
            "",
            "| literal det | literal llm | literal human | order det | order llm "
            "| order human | unresolved |",
            "|---|---|---|---|---|---|---|",
            f"| {s.literal_deterministic} | {s.literal_llm} | {s.literal_human} "
            f"| {s.order_deterministic} | {s.order_llm} | {s.order_human} | {s.unresolved} |",
            "",
        ]
        nontrivial = [d for d in self.decisions if _is_nontrivial(d)]
        if nontrivial:
            out += ["## Decisions (non-trivial)", ""]
            for d in nontrivial:
                out.append(
                    f"- `{d.decision_id}` · {d.conflict_type} · **{d.method}**"
                    + (" · replayed" if d.replayed else "")
                    + (f" · confidence {d.confidence}" if d.confidence is not None else "")
                )
                if d.method != "deterministic_agreement" or _distinct_values(d):
                    for c in d.candidates:
                        shown = c.value if c.value is not None else c.order
                        out.append(f"  - `{c.technique}`: {shown!r}")
                sel = d.selected.get("value", d.selected.get("order"))
                out.append(f"  - selected: {sel!r} (from `{d.selected.get('from', '?')}`)")
            out.append("")
        if self.unresolved:
            out += ["## Unresolved → Human Review", ""]
            for u in self.unresolved:
                out.append(
                    f"- `{u.decision_id}` · {u.conflict_type} · **{u.reason}** "
                    f"→ item `{u.review_item_id}`"
                )
            out.append("")
        return "\n".join(out).rstrip() + "\n"


def _summary_keys() -> tuple[str, ...]:
    return (
        "literal_deterministic", "literal_llm", "literal_human",
        "order_deterministic", "order_llm", "order_human", "unresolved",
    )


def _distinct_values(d: LogDecision) -> bool:
    vals = {c.value for c in d.candidates if c.value is not None}
    orders = {tuple(c.order) for c in d.candidates if c.order is not None}
    return len(vals) > 1 or len(orders) > 1


def _is_nontrivial(d: LogDecision) -> bool:
    """Show a decision's candidate detail only when it is audit-interesting (block
    brief §13): LLM-selected, human-confirmed / replayed, or a deterministic decision
    over genuinely distinct (non-material) candidate values."""
    return d.method != "deterministic_agreement" or _distinct_values(d)
