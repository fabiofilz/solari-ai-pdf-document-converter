"""Stage-3 orchestration: CED → ``SemanticDocument`` (T073).

Runs the frozen post-T070/S2-remediation pipeline in the one order that keeps every
ownership question mechanically closed instead of merely conventionally observed:

1. ``tables = build_tables(ced)`` — table ownership is determined **directly from the
   CED**, before anything else touches it (closes the "partial ReflowUnit" hazard: a
   hint-less segment geometry-absorbed into a table can never also be half-owned by a
   reflowed prose unit);
2. ``reflow(ced, excluded_segment_ids=tables.consumed_segment_ids)`` — the non-table
   reflow pass never even sees a table-owned segment;
3. ``remove_artifacts(ced, non_table_reflow)`` (T071) — conservative, evidence-based
   removal over the non-table content only, with its own removal log;
4. ``infer_structure`` (T068) and ``reconstruct_lists`` (T069) run over T071's
   **retained** units — an artifact-removed segment can never surface as a
   paragraph/heading/list/clause;
5. table blocks (T070's own, reused verbatim) and the newly-built non-table blocks are
   merged into one document, ordered by each block's own **earliest accepted-source
   index** — never by table id, never by block kind. ``StructuralReorder`` is the only
   permitted exception to that order (FR-064 / SC-023), and this module additionally
   detects and records the one remaining case T070 could not: a stitched table whose
   intervening transparent furniture (:class:`~solari_converter.transform.tables.StitchRecord`)
   survived T071 removal and now renders as separate, displaced retained content
   (FR-021).

No LLM, no network, no PDF reopening, no re-extraction. ``SemanticDocument`` is
ephemeral (research §23) — this module performs no I/O.
"""

from __future__ import annotations

from solari_converter.model.canonical import CanonicalExtractedDocument
from solari_converter.model.semantic import (
    Block,
    ClauseBlock,
    HeadingBlock,
    ListBlock,
    ListItemEntry,
    ParagraphBlock,
    SemanticDocument,
    block_id,
)
from solari_converter.transform.artifacts import remove_artifacts
from solari_converter.transform.lists import ClauseNode, ListItemNode, reconstruct_lists
from solari_converter.transform.reflow import ReflowResult, reflow
from solari_converter.transform.structure import infer_structure
from solari_converter.transform.tables import StructuralReorder, TableBlock, build_tables

__all__ = ["build_semantic"]


def build_semantic(ced: CanonicalExtractedDocument) -> SemanticDocument:
    """Deterministically build the Stage-3 ``SemanticDocument`` from ``ced``."""
    tables_result = build_tables(ced)

    non_table_reflow = reflow(
        ced, excluded_segment_ids=tables_result.consumed_segment_ids
    )
    artifact_result = remove_artifacts(ced, non_table_reflow)
    kept_reflow = ReflowResult(
        units=artifact_result.kept_units,
        transforms=tuple(t for u in artifact_result.kept_units for t in u.transforms),
    )

    structure_result = infer_structure(ced, kept_reflow)
    list_result = reconstruct_lists(ced, kept_reflow)

    non_table_blocks = _assemble_non_table_blocks(structure_result, list_result)

    accepted_index = {
        sid: i for i, sid in enumerate(ced.accepted_reading_order)
    }
    all_blocks: list[Block] = [*tables_result.blocks, *non_table_blocks]
    all_blocks.sort(key=lambda b: _anchor(b, accepted_index))

    collapsed_ids = frozenset(
        sid for ch in tables_result.collapsed_headers for sid in ch.segment_ids
    )

    fr021_reorders = _fr021_reorders(
        tables_result, all_blocks, accepted_index, ced.accepted_reading_order,
        artifact_result.removed_segment_ids,
    )

    segment_transforms = (*tables_result.transforms, *kept_reflow.transforms)

    return SemanticDocument(
        blocks=tuple(all_blocks),
        structural_reorder=(*tables_result.structural_reorder, *fr021_reorders),
        segment_transforms=segment_transforms,
        removal_log=artifact_result.removal_log,
        table_owned_segment_ids=tables_result.consumed_segment_ids,
        collapsed_segment_ids=collapsed_ids,
        removed_segment_ids=artifact_result.removed_segment_ids,
    )


def _anchor(block: Block, accepted_index: dict[str, int]) -> int:
    return min(accepted_index[sid] for sid in block.provenance if sid in accepted_index)


# --- non-table block assembly ----------------------------------------------------


def _assemble_non_table_blocks(structure_result, list_result) -> list[Block]:
    """Merge T068's heading/body classification with T069's list/clause
    classification, unit-for-unit (both iterate the exact same input units in the
    exact same order — see ``structure.py`` / ``lists.py``). Precedence: a
    heading-corroborated unit is always a ``HeadingBlock``; otherwise a list-item /
    clause classification from T069 applies; otherwise it is a plain paragraph. Every
    block's ``hint_decisions`` carries **both** passes' decisions for that unit —
    FR-064 auditability is not lost merely because a hint lost precedence."""
    blocks: list[Block] = []
    list_buffer: list[tuple] = []  # (ListItemNode, hint_decisions)

    def _flush_list() -> None:
        if not list_buffer:
            return
        items = tuple(
            ListItemEntry(
                text=node.text, marker=node.marker, family=node.family,
                depth=node.depth, segment_ids=node.segment_ids,
            )
            for node, _hd in list_buffer
        )
        seg_ids = tuple(sid for node, _hd in list_buffer for sid in node.segment_ids)
        hd = tuple(h for _node, hds in list_buffer for h in hds)
        blocks.append(
            ListBlock(
                kind="list", block_id=block_id("list", seg_ids),
                ordered=list_buffer[0][0].ordered, items=items,
                provenance=seg_ids, hint_decisions=hd,
            )
        )
        list_buffer.clear()

    for s_unit, l_unit in zip(structure_result.units, list_result.units, strict=True):
        hint_decisions = tuple(s_unit.hint_decisions) + tuple(l_unit.hint_decisions)

        if s_unit.role == "heading":
            _flush_list()
            blocks.append(
                HeadingBlock(
                    kind="heading", block_id=block_id("heading", s_unit.segment_ids),
                    text=s_unit.text, level=s_unit.level or 1, deep=s_unit.deep,
                    numbering=s_unit.numbering, provenance=s_unit.segment_ids,
                    hint_decisions=hint_decisions,
                )
            )
            continue

        if isinstance(l_unit, ListItemNode):
            family_key = (l_unit.ordered, l_unit.family)
            if list_buffer and (
                list_buffer[-1][0].ordered, list_buffer[-1][0].family
            ) != family_key:
                _flush_list()
            list_buffer.append((l_unit, hint_decisions))
            continue

        _flush_list()

        if isinstance(l_unit, ClauseNode):
            blocks.append(
                ClauseBlock(
                    kind="clause", block_id=block_id("clause", l_unit.segment_ids),
                    identifier=l_unit.identifier, text=l_unit.text, depth=l_unit.depth,
                    provenance=l_unit.segment_ids, hint_decisions=hint_decisions,
                )
            )
            continue

        blocks.append(
            ParagraphBlock(
                kind="paragraph", block_id=block_id("paragraph", s_unit.segment_ids),
                text=s_unit.text, provenance=s_unit.segment_ids,
                hint_decisions=hint_decisions,
            )
        )

    _flush_list()
    return blocks


# --- FR-021 stitch-placement StructuralReorder -------------------------------------


def _fr021_reorders(
    tables_result, all_blocks: list[Block], accepted_index: dict[str, int],
    accepted_order: list[str], removed_segment_ids: frozenset[str],
) -> tuple[StructuralReorder, ...]:
    """A stitched table's intervening transparent furniture
    (:class:`~solari_converter.transform.tables.StitchRecord`) that **survived** T071
    removal now renders as its own displaced retained block. Detected purely from data
    T070 already exposes: a stitch record's ``transparent_segment_ids`` are, by
    construction, always a subset of the accepted-index span the final table
    occupies (they are exactly the ids strictly between two of its own fragments) —
    no additional T070 field is needed."""
    non_table_retained_ids = {
        sid for b in all_blocks if b.kind != "table" for sid in b.provenance
    }
    final_order_all = [sid for b in all_blocks for sid in b.provenance]

    reorders: list[StructuralReorder] = []
    for tb in tables_result.blocks:
        if not isinstance(tb, TableBlock):
            continue
        collapsed = frozenset(
            sid for ch in tables_result.collapsed_headers
            if ch.table_id == tb.table.table_id for sid in ch.segment_ids
        )
        retained_ids = [sid for sid in tb.provenance if sid not in collapsed]
        if not retained_ids:
            continue
        indices = [accepted_index[sid] for sid in retained_ids if sid in accepted_index]
        if not indices:
            continue
        lo, hi = min(indices), max(indices)

        displaced: set[str] = set()
        for sr in tables_result.stitch_records:
            for sid in sr.transparent_segment_ids:
                idx = accepted_index.get(sid)
                if idx is None or not (lo <= idx <= hi):
                    continue
                if sid in removed_segment_ids:
                    continue
                if sid in non_table_retained_ids:
                    displaced.add(sid)

        if not displaced:
            continue

        affected = set(retained_ids) | displaced
        from_order = tuple(sid for sid in accepted_order if sid in affected)
        to_order = tuple(sid for sid in final_order_all if sid in affected)
        if from_order == to_order:
            continue

        reorders.append(
            StructuralReorder(
                scope=tb.table.table_id,
                affected_segment_ids=tuple(sorted(affected)),
                from_order=from_order,
                to_order=to_order,
                reason=(
                    "a stitched logical table's intervening transparent furniture "
                    "survived artifact removal and now renders as displaced retained "
                    "content"
                ),
                permitted_by="FR-021",
            )
        )
    return tuple(reorders)
