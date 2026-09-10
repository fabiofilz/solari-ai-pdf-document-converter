"""Stage-5 deterministic Markdown rendering (T076).

``render_markdown`` is a **pure, deterministic projection** of a frozen
:class:`~solari_converter.model.semantic.SemanticDocument` (T073) onto Markdown text
(FR-012 / FR-016 / FR-017a / FR-020). It does not — ever — rewrite author text,
normalise a literal, invent content, re-order blocks (the ``SemanticDocument`` order is
authoritative; the only permitted exception, ``structural_reorder``, was already
applied upstream), reintroduce a collapsed/removed segment, or call an LLM.

Rendering rules
---------------

* **heading** — ``#``×level for levels 1–6 (FR-017a); a level > 6 is emitted as an
  emphasised lead-in paragraph carrying an explicit ``[L{n}]`` marker so every level
  stays machine-distinguishable (FR-017a);
* **paragraph / clause** — the reflowed text verbatim (a clause keeps its identifier,
  FR-019);
* **list** — one line per item, ``"  "`` × ``depth`` of leading indentation; the item's
  own literal (which already carries its leading marker — a list item is only
  classified when a real marker is present, T069) is emitted verbatim (FR-018/FR-019);
* **table** — a table with no merged cells is a Markdown pipe table; a table that
  contains a merged (spanned) cell is an HTML ``<table>`` whose ``rowspan`` /
  ``colspan`` express the spans exactly (FR-020). The per-page reconstruction and the
  multi-page stitch were done by T070 — rendering never redoes them; a repeated header
  T070 already collapsed simply never reaches here (FR-021/FR-022);
* **OCR marker** — a block every one of whose source segments is OCR-derived is
  preceded by a block-level :data:`OCR_BLOCK_MARKER` line (FR-025). This is *envelope*
  around the block, not a change to any segment's characters (research §25.2).

Serialisation (research §25.1): the text is joined with LF only and ends with exactly
one trailing newline; :func:`render_markdown_bytes` hands it to
``artifacts_io.markdown_bytes`` — ``text.encode("utf-8")``, **no BOM, LF only, no
Unicode normalisation**.

The ``RenderMap`` (per-block / per-segment codepoint spans + the ordered
``segment_transforms`` chain) is **not** produced here — that extension is T145.
"""

from __future__ import annotations

from collections.abc import Collection

from solari_converter.artifacts_io import markdown_bytes
from solari_converter.model.semantic import (
    Block,
    ClauseBlock,
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    SemanticDocument,
)
from solari_converter.transform.tables import TableBlock, TableCell

__all__ = [
    "OCR_BLOCK_MARKER",
    "MAX_MARKDOWN_HEADING_LEVEL",
    "LIST_INDENT",
    "render_markdown",
    "render_markdown_bytes",
]

#: The deterministic block-level OCR-derived marker (FR-025). Placed on its own line
#: immediately before a block every one of whose source segments came from local OCR.
#: An HTML comment: machine-detectable, inert in every Markdown renderer, and *envelope*
#: (it changes no segment's own characters — research §25.2).
OCR_BLOCK_MARKER: str = "<!-- ocr-derived -->"

#: Deepest hierarchy level Markdown heading syntax can carry (FR-017a).
MAX_MARKDOWN_HEADING_LEVEL: int = 6

#: One nesting step of list indentation (envelope; never part of a segment's literal).
LIST_INDENT: str = "  "


def render_markdown(
    doc: SemanticDocument, *, ocr_segment_ids: Collection[str] = ()
) -> str:
    """Render ``doc`` to deterministic Markdown text (LF only, one trailing newline).

    ``ocr_segment_ids`` — the accepted source segment ids that came from local OCR
    (derived by the caller from the CED ``SourceRef.origin_kind``); a block all of whose
    provenance is in this set is preceded by :data:`OCR_BLOCK_MARKER`.
    """
    ocr = frozenset(ocr_segment_ids)
    chunks: list[str] = []
    for block in doc.blocks:
        body = _render_block(block)
        if _is_fully_ocr(block, ocr):
            body = f"{OCR_BLOCK_MARKER}\n{body}"
        chunks.append(body)
    return "\n\n".join(chunks) + "\n"


def render_markdown_bytes(
    doc: SemanticDocument, *, ocr_segment_ids: Collection[str] = ()
) -> bytes:
    """:func:`render_markdown` serialised per research §25.1 — ``text.encode("utf-8")``,
    no BOM, LF only, no Unicode normalisation (``artifacts_io.markdown_bytes``)."""
    return markdown_bytes(render_markdown(doc, ocr_segment_ids=ocr_segment_ids))


# --- per-block rendering ----------------------------------------------------------


def _render_block(block: Block) -> str:
    if isinstance(block, HeadingBlock):
        return _render_heading(block)
    if isinstance(block, ParagraphBlock):
        return block.text
    if isinstance(block, ClauseBlock):
        return block.text
    if isinstance(block, ListBlock):
        return _render_list(block)
    if isinstance(block, TableBlock):
        return _render_table(block)
    raise TypeError(f"unrenderable block kind: {block!r}")  # pragma: no cover


def _render_heading(block: HeadingBlock) -> str:
    level = block.level
    if level <= MAX_MARKDOWN_HEADING_LEVEL and not block.deep:
        return f"{'#' * level} {block.text}"
    # deeper than Markdown can express → emphasised lead-in + explicit level marker
    return f"*{block.text}* [L{level}]"


def _render_list(block: ListBlock) -> str:
    return "\n".join(
        f"{LIST_INDENT * item.depth}{item.text}" for item in block.items
    )


# --- table rendering -------------------------------------------------------------


def _render_table(block: TableBlock) -> str:
    rows = block.table.rows
    if block.table.has_merged_cells:
        return _render_html_table(rows)
    return _render_pipe_table(rows)


def _render_pipe_table(rows: list[list[TableCell]]) -> str:
    ncols = max((len(r) for r in rows), default=0)
    lines: list[str] = []
    for i, row in enumerate(rows):
        cells = [_pipe_cell(c.text) for c in row]
        cells += [""] * (ncols - len(cells))
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("| " + " | ".join(["---"] * ncols) + " |")
    return "\n".join(lines)


def _render_html_table(rows: list[list[TableCell]]) -> str:
    lines = ["<table>"]
    for row in rows:
        lines.append("<tr>" + "".join(_html_cell(c) for c in row) + "</tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _pipe_cell(text: str) -> str:
    """A pipe-table cell value: escape the structural pipe and backslash, and fold a
    hard line break to ``<br>`` (a literal newline would break the table row). The
    numeric / textual value itself is otherwise untouched (FR-020)."""
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "\n")
        .replace("\n", "<br>")
    )


def _html_cell(cell: TableCell) -> str:
    tag = "th" if cell.is_header else "td"
    attrs = ""
    if cell.rowspan > 1:
        attrs += f' rowspan="{cell.rowspan}"'
    if cell.colspan > 1:
        attrs += f' colspan="{cell.colspan}"'
    return f"<{tag}{attrs}>{_html_escape(cell.text)}</{tag}>"


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\r\n", "\n")
        .replace("\n", "<br>")
    )


# --- OCR marking ----------------------------------------------------------------


def _is_fully_ocr(block: Block, ocr: frozenset[str]) -> bool:
    prov = tuple(block.provenance)
    return bool(prov) and all(sid in ocr for sid in prov)
