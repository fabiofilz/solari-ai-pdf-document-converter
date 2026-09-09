"""T041 [US1] — contract test: the ``solari-convert extract`` CLI surface (contracts/cli.md).

INTENTIONAL future RED — every test here
    Owner: **T081** (``src/solari_converter/cli.py`` — argument parsing + dispatch + the
    exception→exit-code mapping already defined in ``errors.py`` T016). The parser does not
    exist yet; ``import solari_converter.cli`` fails.

Contract asserted once the parser lands:
    * ``extract SOURCE.pdf`` accepts ``--pages`` / ``--output-dir`` / ``--resolution-store`` /
      ``--ocr-engine`` / ``--ocr-lang`` / ``--ocr-confidence-threshold`` (0–100) /
      ``--reconcile-confidence-threshold`` (0–1) / ``--llm-base-url`` / ``--llm-model`` /
      ``--json``;
    * ``--help`` states pages are **1-based physical** positions, not printed labels (FR-003);
    * out-of-range numeric options and a bad ``--pages`` spec exit **2**;
    * the documented exit codes 2 / 3 / 6 / 8 are wired to the ``errors.py`` mapping.
"""

from __future__ import annotations

import importlib

from solari_converter.errors import (
    EXIT_HUMAN_REVIEW_REQUIRED,
    EXIT_INVALID_ARGS,
    EXIT_OCR_UNAVAILABLE,
    EXIT_SOURCE_UNREADABLE,
)


def _cli():
    return importlib.import_module("solari_converter.cli")


def _parser():
    cli = _cli()
    for name in ("build_parser", "make_parser", "get_parser"):
        if hasattr(cli, name):
            return getattr(cli, name)()
    raise AssertionError("cli module exposes no parser factory")


def test_cli_module_exists() -> None:
    """RED until T081."""
    cli = _cli()
    assert hasattr(cli, "main")


def test_extract_accepts_the_documented_options() -> None:
    """RED until T081."""
    parser = _parser()
    ns = parser.parse_args([
        "extract", "SOURCE.pdf", "--pages", "2,5-7", "--output-dir", "out",
        "--resolution-store", "r.jsonl", "--ocr-engine", "tesseract",
        "--ocr-lang", "pt,en", "--ocr-confidence-threshold", "70",
        "--reconcile-confidence-threshold", "0.75",
        "--llm-base-url", "http://127.0.0.1:11434/v1", "--llm-model", "m", "--json",
    ])
    assert ns.command == "extract"


def test_extract_help_states_physical_pages() -> None:
    """RED until T081."""
    text = _parser().format_help().lower()
    assert "physical" in text


def test_out_of_range_options_exit_2() -> None:
    """RED until T081."""
    cli = _cli()
    for bad in (["--ocr-confidence-threshold", "150"],
                ["--reconcile-confidence-threshold", "2"],
                ["--pages", "10-5"]):
        assert cli.main(["extract", "SOURCE.pdf", *bad]) == EXIT_INVALID_ARGS, bad


def test_documented_exit_codes_are_the_errors_module_constants() -> None:
    assert (EXIT_INVALID_ARGS, EXIT_SOURCE_UNREADABLE,
            EXIT_HUMAN_REVIEW_REQUIRED, EXIT_OCR_UNAVAILABLE) == (2, 3, 6, 8)
