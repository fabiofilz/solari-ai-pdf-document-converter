"""Deterministic artifact naming (T026).

FR-053: every generated file's name is a pure function of the original filename stem and
the selected page ranges, so identical inputs yield identical names. cli.md fixes the
shape ``<base> = <stem>[__p<sel>]`` — the ``__p<sel>`` suffix is present only for a partial
selection; the whole document has **no** suffix (the run-scoped intermediate name and the
deliverable name are then just ``<stem>.<run_id>.unverified.md`` / ``<stem>.md``).

These are pure string helpers — **no filesystem side effects**. The atomic-write / collision
policy is T027 (``artifacts_io``); ``run_id`` is T025 (``run_identity``). This module never
recomputes a run identifier.
"""

from __future__ import annotations

from solari_converter.model.page_selection import PageSelection

__all__ = ["selector_token", "base_name", "artifact_name"]


def selector_token(selection: PageSelection) -> str:
    """The page-range token used **inside a filename**: ``""`` for the whole document,
    else e.g. ``"2_5-7_10-12"`` (``_`` between parts, ``-`` inside a range).

    Distinct from :meth:`PageSelection.normalized_token`, which yields ``"all"`` for the
    whole document — that form is the value of the persisted ``page_selection`` envelope
    field, not part of any filename.
    """
    if selection.is_whole_document:
        return ""
    return selection.normalized_token()


def base_name(stem: str, selection: PageSelection) -> str:
    """``<base> = <stem>[__p<sel>]`` (cli.md)."""
    token = selector_token(selection)
    return f"{stem}__p{token}" if token else stem


def artifact_name(
    stem: str,
    selection: PageSelection,
    *,
    kind: str = "base",
    run_id: str | None = None,
) -> str:
    """A deterministic artifact name.

    ``kind``:
      * ``"base"`` — ``<base>`` (the stem for cross-referencing other names);
      * ``"markdown"`` — the deliverable Markdown ``<base>.md``;
      * ``"unverified_markdown"`` — the run-scoped staging Markdown
        ``intermediates/<base>.<run_id>.unverified.md`` (requires ``run_id``).
    """
    base = base_name(stem, selection)
    if kind == "base":
        return base
    if kind == "markdown":
        return f"{base}.md"
    if kind == "unverified_markdown":
        if not run_id:
            raise ValueError("kind='unverified_markdown' requires run_id")
        return f"intermediates/{base}.{run_id}.unverified.md"
    raise ValueError(f"unknown artifact kind {kind!r}")
