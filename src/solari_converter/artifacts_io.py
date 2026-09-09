"""Atomic artifact I/O primitives + the FR-054 output-collision policy (T027).

Every artifact this project writes goes through one of the helpers here so the guarantees
are uniform:

* **atomic** — write a sibling ``<name>.tmp`` in the *same directory*, ``flush()`` +
  ``os.fsync()``, then ``os.replace`` onto the target. A crash leaves either the old file
  or the new complete file, never a partial one.
* **never a silent overwrite** (FR-054 / SC-016) — :func:`write_atomic` refuses to change an
  existing artifact whose content differs (``OutputCollision``, exit 5); identical bytes are
  a satisfied no-op (SC-009). The source PDF and intermediates are protected the same way.
* **append-only stores** — :func:`append_line_atomic` is the *atomic whole-file publish per
  append* for ``resolutions.jsonl`` and ``<base>.review-authorizations.jsonl``
  (research §22.2): read every existing line, append the new complete newline-framed line,
  publish the whole file atomically. :func:`read_jsonl` tolerates a torn/unparseable final
  line on read (an external crash / legacy writer) — it is ignored, never counted.
* **Markdown serialisation** — :func:`markdown_bytes` writes ``text.encode("utf-8")`` in
  binary form: **no BOM, LF only, no Unicode normalisation** (research §25.1).

``publish_final`` is the final-Markdown publish helper. It is defined here but is invoked
**only** by ``publish_delivery(...)`` in ``pipeline/extract.py`` (T154) once every delivery
gate has passed — nothing in this tranche calls it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from solari_converter.errors import OutputCollision

__all__ = [
    "write_atomic",
    "append_line_atomic",
    "read_jsonl",
    "markdown_bytes",
    "write_record",
    "staging_markdown_path",
    "intermediates_dir",
    "publish_final",
]


# --- low-level atomic write --------------------------------------------------------


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def write_atomic(
    path: str | os.PathLike[str], data: bytes, *, overwrite: bool = False
) -> Path:
    """Atomically write ``data`` to ``path``.

    With ``overwrite=False`` (default — a *deliverable* / *intermediate* artifact) an
    existing file with **different** content is an :class:`OutputCollision` (FR-054, exit 5)
    and is left untouched; identical bytes are a satisfied no-op (SC-009 re-run).

    With ``overwrite=True`` the target is replaced unconditionally — for a **regenerated
    derived view** whose source of truth lives elsewhere (the ``.md`` rendering of an
    append-only ``.jsonl`` store, the atomically-rewritten human-review queue). Still atomic
    (temp + fsync + ``os.replace``); still never a partial file.
    """
    p = Path(path)
    if p.exists() and not overwrite:
        existing = p.read_bytes()
        if existing == data:
            return p  # satisfied no-op (SC-009 re-run)
        raise OutputCollision(
            f"{p} already exists with different content "
            f"({len(existing)} vs {len(data)} bytes); the existing file is preserved (FR-054)"
        )
    _atomic_write_bytes(p, data)
    return p


# --- append-only store: atomic whole-file publish per append ---------------------


def read_jsonl(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Parse every line of a JSONL store. A **torn / unparseable final line** is ignored
    (research §22.2) — a crash mid-write elsewhere, or a stray legacy line, never counts as
    a valid record. A missing file yields ``[]``."""
    p = Path(path)
    if not p.exists():
        return []
    raw = p.read_text(encoding="utf-8")
    lines = raw.split("\n")
    records: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        if line == "":
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            is_last_nonempty = all(rest == "" for rest in lines[i + 1:])
            if is_last_nonempty:
                break  # tolerate a torn final line
            raise
        records.append(obj)
    return records


def append_line_atomic(path: str | os.PathLike[str], record: dict[str, Any]) -> Path:
    """Append one record to a JSONL store as an **atomic whole-file publish**
    (research §22.2): read the existing lines, append
    ``json.dumps(record, ensure_ascii=False)`` + ``"\\n"``, write every line to
    ``<store>.tmp`` in the same directory, ``flush`` + ``fsync``, ``os.replace``."""
    p = Path(path)
    existing = read_jsonl(p)
    all_lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in existing]
    all_lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
    _atomic_write_bytes(p, ("\n".join(all_lines) + "\n").encode("utf-8"))
    return p


# --- Markdown serialisation (research §25.1) ------------------------------------


def markdown_bytes(text: str) -> bytes:
    """``text.encode("utf-8")`` — no BOM, LF only, no Unicode normalisation."""
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.encode("utf-8")


# --- record emit (dual .json + .md for audit records; .json only for M1 records) -


def write_record(path_stem: str | os.PathLike[str], model: Any, *, emit_md: bool) -> list[Path]:
    """Persist a pydantic record. Always writes ``<path_stem>.json``
    (``model.model_dump_json``); when ``emit_md`` also writes ``<path_stem>.md`` from
    ``model.render_markdown()`` (FR-057 dual emit). Extraction candidates and the CED pass
    ``emit_md=False`` — JSON is their sole authoritative representation (M1).

    ``.json``/``.md`` are appended to ``path_stem`` verbatim (``stem.with_name(stem.name
    + ext)``), never via ``Path.with_suffix()`` — a stem that itself contains a dot
    (e.g. the candidate naming shape ``<base>.candidate.<technique>``, T051) would
    otherwise have its trailing dotted segment silently replaced instead of a new
    extension being appended."""
    stem = Path(path_stem)
    json_bytes = model.model_dump_json(indent=2).encode("utf-8") + b"\n"
    written = [write_atomic(stem.with_name(stem.name + ".json"), json_bytes)]
    if emit_md:
        md_path = stem.with_name(stem.name + ".md")
        written.append(write_atomic(md_path, markdown_bytes(model.render_markdown())))
    return written


# --- naming helpers for the staging area --------------------------------------


def intermediates_dir(output_dir: str | os.PathLike[str]) -> Path:
    return Path(output_dir) / "intermediates"


def staging_markdown_path(output_dir: str | os.PathLike[str], base: str, run_id: str) -> Path:
    """``<output-dir>/intermediates/<base>.<run_id>.unverified.md`` — the run-scoped,
    non-deliverable render location. Publishing it to ``<base>.md`` is T154's job."""
    return intermediates_dir(output_dir) / f"{base}.{run_id}.unverified.md"


def publish_final(staged: str | os.PathLike[str], target: str | os.PathLike[str]) -> Path:
    """Atomic ``os.replace`` of a verified staged Markdown onto ``<base>.md``.

    **Invoked only by ``publish_delivery(...)`` in ``pipeline/extract.py`` (T154)** once
    every delivery gate has passed. Not called anywhere in this tranche."""
    src, dst = Path(staged), Path(target)
    if dst.exists() and dst.read_bytes() != src.read_bytes():
        raise OutputCollision(
            f"{dst} already exists with different content; a changed decision needs a fresh "
            f"--output-dir (FR-054 / research §25.7)"
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    return dst
