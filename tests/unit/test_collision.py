"""T014 — failing-first unit tests for the FR-054 / SC-016 output-collision policy in
``solari_converter.artifacts_io``.

GREEN owner: **T027** (`artifacts_io.py`). Written now (Constitution VI); FAILS until T027
lands — INTENTIONAL future RED, not a regression. FR-054: never overwrite the source or an
intermediate by default; a name collision whose existing file has **different** content is
an ``OutputCollision`` (exit 5); identical bytes are a satisfied no-op (SC-009 / SC-016).
"""

from __future__ import annotations

from pathlib import Path

from solari_converter.errors import OutputCollision


def _io():
    import solari_converter.artifacts_io as artifacts_io  # GREEN owner: T027

    return artifacts_io


def test_identical_bytes_are_a_satisfied_no_op(tmp_path: Path) -> None:
    io = _io()
    target = tmp_path / "agreement.md"
    io.write_atomic(target, b"# same\n")
    io.write_atomic(target, b"# same\n")  # must not raise
    assert target.read_bytes() == b"# same\n"


def test_different_bytes_raise_output_collision(tmp_path: Path) -> None:
    io = _io()
    target = tmp_path / "agreement.md"
    io.write_atomic(target, b"# original\n")
    try:
        io.write_atomic(target, b"# changed\n")
    except OutputCollision:
        pass
    else:  # pragma: no cover - failure path
        raise AssertionError("expected OutputCollision for differing content")
    assert target.read_bytes() == b"# original\n"  # existing file preserved


def test_prior_delivered_markdown_plus_changed_decision_is_a_collision(tmp_path: Path) -> None:
    # FR-054 / research §25.7: a prior <base>.md + a new run_id (changed applicable
    # resolution => different bytes) collides; the delivered artifact is not overwritten.
    io = _io()
    base_md = tmp_path / "agreement.md"
    io.write_atomic(base_md, b"delivered under run_id AAAA\n")
    try:
        io.write_atomic(base_md, b"delivered under run_id BBBB\n")
    except OutputCollision:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected OutputCollision")
    assert base_md.read_bytes() == b"delivered under run_id AAAA\n"
