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
from solari_converter.transform.reflow import (
    WRAPPED_LINE_JOIN,
    ReflowResult,
    SegmentTransform,
    reflow,
)
from solari_converter.transform.reflow import (
    _line_break_hyphen_fragment as _hyphen_fragment,  # the exact §27 predicate reflow uses
)
from solari_converter.transform.structure import infer_structure
from solari_converter.transform.tables import StructuralReorder, TableBlock, build_tables

__all__ = [
    "build_semantic",
    "literal_accounting_violations",
    "accepted_partition_violations",
    "authenticated_dehyphenations",
    "LiteralAccountingError",
    "AcceptedPartitionError",
]

#: The one line-boundary hyphen a ``dehyphenate`` transform is allowed to drop (§27).
_HYPHEN = "-"

#: The frozen requirement id a ``dehyphenate`` :class:`SegmentTransform` must name.
_DEHYPHENATE_RULE = "FR-014"
#: The Stage-3 semantic stage a dehyphenation may occur in.
_DEHYPHENATE_STAGE = 3


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
    artifact_result = remove_artifacts(
        ced, non_table_reflow,
        rejected_table_segment_ids=tables_result.rejected_table_segment_ids,
    )
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
        table_identical_evidence_groups=tables_result.identical_evidence_groups,
        rejected_table_segment_ids=tables_result.rejected_table_segment_ids,
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
    whose text must still carry each of their provenance segments' **exact** literals.

    A *carrier* is the smallest content-owning unit: one paragraph / heading / clause,
    one list item, one **table cell** — never the outer ``TableBlock``. Each carries
    its own ordered provenance."""
    if block.kind == "table":
        return [
            (c.text, c.provenance)
            for row in block.table.rows for c in row if c.provenance
        ]
    if block.kind == "list":
        return [(it.text, it.segment_ids) for it in block.items]
    return [(block.text, block.provenance)]  # heading / paragraph / clause


def _ced_literals(ced: CanonicalExtractedDocument) -> dict[str, str]:
    return {s.segment_id: s.text for s in ced.accepted_segments}


def _raw_owned_ids(semantic: SemanticDocument) -> set[str]:
    """B3 — the **raw** content-ownership set: the union of every semantic carrier's
    own ordered provenance (prose / heading / clause / list-item provenance and table
    **cell** provenance). NOT the outer ``TableBlock.provenance`` (which also carries
    collapsed-header lineage). Nothing is subtracted — an id that is here *and* also
    collapsed / removed is exactly the overlap the partition invariant must surface."""
    return {
        sid
        for b in semantic.blocks
        for _text, prov in _carrier_units(b)
        for sid in prov
    }


def accepted_partition_violations(
    semantic: SemanticDocument, ced: CanonicalExtractedDocument
) -> dict[str, list[str]]:
    """R8-A / B3. Every accepted CED segment id must be in **exactly one** terminal
    ownership state:

    * ``raw_retained`` — id owned by a renderable carrier (prose / heading / clause /
      list-item provenance, or a **table cell**'s provenance — never the outer
      ``TableBlock.provenance``);
    * ``collapsed`` — ``collapsed_segment_ids``;
    * ``removed`` — ``removed_segment_ids``.

    The three are obtained **independently** (nothing subtracted before the checks) so
    an overlap cannot be hidden. Enforced: ``raw_retained ∩ collapsed == ∅``,
    ``raw_retained ∩ removed == ∅``, ``collapsed ∩ removed == ∅``,
    ``raw_retained ∪ collapsed ∪ removed == accepted``, and no terminal id outside
    ``accepted``.

    Returns a dict of non-empty violation categories (``absent`` /
    ``retained_and_collapsed`` / ``retained_and_removed`` / ``collapsed_and_removed``
    / ``not_accepted``), each a sorted id list; an empty dict ⇒ the partition holds.
    """
    accepted = set(ced.accepted_reading_order)
    collapsed = set(semantic.collapsed_segment_ids)
    removed = set(semantic.removed_segment_ids)
    raw_retained = _raw_owned_ids(semantic)

    out: dict[str, list[str]] = {}
    if raw_retained & collapsed:
        out["retained_and_collapsed"] = sorted(raw_retained & collapsed)
    if raw_retained & removed:
        out["retained_and_removed"] = sorted(raw_retained & removed)
    if collapsed & removed:
        out["collapsed_and_removed"] = sorted(collapsed & removed)
    union = raw_retained | collapsed | removed
    absent = accepted - union
    if absent:
        out["absent"] = sorted(absent)
    not_accepted = union - accepted
    if not_accepted:
        out["not_accepted"] = sorted(not_accepted)
    return out


def literal_accounting_violations(
    semantic: SemanticDocument, ced: CanonicalExtractedDocument
) -> list[str]:
    """The R8 / B1 **exact complete-carrier reconstruction** invariant.

    Substring accounting ("each source literal occurs *somewhere* in a carrier naming
    that id") is not fidelity — it lets ``abc`` → ``xabcx`` pass, lets one segment's
    substring satisfy another's contribution, lets a duplicate collapse to one
    occurrence, and lets unrelated text be inserted around a literal.

    Instead, for **every semantic carrier** — one paragraph / heading / clause, one
    list item, one **table cell** (never the outer table block) — the expected carrier
    text is *reconstructed* from:

    1. the carrier's own ordered provenance segment ids;
    2. those segments' exact CED literals (every codepoint preserved, source order
       kept);
    3. the exact ordered permitted boundary transforms that apply to *those* ids:

       * ``dehyphenate`` (:func:`_dehyphenate_participants`, B2) — the **only**
         permitted literal mutation: drop the left literal's single trailing
         ``U+002D`` at the join with its named right participant. Every frozen
         contract field is validated first (rule ``FR-014``, stage 3, named adjacent
         participants in source order, left literal actually ends in ``U+002D``);
       * ``reflow_whitespace`` / the deterministic default — a single
         ``WRAPPED_LINE_JOIN`` space *between* two literals, suppressed only when the
         accumulated text ends in a genuine §27 line-break hyphen fragment (the exact
         predicate ``reflow`` itself uses).

    The reconstructed text must equal the carrier's rendered text **exactly**. No
    unrecorded prefix / suffix / interior insertion passes; no occurrence satisfies
    two source contributions; a duplicated literal needs two rendered copies **unless**
    the current carrier is the exact retained table cell into which T070 collapsed
    byte-identical evidence and that group authenticates against the real cell
    (:func:`_authenticated_ident_groups`, B1) — the one narrow, cell-local,
    provenance-authenticated exception. It is impossible in a paragraph / heading /
    clause / list item, cannot span cells, and cannot be borrowed from
    ``table_identical_evidence_groups`` alone.

    On a carrier mismatch, blame is attributed per segment by ordered substring
    alignment of each segment's own delivered contribution; an insertion/reorder that
    leaves every literal individually present still implicates the whole carrier.

    Returns the sorted list of offending segment ids; empty ⇒ the invariant holds.
    """
    ced_text = _ced_literals(ced)

    tx_by_right: dict[str, list[SegmentTransform]] = {}
    for t in semantic.segment_transforms:
        if t.joined_with:
            tx_by_right.setdefault(t.joined_with, []).append(t)

    # B1 — the identical-evidence exception is authenticated against the *actual*
    # retained table cells, never trusted from ``table_identical_evidence_groups``
    # alone: a group is usable only when a real rendered table cell owns exactly it,
    # its literals are codepoint-identical, T070 recorded it, and no other semantic
    # carrier owns any member (see :func:`_authenticated_ident_groups`).
    recorded_ident = tuple(
        frozenset(g) for g in semantic.table_identical_evidence_groups
    )
    authentic_ident = _authenticated_ident_groups(semantic, ced)

    carriers = [
        (b.kind == "table", tuple(prov), text)
        for b in semantic.blocks
        for text, prov in _carrier_units(b)
        if prov
    ]

    violations: set[str] = set()
    for is_table, prov, text in carriers:
        violations |= _carrier_violations(
            text, prov, is_table, ced_text, tx_by_right, authentic_ident
        )

    # B1 — a recorded identical-evidence group that does not authenticate against a
    # real retained table cell is fabricated lineage on its own, even if no carrier
    # tried to use it.
    for g in recorded_ident:
        if g not in authentic_ident:
            violations |= {s for s in g if s in ced_text} or set(g)

    # B2 — a ``dehyphenate`` record whose named participants are not exactly one
    # carrier's ordered provenance prefix through the joined-right segment — or that is
    # otherwise malformed, carries duplicate ids, or conflicts with another
    # dehyphenate record on the same boundary / ``joined_with`` — is a violation on its
    # own, even when some carrier's text coincidentally matches.
    carrier_prov = [prov for _t, prov, _x in carriers]
    deh_transforms = [
        t for t in semantic.segment_transforms if t.kind == "dehyphenate"
    ]
    joined_counts: dict[str, int] = {}
    boundary_counts: dict[tuple[str, str], int] = {}
    for t in deh_transforms:
        sids = tuple(t.segment_ids or ())
        if t.joined_with:
            joined_counts[t.joined_with] = joined_counts.get(t.joined_with, 0) + 1
        if len(sids) >= 2:
            key = (sids[-2], sids[-1])
            boundary_counts[key] = boundary_counts.get(key, 0) + 1
    for t in deh_transforms:
        sids = tuple(t.segment_ids or ())
        violations |= _malformed_dehyphenate(t, carrier_prov, ced_text)
        if (t.joined_with and joined_counts.get(t.joined_with, 0) > 1) or (
            len(sids) >= 2 and boundary_counts.get((sids[-2], sids[-1]), 0) > 1
        ):
            violations |= {s for s in sids if s in ced_text}

    return sorted(violations)


def _authenticated_ident_groups(
    semantic: SemanticDocument, ced: CanonicalExtractedDocument
) -> set[frozenset[str]]:
    """B1 — the set of identical-evidence groups that may authorise one rendered
    literal standing for several provenance ids **in the exact table cell that
    generated the collapse**.

    A group qualifies only when a real retained :class:`TableCell` in
    ``semantic.blocks`` has provenance whose id set is *exactly* that group and:

    * the cell holds at least two **distinct** accepted CED segment ids;
    * every one of those ids' stored CED literals is codepoint-identical, and the
      cell's rendered text equals that shared literal;
    * no id in the group belongs to any other semantic carrier (prose / heading /
      clause / list-item provenance or another table cell);
    * no id in the group is a rejected-table fragment id;
    * T070 actually recorded the group in ``table_identical_evidence_groups``
      (genuine same-anchor identical-evidence lineage, not a hand-injected set).

    The exception is therefore impossible outside a table cell, cannot span cells,
    and cannot be borrowed by a paragraph / heading / clause / list item.
    """
    ced_text = _ced_literals(ced)
    accepted = set(ced.accepted_reading_order)
    recorded = {frozenset(g) for g in semantic.table_identical_evidence_groups}
    rejected = set(semantic.rejected_table_segment_ids)

    owner_count: dict[str, int] = {}
    for b in semantic.blocks:
        for _text, prov in _carrier_units(b):
            for sid in set(prov):
                owner_count[sid] = owner_count.get(sid, 0) + 1

    authentic: set[frozenset[str]] = set()
    for b in semantic.blocks:
        if b.kind != "table":
            continue
        for row in b.table.rows:
            for c in row:
                prov = tuple(c.provenance)
                uniq = set(prov)
                if len(prov) < 2 or len(uniq) < 2:
                    continue
                if not uniq <= accepted:
                    continue
                lits = {ced_text.get(s) for s in uniq}
                if len(lits) != 1 or None in lits:
                    continue
                if c.text != next(iter(lits)):
                    continue
                if uniq & rejected:
                    continue
                if any(owner_count.get(s, 0) != 1 for s in uniq):
                    continue
                g = frozenset(uniq)
                if g in recorded:
                    authentic.add(g)
    return authentic


def _dehyphenate_participants(
    t: SegmentTransform,
    carrier_prov: tuple[str, ...],
    ced_text: dict[str, str],
) -> tuple[str, str] | None:
    """B2 — validate one ``dehyphenate`` transform against the carrier currently under
    reconstruction (``carrier_prov`` is that carrier's ordered provenance). Returns
    ``(left_id, right_id)`` when **every** frozen contract field holds, else ``None``
    (record does not apply here / is malformed).

    The frozen Stage-3 generation contract (``reflow._join``:
    ``segment_ids = tuple(unit_ids_so_far) + (right,)``) means a well-formed record's
    ``segment_ids`` is *exactly* the hosting carrier's ordered provenance prefix up to
    and including the joined-right segment — never a subset of two IDs, never with an
    unrelated prefix / suffix ID, never out of carrier order, never with a duplicate.
    """
    if t.kind != "dehyphenate":
        return None
    if t.permitted_by != _DEHYPHENATE_RULE or t.stage != _DEHYPHENATE_STAGE:
        return None
    sids = tuple(t.segment_ids or ())
    if len(sids) < 2 or t.joined_with is None or sids[-1] != t.joined_with:
        return None
    if len(set(sids)) != len(sids):
        return None  # no duplicate participant ids
    right = sids[-1]
    if right not in carrier_prov:
        return None
    ri = carrier_prov.index(right)
    if ri < 1:
        return None
    if sids != tuple(carrier_prov[: ri + 1]):
        return None  # must be exactly this carrier's provenance prefix through right
    left = sids[-2]  # == carrier_prov[ri - 1]: adjacent, left immediately before right
    if left == right:
        return None
    if not ced_text.get(left, "").endswith(_HYPHEN):
        return None  # the only permitted mutation is dropping a trailing U+002D
    return (left, right)


def _carrier_violations(
    actual: str,
    provenance: tuple[str, ...],
    is_table: bool,
    ced_text: dict[str, str],
    tx_by_right: dict[str, list[SegmentTransform]],
    authentic_groups: set[frozenset[str]],
) -> set[str]:
    """Reconstruct one carrier's expected text from its ordered provenance + permitted
    transforms and compare it, codepoint-exact, to ``actual``. Returns the blamed
    segment ids (empty ⇒ the carrier reconstructs exactly)."""
    lits = [ced_text.get(p, "") for p in provenance]
    prov_set = set(provenance)

    def _ident_sibling(i: int) -> bool:
        # The identical-evidence collapse exception is table-cell-only and
        # provenance-authenticated: the whole group must be owned by *this* cell and
        # already validated by :func:`_authenticated_ident_groups` (B1).
        if i == 0 or not is_table:
            return False
        a, b = provenance[i - 1], provenance[i]
        if not lits[i] or lits[i] != lits[i - 1]:
            return False
        return any(
            a in g and b in g and g <= prov_set for g in authentic_groups
        )

    dehyph_left: set[str] = set()
    expected = lits[0] if lits else ""
    for i in range(1, len(provenance)):
        pid = provenance[i]
        lit = lits[i]
        if _ident_sibling(i):
            continue  # a byte-identical duplicate T070 collapsed — contributes nothing
        deh = None
        if not is_table:
            for t in tx_by_right.get(pid, ()):
                v = _dehyphenate_participants(t, provenance, ced_text)
                if v is not None and v[0] == provenance[i - 1]:
                    deh = v
                    break
        if deh is not None:
            dehyph_left.add(deh[0])
            expected = expected[:-1] + lit if expected.endswith(_HYPHEN) else expected + lit
            continue
        if not is_table and _hyphen_fragment(expected) is not None:
            expected = expected + lit  # a retained line-break hyphen suppresses the space
        elif lit == "" or expected == "":
            expected = expected + lit
        else:
            expected = expected + WRAPPED_LINE_JOIN + lit

    if expected == actual:
        return set()

    blamed: set[str] = set()
    pos = 0
    all_present = True
    for i, pid in enumerate(provenance):
        if _ident_sibling(i):
            continue
        contrib = lits[i]
        if pid in dehyph_left and contrib.endswith(_HYPHEN):
            contrib = contrib[:-1]
        if contrib.strip() == "":
            continue
        j = actual.find(contrib, pos)
        if j == -1:
            blamed.add(pid)
            all_present = False
        else:
            pos = j + len(contrib)
    if all_present:
        # every literal present, in order — yet the exact carrier still differs: an
        # insertion / reorder around the literals implicates the whole carrier.
        blamed.update(
            pid
            for i, pid in enumerate(provenance)
            if not _ident_sibling(i) and lits[i].strip() != ""
        )
    return blamed


def _malformed_dehyphenate(
    t: SegmentTransform,
    carrier_prov: list[tuple[str, ...]],
    ced_text: dict[str, str],
) -> set[str]:
    """B2 — a ``dehyphenate`` record that no carrier can host well-formed is a
    violation on its own: wrong rule / stage / shape, duplicate participant ids, or
    ``segment_ids`` that is not *exactly* one carrier's ordered provenance prefix
    through the joined-right segment (participants split across carriers, an unrelated
    prefix / suffix id, wrong order), or a left literal without a trailing ``U+002D``.
    """
    sids = tuple(t.segment_ids or ())
    named = {s for s in sids if s in ced_text}
    if t.permitted_by != _DEHYPHENATE_RULE or t.stage != _DEHYPHENATE_STAGE:
        return named
    if len(sids) < 2 or t.joined_with is None or sids[-1] != t.joined_with:
        return named
    if len(set(sids)) != len(sids):
        return named  # duplicate participant ids
    right = sids[-1]
    hosts = [
        prov
        for prov in carrier_prov
        if right in prov
        and prov.index(right) >= 1
        and sids == tuple(prov[: prov.index(right) + 1])
    ]
    if len(hosts) != 1:
        return named  # not exactly one carrier's prefix-through-right
    left = sids[-2]
    if not ced_text.get(left, "").endswith(_HYPHEN):
        return {left} & set(ced_text)
    return set()


def authenticated_dehyphenations(
    semantic: SemanticDocument, ced: CanonicalExtractedDocument
) -> tuple[SegmentTransform, ...]:
    """The subset of ``semantic.segment_transforms`` that are ``dehyphenate`` records
    satisfying the **frozen** Stage-3 lineage contract (T066–T074 / B2) against the
    actual semantic carriers and the CED literals — the only records a downstream
    consumer (the Stage-4 self-check) may trust to account for a joined line-boundary
    surface.

    A record is authenticated only when **every** frozen field holds — the same checks
    :func:`_dehyphenate_participants` and :func:`_malformed_dehyphenate` enforce inside
    :func:`literal_accounting_violations`, reused here verbatim (no weaker duplicate
    contract):

    * ``kind == "dehyphenate"``, ``permitted_by == "FR-014"``, ``stage == 3``;
    * ``segment_ids`` has ≥ 2 entries, all unique, ``segment_ids[-1] == joined_with``;
    * exactly **one** semantic carrier (prose / heading / clause / list item / table
      cell — never the outer table block) has ordered provenance whose prefix through
      the joined-right segment is *exactly* ``segment_ids`` (adjacency, source order,
      no unrelated / reordered / duplicated / cross-carrier participant ids);
    * the left participant's stored CED literal ends in ``U+002D``;
    * no other ``dehyphenate`` record shares this record's ``joined_with`` or its
      ``(left, right)`` boundary (no conflicting duplicate transforms).
    * reconstructing the unique carrier from its exact CED literals and applying the
      authenticated transforms at their exact adjacent boundaries yields the carrier's
      actual text codepoint-for-codepoint (a joined token elsewhere proves nothing).

    Deterministic; order-preserving. A forged record (``permitted_by="FR-999"``,
    ``stage=99``, unknown / unrelated / reordered ids, a cross-carrier or duplicated
    participant sequence, a forged ``joined_with``, or a conflicting twin) is absent
    from the result.
    """
    ced_text = _ced_literals(ced)
    carriers = [
        (b.kind == "table", tuple(prov), text)
        for b in semantic.blocks
        for text, prov in _carrier_units(b)
        if prov
    ]
    deh = [t for t in semantic.segment_transforms if t.kind == "dehyphenate"]

    joined_counts: dict[str, int] = {}
    boundary_counts: dict[tuple[str, str], int] = {}
    for t in deh:
        sids = tuple(t.segment_ids or ())
        if t.joined_with:
            joined_counts[t.joined_with] = joined_counts.get(t.joined_with, 0) + 1
        if len(sids) >= 2:
            key = (sids[-2], sids[-1])
            boundary_counts[key] = boundary_counts.get(key, 0) + 1

    structurally_valid: list[tuple[SegmentTransform, tuple[bool, tuple[str, ...], str]]] = []
    for t in deh:
        sids = tuple(t.segment_ids or ())
        # frozen conflict rule (no duplicate transform for the same joined boundary)
        if t.joined_with and joined_counts.get(t.joined_with, 0) > 1:
            continue
        if len(sids) >= 2 and boundary_counts.get((sids[-2], sids[-1]), 0) > 1:
            continue
        # exactly one hosting carrier, each validated by the frozen per-carrier contract
        hosts = [
            carrier
            for carrier in carriers
            for _is_table, prov, _actual in (carrier,)
            if _dehyphenate_participants(t, prov, ced_text) is not None
        ]
        if len(hosts) != 1:
            continue
        host = hosts[0]
        _is_table, host_prov, _actual = host
        v = _dehyphenate_participants(t, host_prov, ced_text)
        if v is None:
            continue
        left_id, right_id = v
        if left_id != host_prov[host_prov.index(right_id) - 1]:
            continue
        structurally_valid.append((t, host))

    # Bind lineage to the actual carrier, not to a joined token found somewhere in it.
    # Reconstruct each hosting carrier from its exact CED literals using precisely the
    # structurally-valid, non-conflicting transforms at their authenticated boundaries.
    # A wrong/ambiguous occurrence therefore invalidates the claimed transform even if
    # the same joined token happens to occur elsewhere in the carrier.
    tx_by_right: dict[str, list[SegmentTransform]] = {}
    for t, _host in structurally_valid:
        if t.joined_with is not None:
            tx_by_right.setdefault(t.joined_with, []).append(t)
    authentic_ident = _authenticated_ident_groups(semantic, ced)

    out: list[SegmentTransform] = []
    for t, (is_table, prov, actual) in structurally_valid:
        if _carrier_violations(
            actual, prov, is_table, ced_text, tx_by_right, authentic_ident
        ):
            continue
        out.append(t)
    return tuple(out)


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
