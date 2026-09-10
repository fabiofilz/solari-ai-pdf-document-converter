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

__all__ = [
    "build_semantic",
    "literal_accounting_violations",
    "accepted_partition_violations",
    "LiteralAccountingError",
    "AcceptedPartitionError",
]

#: The one line-boundary hyphen a ``dehyphenate`` transform is allowed to drop (§27).
_HYPHEN = "-"


class LiteralAccountingError(ValueError):
    """Raised when the R8 literal-level fidelity invariant is violated — a source
    segment is nominally retained (its id sits in a block's provenance, and it is
    neither collapsed nor artifact-removed) yet its **exact** stored literal has no
    representation in the rendered-semantic content and no permitted line-boundary
    transform accounts for the delta. This is the R1 class of defect; it must never
    pass unnoticed."""


class AcceptedPartitionError(ValueError):
    """Raised when the R8 accepted-ID partition invariant is violated — some accepted
    CED segment id is not in exactly one terminal ownership state (retained /
    collapsed / removed), or the three sets are not pairwise disjoint, or their union
    is not exactly the accepted-id set."""


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

    semantic = SemanticDocument(
        blocks=tuple(all_blocks),
        structural_reorder=(*tables_result.structural_reorder, *fr021_reorders),
        segment_transforms=segment_transforms,
        removal_log=artifact_result.removal_log,
        table_owned_segment_ids=tables_result.consumed_segment_ids,
        collapsed_segment_ids=collapsed_ids,
        removed_segment_ids=artifact_result.removed_segment_ids,
        collapsed_headers=tuple(tables_result.collapsed_headers),
    )

    # R8-A — the accepted-ID partition invariant (retained ⊎ collapsed ⊎ removed ==
    # accepted, pairwise disjoint), enforced at runtime in the semantic build, not
    # tests only.
    partition = accepted_partition_violations(semantic, ced)
    if partition:
        raise AcceptedPartitionError(
            "accepted-ID terminal-ownership partition violated: "
            + "; ".join(f"{k}={v}" for k, v in sorted(partition.items()))
        )

    # R8-B/C/D — the exact literal-level fidelity invariant, enforced at the semantic
    # boundary so the R1 class of silent literal mutation / disappearance can never
    # pass unnoticed.
    offenders = literal_accounting_violations(semantic, ced)
    if offenders:
        raise LiteralAccountingError(
            "retained-in-provenance source segments whose exact literal has no "
            f"rendered representation and no permitted transform: {offenders}"
        )
    return semantic


# --- R8: exact literal-level semantic accounting invariants -------------------------


def _carrier_units(block: Block) -> list[tuple[str, tuple[str, ...]]]:
    """``(rendered-text, contributing-segment-ids)`` pairs for one block — the units
    whose text must still carry each of their provenance segments' **exact** literals."""
    if block.kind == "table":
        return [
            (c.text, c.provenance)
            for row in block.table.rows for c in row if c.provenance
        ]
    if block.kind == "list":
        return [(it.text, it.segment_ids) for it in block.items]
    return [(block.text, block.provenance)]  # heading / paragraph / clause


def _retained_ids(semantic: SemanticDocument) -> set[str]:
    return (
        {sid for b in semantic.blocks for sid in b.provenance}
        - set(semantic.collapsed_segment_ids)
        - set(semantic.removed_segment_ids)
    )


def _dehyphenation_pairs(
    semantic: SemanticDocument,
) -> list[tuple[str, str]]:
    """``(left_id, right_id)`` for every recorded ``dehyphenate`` transform. ``reflow``
    builds the transform's ``segment_ids`` as ``(*unit_ids_so_far, right_id)`` with
    ``joined_with == right_id``, so the hyphen-dropped *left* segment is the
    second-to-last id and the *right* segment is the last (== ``joined_with``)."""
    pairs: list[tuple[str, str]] = []
    for t in semantic.segment_transforms:
        if t.kind != "dehyphenate" or len(t.segment_ids) < 2:
            continue
        pairs.append((t.segment_ids[-2], t.joined_with or t.segment_ids[-1]))
    return pairs


def accepted_partition_violations(
    semantic: SemanticDocument, ced: CanonicalExtractedDocument
) -> dict[str, list[str]]:
    """R8-A. Every accepted CED segment id must be in **exactly one** terminal
    ownership state — ``retained`` (id in some block provenance, not collapsed, not
    removed), ``collapsed`` (``collapsed_segment_ids``), or ``removed``
    (``removed_segment_ids``) — the three sets pairwise disjoint and unioning to
    exactly the accepted-id set.

    Returns a dict of non-empty violation categories (``absent`` /
    ``retained_and_collapsed`` / ``retained_and_removed`` / ``collapsed_and_removed``
    / ``not_accepted``), each a sorted id list; an empty dict ⇒ the partition holds.
    """
    accepted = set(ced.accepted_reading_order)
    collapsed = set(semantic.collapsed_segment_ids)
    removed = set(semantic.removed_segment_ids)
    in_provenance = {sid for b in semantic.blocks for sid in b.provenance}
    retained = in_provenance - collapsed - removed

    out: dict[str, list[str]] = {}
    absent = accepted - retained - collapsed - removed
    if absent:
        out["absent"] = sorted(absent)
    if retained & collapsed:
        out["retained_and_collapsed"] = sorted(retained & collapsed)
    if retained & removed:
        out["retained_and_removed"] = sorted(retained & removed)
    if collapsed & removed:
        out["collapsed_and_removed"] = sorted(collapsed & removed)
    not_accepted = (retained | collapsed | removed) - accepted
    if not_accepted:
        out["not_accepted"] = sorted(not_accepted)
    return out


def literal_accounting_violations(
    semantic: SemanticDocument, ced: CanonicalExtractedDocument
) -> list[str]:
    """The R8 **exact** literal-fidelity invariant — strictly stronger than the
    set-level ``retained ⊎ collapsed ⊎ removed == accepted`` and stronger than the
    previous comparison-key-equivalence check (R8: comparison normalisation may be
    used for diagnostics, never to prove delivered fidelity).

    **Invariant.** For every *nominally retained* accepted segment ``s`` (id in some
    block's ``provenance``; not collapsed; not removed):

    * **B.** If no literal-changing permitted transform applies to ``s``, its stored
      CED literal MUST appear **verbatim** (codepoint-exact — no casefold, no
      smart-quote fold, no punctuation or numeric-format change, no whitespace
      normalisation) as a substring of some carrier unit (paragraph / heading /
      clause / list item / table cell) that names ``s`` in provenance. ``reflow`` and
      the table wrapped-line join only ever insert a separator *between* two literals,
      so an unmodified segment's own characters survive intact.
    * **C.** If ``s`` is the *left* participant of a recorded ``dehyphenate``
      transform (with right participant ``r``), the single permitted boundary
      mutation is the drop of ``s``'s trailing ``U+002D``: ``s.text`` MUST end with
      ``-`` and ``s.text[:-1] + r.text`` MUST appear verbatim in a carrier naming
      both. Merely appearing in a ``dehyphenate`` record exempts nothing — an
      arbitrary replacement (``abcdef`` → ``TOTAL REPLACEMENT``) still fails. The
      *right* participant keeps every character and is checked by rule B.
    * **D.** Collapsed and removed segments are out of scope here **only** because
      they carry their own explicit lineage (``CollapsedHeader`` / ``RemovalLog``);
      provenance membership alone is never treated as sufficient.

    Returns the sorted list of offending segment ids; empty ⇒ the invariant holds.
    """
    ced_text = {s.segment_id: s.text for s in ced.accepted_segments}

    carriers: dict[str, list[str]] = {}
    for b in semantic.blocks:
        for text, prov in _carrier_units(b):
            for sid in prov:
                carriers.setdefault(sid, []).append(text)

    dehyph_pairs = _dehyphenation_pairs(semantic)
    dehyph_left = {left for left, _r in dehyph_pairs}

    retained = _retained_ids(semantic)

    violations: list[str] = []
    for sid in sorted(retained):
        literal = ced_text.get(sid, "")
        if literal == "" or literal.strip() == "":
            continue  # an empty / whitespace-only literal contributes no characters
        my_carriers = carriers.get(sid, [])

        if sid in dehyph_left:
            # C: validate the exact allowed line-boundary mutation.
            ok = False
            for left, right in dehyph_pairs:
                if left != sid or not literal.endswith(_HYPHEN):
                    continue
                expected = literal[:-1] + ced_text.get(right, "")
                if any(expected in c for c in my_carriers):
                    ok = True
                    break
            if ok:
                continue
            violations.append(sid)
            continue

        # B: verbatim (codepoint-exact) contribution required.
        if any(literal in c for c in my_carriers):
            continue
        violations.append(sid)
    return violations


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
