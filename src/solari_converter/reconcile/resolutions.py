"""Append-only human-review resolution store + applicability authority (T030).

The durable, cross-run record of every confirmed HUMAN_REVIEW_REQUIRED decision
(``resolutions.jsonl`` + a regenerated ``resolutions.md``). Research §22 / §22.2,
FR-057b / FR-068 / FR-070 / FR-071 / FR-076, M1 / M3.

Authority rules this module enforces:

* **``compute_applicability_key``** (FR-071) — a stored decision is replayed for a fresh
  conflict *only* when the key matches: source hash + conflict type + the canonical
  page/region/aligned-candidate-value set + the OCR/enabled-path config subset. A changed
  context ⇒ a different key ⇒ no silent replay, a fresh item.
* **``sequence_index`` is the sole "currently-applicable" authority (H6)** — assigned
  ``= max(existing) + 1``, unique and strictly increasing store-wide (I1). The current
  resolution for a key is the valid record with the **greatest ``sequence_index``**, not
  the last line.
* **``supersedes`` is audit linkage only** — invariants I2 (points at the currently-
  applicable prior for the same key), I3 (``null`` iff first for the key), I4 (target
  exists, same key, lower ``sequence_index``), I5 (a simple chain — no forks / cycles /
  orphans). **I6 — fail closed**: any violation for a key ⇒ the loader refuses to replay
  *that key* (it is raised fresh) and never guesses; other keys are unaffected.
* **``resolution_id`` is content-bound** — computed here via the T024 helper
  (``model.human_review.compute_resolution_id``); the store is the *only* assigner.
* **durability (M3)** — every append is an atomic whole-file publish
  (``artifacts_io.append_line_atomic``); a torn / unparseable final record is ignored.
* a ``mode: entered`` literal value is stored **verbatim** — no strip / normalisation.

No LLM, no UI, no database. ``applicable_resolution_digest()`` is **owned here**;
``run_identity`` only folds the string it returns.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from solari_converter import artifacts_io
from solari_converter.model.human_review import (
    HumanReviewResolution,
    canonical_selected,
    compute_resolution_id,
)
from solari_converter.run_identity import canonical_json

__all__ = [
    "compute_applicability_key",
    "candidate_values_for_applicability",
    "ResolutionStore",
    "ResolutionIndex",
]


# --- applicability key (research §22 / FR-071) ----------------------------------


def compute_applicability_key(
    *,
    source_sha256: str,
    conflict_type: str,
    physical_page: int,
    region_bboxes: Sequence[Sequence[float]],
    candidate_values: Sequence[str],
    config_subset: Mapping[str, Any],
) -> str:
    """``sha256(source_sha256 ⧺ conflict_type ⧺ canonical(page, region, aligned
    candidate-value set) ⧺ canonical_json(config_subset))`` — 64 hex.

    The aligned candidate-value set is order-independent (sorted); ``enabled_extraction_paths``
    in the config subset is a **set** (sorted). ``ocr_languages_override`` order is kept
    (primary language matters).
    """
    region = canonical_json(
        {
            "page": physical_page,
            "regions": [[round(float(c), 3) for c in bbox] for bbox in region_bboxes],
            "candidates": sorted(candidate_values),
        }
    )
    cfg = dict(config_subset)
    paths = cfg.get("enabled_extraction_paths")
    if paths is not None:
        cfg["enabled_extraction_paths"] = sorted(paths)
    parts = [source_sha256, conflict_type, region, canonical_json(cfg)]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def candidate_values_for_applicability(
    conflict_type: str, candidates: Sequence[Mapping[str, Any]]
) -> list[str]:
    """The ``candidate_values`` list :func:`compute_applicability_key` takes, derived from
    the evidence presented to Human Review (block brief §12 — literal: the exact candidate
    values; reading-order: the canonical JSON of each candidate/supported order). Used both
    when a resolution is created (T061) and when its applicability is re-checked under the
    current source/config (H1)."""
    if conflict_type == "reading_order":
        return [
            canonical_json(list(c["order"]))
            for c in candidates
            if c.get("order") is not None
        ]
    return [c["value"] for c in candidates if c.get("value") is not None]


# --- the store -------------------------------------------------------------


@dataclass
class ResolutionIndex:
    """The result of loading + validating the store (research §22.2)."""

    current: dict[str, HumanReviewResolution] = field(default_factory=dict)
    failed_closed: dict[str, str] = field(default_factory=dict)
    all_records: list[HumanReviewResolution] = field(default_factory=list)


class ResolutionStore:
    """Wraps one ``resolutions.jsonl`` path."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.md_path = self.path.with_suffix(".md")

    # --- read ------------------------------------------------------------

    def _load_raw(self) -> list[HumanReviewResolution]:
        return [
            HumanReviewResolution.model_validate(obj)
            for obj in artifacts_io.read_jsonl(self.path)
        ]

    def load_index(self) -> ResolutionIndex:
        records = self._load_raw()
        seq_counts = Counter(r.sequence_index for r in records)
        by_key: dict[str, list[HumanReviewResolution]] = defaultdict(list)
        for r in records:
            by_key[r.applicability_key].append(r)

        idx = ResolutionIndex(all_records=records)
        for key, recs in by_key.items():
            recs = sorted(recs, key=lambda r: r.sequence_index)
            reason = _validate_chain(recs, seq_counts)
            if reason is not None:
                idx.failed_closed[key] = reason
            else:
                idx.current[key] = recs[-1]  # greatest sequence_index
        return idx

    def replay_for(self, applicability_key: str) -> HumanReviewResolution | None:
        """The currently-applicable resolution for a key, or ``None`` — no match, or the
        key's chain failed closed (it must be raised fresh, FR-071)."""
        return self.load_index().current.get(applicability_key)

    def applicable_index(
        self,
        *,
        source_sha256: str | None = None,
        config_subset: Mapping[str, Any] | None = None,
    ) -> dict[str, HumanReviewResolution]:
        """The currently-applicable resolution set, optionally **scoped** to one source +
        config identity (H1 / block brief §12).

        With no scope arguments this is exactly ``load_index().current`` — the historical
        behaviour every existing caller relies on. When ``source_sha256`` and/or
        ``config_subset`` are given, a currently-applicable record is included **only** when

        1. its envelope ``source_sha256`` matches, and
        2. recomputing its applicability key from its own conflict type / physical page /
           region bboxes / candidates-presented **and the given config subset** reproduces
           its stored ``applicability_key``.

        It **fails closed** — a record whose applicability cannot be reproduced (a raised
        exception, or a mismatch) is excluded, so another document's / another config's
        resolution can never change this run's identity."""
        current = self.load_index().current
        if source_sha256 is None and config_subset is None:
            return dict(current)
        scoped: dict[str, HumanReviewResolution] = {}
        for key, r in current.items():
            if source_sha256 is not None and r.source_sha256 != source_sha256:
                continue
            if config_subset is not None:
                try:
                    recomputed = compute_applicability_key(
                        source_sha256=r.source_sha256,
                        conflict_type=r.conflict_type,
                        physical_page=r.physical_page,
                        region_bboxes=r.region_bboxes,
                        candidate_values=candidate_values_for_applicability(
                            r.conflict_type,
                            [c.model_dump() for c in r.candidates_presented],
                        ),
                        config_subset=config_subset,
                    )
                except Exception:  # noqa: BLE001 - fail closed on any recompute failure
                    continue
                if recomputed != r.applicability_key:
                    continue
            scoped[key] = r
        return scoped

    def applicable_resolution_digest(
        self,
        *,
        source_sha256: str | None = None,
        config_subset: Mapping[str, Any] | None = None,
    ) -> str:
        """``sha256`` over the sorted ``f"{applicability_key}={canonical_json(selected)}"``
        of the **currently-applicable** resolution set (data-model.md ``RunIdentity`` /
        research §14). Order-independent; an empty set yields ``sha256(b"").hexdigest()``.

        ``source_sha256`` / ``config_subset`` scope the set to one document + config
        identity (H1): a resolution created for a different source, or under a config that
        no longer reproduces its applicability key, contributes **nothing** — so it can
        never perturb this run's ``run_id``. With no arguments the behaviour is unchanged.
        Folded into ``run_id`` by ``run_identity.compute_run_id`` — *consumed* there,
        owned here."""
        current = self.applicable_index(
            source_sha256=source_sha256, config_subset=config_subset
        )
        pairs = sorted(
            f"{key}={canonical_json(canonical_selected(r.selected))}"
            for key, r in current.items()
        )
        return hashlib.sha256("\n".join(pairs).encode("utf-8")).hexdigest()

    # --- write -----------------------------------------------------------

    def append(
        self,
        *,
        applicability_key: str,
        review_item_id: str,
        conflict_type: str,
        physical_page: int,
        region_bboxes: Sequence[Sequence[float]],
        candidates_presented: Sequence[Mapping[str, Any]],
        selected: Mapping[str, Any],
        envelope: Mapping[str, Any],
        reviewer_note: str | None = None,
    ) -> HumanReviewResolution:
        """Append one confirmed decision. **Assigns** ``sequence_index = max(existing) + 1``,
        sets ``supersedes`` (I2/I3), and **computes** the content-bound ``resolution_id``
        via the T024 helper. Published atomically; ``resolutions.md`` regenerated after."""
        existing = self._load_raw()
        next_seq = max((r.sequence_index for r in existing), default=-1) + 1

        prior = [r for r in existing if r.applicability_key == applicability_key]
        supersedes = (
            max(prior, key=lambda r: r.sequence_index).resolution_id if prior else None
        )
        selected = dict(selected)
        resolution_id = compute_resolution_id(
            applicability_key=applicability_key,
            sequence_index=next_seq,
            selected=selected,
        )
        record = HumanReviewResolution(
            **dict(envelope),
            resolution_id=resolution_id,
            sequence_index=next_seq,
            supersedes=supersedes,
            applicability_key=applicability_key,
            review_item_id=review_item_id,
            conflict_type=conflict_type,
            physical_page=physical_page,
            region_bboxes=[list(b) for b in region_bboxes],
            candidates_presented=[dict(c) for c in candidates_presented],
            selected=selected,
            reviewer_note=reviewer_note,
        )
        artifacts_io.append_line_atomic(self.path, record.model_dump(mode="json"))
        self._render_md()
        return record

    def _render_md(self) -> None:
        """Regenerate ``resolutions.md`` from the ``.jsonl`` — a derived human-readable
        view (research §22.2), atomically overwritten, never collision-guarded."""
        idx = self.load_index()
        lines = ["# Human-review resolution store", ""]
        for rec in idx.all_records:
            cur = idx.current.get(rec.applicability_key)
            mark = " (currently applicable)" if cur is rec else ""
            failed = rec.applicability_key in idx.failed_closed
            lines.append(
                f"- `seq {rec.sequence_index}` · item `{rec.review_item_id}` · "
                f"`{rec.conflict_type}` · key `{rec.applicability_key[:12]}…`{mark}"
                + (" — CHAIN FAILED CLOSED" if failed else "")
            )
            lines.append(f"  - resolution_id `{rec.resolution_id}`  supersedes `{rec.supersedes}`")
            lines.append(f"  - selected: `{canonical_json(canonical_selected(rec.selected))}`")
        for key, why in idx.failed_closed.items():
            lines.append(f"- **fail-closed** key `{key[:12]}…`: {why}")
        artifacts_io.write_atomic(
            self.md_path, ("\n".join(lines) + "\n").encode("utf-8"), overwrite=True
        )


# --- chain validation (I1-I6) -------------------------------------------------


def _validate_chain(
    recs: list[HumanReviewResolution], seq_counts: Counter[int]
) -> str | None:
    """Validate one applicability key's records (already sorted by ``sequence_index``).
    Returns a diagnostic string on any I1-I5 violation, else ``None``."""
    # I1 — sequence_index unique store-wide (as it touches this key)
    for r in recs:
        if seq_counts[r.sequence_index] > 1:
            return f"sequence_index {r.sequence_index} is not unique store-wide (I1)"

    id_by_id = {r.resolution_id: r for r in recs}

    # I3 — the first (lowest sequence_index) record has supersedes == null
    if recs[0].supersedes is not None:
        return "first resolution for the key has a non-null `supersedes` (I3)"

    for prev, cur in zip(recs[:-1], recs[1:], strict=True):
        del prev  # unused; the "currently-applicable prior" is recomputed below
        if cur.supersedes is None:
            return "a non-first resolution has a null `supersedes` (I3)"
        target = id_by_id.get(cur.supersedes)
        if target is None:
            return f"`supersedes` {cur.supersedes} does not resolve within this key's chain (I4)"
        if target.sequence_index >= cur.sequence_index:
            return "`supersedes` target does not have a lower sequence_index (I4)"
        prior_applicable = max(
            (r for r in recs if r.sequence_index < cur.sequence_index),
            key=lambda r: r.sequence_index,
        )
        if cur.supersedes != prior_applicable.resolution_id:
            return "`supersedes` does not point at the currently-applicable prior record (I2)"

    # I5 — a simple chain: no two records supersede the same target (fork)
    targets = [r.supersedes for r in recs if r.supersedes is not None]
    if len(targets) != len(set(targets)):
        return "fork: two records supersede the same target (I5)"

    return None
