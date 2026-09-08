"""Reconciliation non-rewrite guard (T033).

The **hard programmatic safety boundary** for LLM-assisted reconciliation (research §21d,
FR-061a / FR-061b, SC-020). It is deterministic and pure — it holds regardless of whether
the LLM response looks reasonable:

* :func:`guard_literal` accepts an LLM-selected literal **only** when it is byte-identical
  to one of the source-backed candidate values allowed by the reconciliation decision;
* :func:`guard_order` accepts an LLM-selected reading order **only** when it exactly equals
  one of the candidate reading orders or the explicitly permitted geometry-derived order;
* the guard never trims, case-folds, normalises Unicode, rewrites line endings, collapses
  whitespace, normalises punctuation, repairs spelling / OCR, infers missing text,
  combines, splits, or re-sorts — a near-miss is **rejected**, not repaired.

A rejection returns :class:`GuardReject` with ``outcome == HUMAN_REVIEW_REQUIRED`` and
``resolved is False``: the conflict stays unresolved and is routed to Human Review. This
module does **not** implement the Human Review workflow.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "HUMAN_REVIEW_REQUIRED",
    "GuardAccept",
    "GuardReject",
    "guard_literal",
    "guard_order",
]

# The frozen unresolved-conflict signal (FR-061b). A guard rejection ultimately requires
# Human Review; the state string matches spec / research usage.
HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"

_ConflictType = Literal["literal_content", "reading_order"]


@dataclass(frozen=True)
class GuardAccept:
    """The LLM selection is a valid, source-backed choice."""

    conflict_type: _ConflictType
    value: str | None = None
    order: list[str] | None = None
    resolved: bool = True


@dataclass(frozen=True)
class GuardReject:
    """The LLM selection is not an exact source-backed choice — the conflict stays
    unresolved and must go to Human Review (FR-061b)."""

    conflict_type: _ConflictType
    reason: str
    selected: object
    outcome: str = HUMAN_REVIEW_REQUIRED
    resolved: bool = False


def guard_literal(
    *,
    selected_value: str,
    candidate_values: Iterable[str],
) -> GuardAccept | GuardReject:
    """Accept ``selected_value`` **only** if it is byte-identical (Python ``==`` on the
    ``str``, i.e. identical Unicode code points) to one of ``candidate_values``. No
    trimming, case-folding, Unicode normalisation, whitespace collapsing, or punctuation
    normalisation is applied."""
    candidates = list(candidate_values)
    for cand in candidates:
        if isinstance(cand, str) and cand == selected_value:
            return GuardAccept(conflict_type="literal_content", value=cand)
    return GuardReject(
        conflict_type="literal_content",
        reason=(
            "selected literal is not byte-identical to any source-backed candidate value"
        ),
        selected=selected_value,
    )


def guard_order(
    *,
    selected_order: Sequence[str],
    candidate_orders: Iterable[Sequence[str]],
    geometry_order: Sequence[str] | None = None,
) -> GuardAccept | GuardReject:
    """Accept ``selected_order`` **only** if it exactly equals one of ``candidate_orders``
    or the explicitly permitted ``geometry_order``. The guard never re-sorts a rejected
    order to "fix" it."""
    selected = list(selected_order)
    allowed: list[list[str]] = [list(o) for o in candidate_orders]
    if geometry_order is not None:
        allowed.append(list(geometry_order))
    if selected in allowed:
        return GuardAccept(conflict_type="reading_order", order=selected)
    return GuardReject(
        conflict_type="reading_order",
        reason=(
            "selected reading order is neither a candidate order nor the "
            "geometry-supported order"
        ),
        selected=selected,
    )
