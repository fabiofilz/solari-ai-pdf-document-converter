"""T042 [US1] — contract test: the non-interactive ``solari-convert review`` sub-interface.

INTENTIONAL future RED — every test here
    Owners: **T080** (``src/solari_converter/pipeline/review.py`` — the headless review core:
    ``list`` / ``show`` / ``resolve`` / ``authorize`` / ``status``, no ``questionary`` import,
    no LLM, never writes Markdown) and **T081** (``cli.py`` dispatch). Neither exists yet.

Contract asserted once they land (contracts/cli.md):
    * ``review list`` / ``show <id>`` / ``resolve <id> (--select N | --value TEXT |
      --value-file PATH | --order ids)`` / ``authorize`` / ``status`` all parse and dispatch
      to the headless core;
    * bare ``review`` is a defined entry point (interactive dispatch wired later by T152 — not
      exercised here);
    * bad ``--select`` / bad ``--order`` / non-UTF-8 ``--value-file`` → exit 2;
    * ``--value-file`` bytes are read, required UTF-8, decoded, stored **verbatim** (no strip /
      normalization / BOM removal);
    * ``resolve`` appends a superseding-aware store record and marks the item ``resolved``;
    * ``authorize`` → exit 6 while any item is ``open``; otherwise appends an authorization event;
    * ``status`` prints ``run_state`` + ``{open, resolved, applicable, verified, failed}``;
    * ``review`` never instantiates the LLM client and never writes Markdown.
"""

from __future__ import annotations

import importlib

from solari_converter.errors import EXIT_HUMAN_REVIEW_REQUIRED, EXIT_INVALID_ARGS


def _review_core():
    """RED until T080."""
    return importlib.import_module("solari_converter.pipeline.review")


def _cli():
    """RED until T081."""
    return importlib.import_module("solari_converter.cli")


def test_headless_review_core_exists_without_questionary_or_llm() -> None:
    from pathlib import Path

    mod = _review_core()
    for op in ("list_items", "show_item", "resolve_item"):
        assert hasattr(mod, op)
    src = importlib.import_module("solari_converter.pipeline.review").__file__
    assert src and "questionary" not in Path(src).read_text(encoding="utf-8")


def test_review_subcommands_parse() -> None:
    """RED until T081."""
    cli = _cli()
    parser = cli.build_parser()
    for argv in (
        ["review", "list"],
        ["review", "show", "i1"],
        ["review", "resolve", "i1", "--select", "0"],
        ["review", "resolve", "i1", "--value", "X"],
        ["review", "resolve", "i1", "--value-file", "v.txt"],
        ["review", "resolve", "i1", "--order", "s1,s2"],
        ["review", "authorize"],
        ["review", "status"],
        ["review"],
    ):
        assert parser.parse_args(argv).command == "review", argv


def test_bad_resolve_input_exits_2() -> None:
    """RED until T080/T081."""
    cli = _cli()
    assert cli.main(["review", "resolve", "i1", "--select", "-1"]) == EXIT_INVALID_ARGS


def test_authorize_with_open_items_exits_6() -> None:
    """RED until T080/T081."""
    cli = _cli()
    assert cli.main(["review", "authorize"]) == EXIT_HUMAN_REVIEW_REQUIRED
