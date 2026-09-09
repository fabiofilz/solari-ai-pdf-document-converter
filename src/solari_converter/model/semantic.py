"""``SemanticDocument`` — the ephemeral Stage-3 output (T073 / research §23).

**Not** a persisted source of truth: it is deterministically regenerable from the CED at
any time (no JSON schema, no envelope, no ``run_id`` — those belong to *persisted*
records like ``CanonicalExtractedDocument`` and ``RemovalLog``). Its assembly lives in
``transform/build_semantic.py``; this module only defines the ``Block`` union and the
document container plain dataclasses match the rest of the Stage-3 pipeline's style
(``transform/reflow.py`` / ``structure.py`` / ``lists.py`` / ``tables.py`` /
``artifacts.py``).

Every block carries ``block_id`` (stable, deterministic — content/source-lineage
derived, never uuid/time/random), ``provenance: tuple[segment_id, ...]``, and
``hint_decisions`` (FR-064 auditability). A **table** block is T070's own
:class:`~solari_converter.transform.tables.TableBlock` **reused verbatim** — this
module does not re-model or remap table identity (data-model.md's ``Table`` / ``Cell``
already live there).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from solari_converter.reports.removal_log import RemovalLog
from solari_converter.transform.reflow import HintDecision, SegmentTransform
from solari_converter.transform.tables import StructuralReorder, TableBlock

__all__ = [
    "block_id",
    "HeadingBlock",
    "ParagraphBlock",
    "ListItemEntry",
    "ListBlock",
    "ClauseBlock",
    "TableBlock",
    "Block",
    "SemanticDocument",
]


def block_id(kind: str, segment_ids: Sequence[str]) -> str:
    """Deterministic non-table block identity — ``blk-`` + a sha1 digest of the block
    kind and its **ordered** contributing source segment ids (no uuid / timestamp /
    randomness). Table blocks reuse T070's own ``blk-`` id verbatim instead — never
    remapped."""
    payload = f"{kind}:{list(segment_ids)}"
    return "blk-" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class HeadingBlock:
    kind: Literal["heading"]
    block_id: str
    text: str
    level: int
    deep: bool
    numbering: str | None
    provenance: tuple[str, ...]
    hint_decisions: tuple[HintDecision, ...] = ()


@dataclass(frozen=True)
class ParagraphBlock:
    kind: Literal["paragraph"]
    block_id: str
    text: str
    provenance: tuple[str, ...]
    hint_decisions: tuple[HintDecision, ...] = ()


@dataclass(frozen=True)
class ListItemEntry:
    """One item inside a :class:`ListBlock` — source content, never renumbered."""

    text: str
    marker: str
    family: Literal["bullet", "decimal", "alpha", "roman"]
    depth: int
    segment_ids: tuple[str, ...]


@dataclass(frozen=True)
class ListBlock:
    kind: Literal["list"]
    block_id: str
    ordered: bool
    items: tuple[ListItemEntry, ...]
    provenance: tuple[str, ...]
    hint_decisions: tuple[HintDecision, ...] = ()


@dataclass(frozen=True)
class ClauseBlock:
    kind: Literal["clause"]
    block_id: str
    identifier: str
    text: str
    depth: int
    provenance: tuple[str, ...]
    hint_decisions: tuple[HintDecision, ...] = ()


#: The discriminated Block union (data-model.md). ``TableBlock`` is T070's own type —
#: reused, not re-modelled.
Block = HeadingBlock | ParagraphBlock | ListBlock | ClauseBlock | TableBlock


@dataclass(frozen=True)
class SemanticDocument:
    """The complete Stage-3 semantic output — table + non-table blocks in accepted
    source order (StructuralReorder is the only permitted ordering exception, FR-064 /
    SC-023), plus every audit record downstream stages need without reopening this
    module."""

    blocks: tuple[Block, ...]
    structural_reorder: tuple[StructuralReorder, ...] = ()
    segment_transforms: tuple[SegmentTransform, ...] = ()
    removal_log: RemovalLog | None = None
    table_owned_segment_ids: frozenset[str] = field(default_factory=frozenset)
    collapsed_segment_ids: frozenset[str] = field(default_factory=frozenset)
    removed_segment_ids: frozenset[str] = field(default_factory=frozenset)
