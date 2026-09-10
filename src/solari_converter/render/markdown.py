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

import re
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
    "serialize_html_cell_text",
    "serialize_pipe_cell",
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

#: A block-context line whose first non-space run is one of these would be parsed by a
#: Markdown reader as structure (ATX heading, list, thematic break, setext underline).
#: The renderer backslash-escapes that one lead character so the author literal renders
#: verbatim (research §25.2 ``markdown_escape``). ``>`` / ``*`` / ``_`` / `` ` `` are
#: already neutralised inline below, so they are not repeated here.
_LEADING_STRUCTURE_RE = re.compile(r"^(\s{0,3})(#{1,6}|[-+~=]|\d+[.)])(?=\s|$)")


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


# --- Stage-5 context-aware escaping (research §25.2 ``markdown_escape``) -----------
#
# The renderer preserves the **literal author-visible content** of every segment while
# emitting valid Markdown structure. It escapes only characters that a Markdown reader
# would otherwise treat as active syntax; it never escapes the structural syntax the
# renderer itself generates (the ``#`` of a heading, the ``*`` / ``[L{n}]`` of a deep
# heading envelope, list indentation, table pipes, ``<table>``/``<tr>``/``<td>``).


def _escape_inline(text: str) -> str:
    """Neutralise every Markdown-/HTML-significant character a value contains so it
    renders verbatim: backslash first, then HTML entities (``&`` before ``<``/``>`` so a
    literal ``&lt;`` is not double-encoded), then the inline emphasis / code / autolink
    triggers, then any hard line break folded to a literal ``<br>`` (a bare newline would
    otherwise open a new block or a soft break)."""
    out = text.replace("\\", "\\\\")
    out = out.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = out.replace("`", "\\`").replace("*", "\\*").replace("_", "\\_")
    out = out.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return out


def _escape_block_text(text: str) -> str:
    """Inline escaping plus the one leading structural character (``#`` / ``-`` / ``+``
    / ``~`` / ``=`` / ``1.``) a Markdown reader would treat as a block marker at the
    start of a paragraph, clause, or list-item body."""
    out = _escape_inline(text)
    m = _LEADING_STRUCTURE_RE.match(out)
    if m is None:
        return out
    marker = m.group(2)
    # escape the significant char: the trailing '.'/')' of an ordered-list marker,
    # else the first char of the run ('#'/'-'/'+'/'~'/'=').
    at = m.start(2) + (len(marker) - 1 if marker[0].isdigit() else 0)
    return out[:at] + "\\" + out[at:]


# --- per-block rendering ----------------------------------------------------------


def _render_block(block: Block) -> str:
    if isinstance(block, HeadingBlock):
        return _render_heading(block)
    if isinstance(block, ParagraphBlock):
        return _escape_block_text(block.text)
    if isinstance(block, ClauseBlock):
        return _escape_block_text(block.text)
    if isinstance(block, ListBlock):
        return _render_list(block)
    if isinstance(block, TableBlock):
        return _render_table(block)
    raise TypeError(f"unrenderable block kind: {block!r}")  # pragma: no cover


def _render_heading(block: HeadingBlock) -> str:
    level = block.level
    text = _escape_inline(block.text)
    if level <= MAX_MARKDOWN_HEADING_LEVEL and not block.deep:
        return f"{'#' * level} {text}"
    # deeper than Markdown can express → emphasised lead-in + explicit level marker.
    # ``text`` has its own ``*`` escaped inline, so the envelope ``*…*`` stays intact.
    return f"*{text}* [L{level}]"


def _render_list(block: ListBlock) -> str:
    return "\n".join(
        f"{LIST_INDENT * item.depth}{_render_list_item_text(item)}"
        for item in block.items
    )


def _render_list_item_text(item) -> str:
    """The item's own literal already carries its leading marker (T069 only classifies a
    list item when a real marker is present). Keep that marker literal — it *is* the list
    structure — and escape only the author text after it."""
    marker = item.marker or ""
    if marker and item.text.startswith(marker):
        return marker + _escape_block_text(item.text[len(marker):])
    return _escape_block_text(item.text)


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
        cells = [serialize_pipe_cell(c.text) for c in row]
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


def serialize_pipe_cell(text: str) -> str:
    """A pipe-table cell value (research §25.2 ``markdown_escape``): backslash first,
    then the HTML-significant characters as entities (``&`` before ``<``/``>`` so a
    literal ``&lt;`` is not double-encoded — authored ``<b>x</b> & y`` must never become
    active HTML), then the structural pipe, then the inline emphasis / code triggers a
    cell still parses (`` ` ``, ``*``, ``_``), then a hard line break folded to ``<br>``
    (a literal newline would break the table row; it is emitted *after* the ``<`` / ``>``
    pass so the renderer's own ``<br>`` is not re-encoded). No numeric / separator
    normalisation (FR-020)."""
    return (
        text.replace("\\", "\\\\")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
    )


# Kept for the frozen T075 renderer tests and existing internal callers.
_pipe_cell = serialize_pipe_cell


def _html_cell(cell: TableCell) -> str:
    tag = "th" if cell.is_header else "td"
    attrs = ""
    if cell.rowspan > 1:
        attrs += f' rowspan="{cell.rowspan}"'
    if cell.colspan > 1:
        attrs += f' colspan="{cell.colspan}"'
    return f"<{tag}{attrs}>{serialize_html_cell_text(cell.text)}</{tag}>"


def serialize_html_cell_text(text: str) -> str:
    """An HTML ``<table>`` cell value (research §25.2 ``html_escape`` / ``cell_newline_br``):
    ``&`` before ``<``/``>``, then a hard line break to ``<br>``. Markdown emphasis is
    inert inside an HTML block, so no backslash escaping is needed or wanted here."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
    )


# Backwards-compatible internal name; the public pure helper is shared with validation.
_html_escape = serialize_html_cell_text


# --- OCR marking ----------------------------------------------------------------


def _is_fully_ocr(block: Block, ocr: frozenset[str]) -> bool:
    prov = tuple(block.provenance)
    return bool(prov) and all(sid in ocr for sid in prov)
