"""Read-only PDF source loader (T034).

The single source boundary (M2 / research §24): the original PDF is opened **once** here
and never again downstream. The loader exposes a deterministic page count and 1-based
**physical** page addressing, and hands each independent extraction path a **read-only**
handle to the *source* — path A (Docling), path B (pdfplumber + pypdfium2) and path C
(OCR / native-reliability routing) each read the source directly and never consume another
path's produced candidate. Sharing the ``pdfplumber`` / ``pypdfium2`` libraries on the
source handle is fine; sharing a path's *interpretation* is not, and the loader holds no
such interpretation.

A missing / corrupted / encrypted source maps to :class:`SourceUnreadable` (exit 3) — no
silent partial success. Opened handles are context-managed and closable; :meth:`close` is
idempotent.

This module performs **no extraction** — it only opens, addresses, and closes the source.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from types import TracebackType
from typing import Any

import pdfplumber
import pypdfium2 as pdfium

from solari_converter.errors import SourceUnreadable

__all__ = ["PdfSource", "load_pdf"]

_ENCRYPTED_MARKERS = ("password", "security")


class PdfSource:
    """An opened, read-only view of one source PDF.

    Attributes
    ----------
    path:
        The source path.
    page_count:
        Deterministic physical page count.
    plumber / pdfium:
        The shared read-only library handles. Extraction paths use these directly; the
        loader never mutates them and never exposes a candidate through them.
    """

    def __init__(self, path: Path, plumber: pdfplumber.PDF, pdfium_doc: Any) -> None:
        self.path = path
        self._plumber = plumber
        self._pdfium = pdfium_doc
        self._page_count = len(plumber.pages)
        self._closed = False

    # --- introspection ---------------------------------------------------------

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def plumber(self) -> pdfplumber.PDF:
        """The read-only ``pdfplumber`` handle on the source (path B / native-reliability)."""
        self._check_open()
        return self._plumber

    @property
    def pdfium(self) -> Any:
        """The read-only ``pypdfium2`` document handle on the source (rasterization for OCR)."""
        self._check_open()
        return self._pdfium

    # --- 1-based physical page addressing ------------------------------------

    def plumber_page(self, page_number: int) -> Any:
        """The ``pdfplumber`` page at 1-based **physical** ``page_number``."""
        return self._plumber.pages[self._physical_index(page_number)]

    def pdfium_page(self, page_number: int) -> Any:
        """The ``pypdfium2`` page at 1-based **physical** ``page_number``.

        The caller is responsible for closing the returned page object if it holds it.
        """
        return self._pdfium[self._physical_index(page_number)]

    def _physical_index(self, page_number: int) -> int:
        self._check_open()
        if not isinstance(page_number, int) or isinstance(page_number, bool):
            raise ValueError(f"physical page number must be an int, got {page_number!r}")
        if not 1 <= page_number <= self._page_count:
            raise ValueError(
                f"physical page {page_number} out of range 1..{self._page_count}"
            )
        return page_number - 1

    # --- lifecycle ------------------------------------------------------------

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("PdfSource is closed")

    def close(self) -> None:
        """Close both handles. Idempotent."""
        if self._closed:
            return
        self._closed = True
        for handle in (self._plumber, self._pdfium):
            with contextlib.suppress(Exception):  # best-effort teardown
                handle.close()

    def __enter__(self) -> PdfSource:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def load_pdf(path: str | Path) -> PdfSource:
    """Open ``path`` once and return a read-only :class:`PdfSource`.

    Raises :class:`SourceUnreadable` (exit 3) for a missing, corrupted, or encrypted
    source. On a partial open failure any handle already opened is closed before raising.
    """
    src_path = Path(path)
    if not src_path.is_file():
        raise SourceUnreadable(f"source PDF not found: {src_path}")

    pdfium_doc: Any | None = None
    plumber: pdfplumber.PDF | None = None
    try:
        try:
            pdfium_doc = pdfium.PdfDocument(str(src_path))
            # Force the page table to materialise so a malformed doc fails here.
            _ = len(pdfium_doc)
        except pdfium.PdfiumError as exc:
            reason = "encrypted" if _looks_encrypted(exc) else "corrupted or unreadable"
            raise SourceUnreadable(f"source PDF is {reason}: {src_path} ({exc})") from exc

        try:
            plumber = pdfplumber.open(str(src_path))
            _ = plumber.pages  # trigger parsing of the page tree
        except SourceUnreadable:
            raise
        except Exception as exc:  # noqa: BLE001 — pdfplumber wraps pdfminer errors
            reason = "encrypted" if _looks_encrypted(exc) else "corrupted or unreadable"
            raise SourceUnreadable(f"source PDF is {reason}: {src_path} ({exc})") from exc
    except BaseException:
        for handle in (plumber, pdfium_doc):
            if handle is not None:
                with contextlib.suppress(Exception):
                    handle.close()
        raise

    return PdfSource(src_path, plumber, pdfium_doc)


def _looks_encrypted(exc: BaseException) -> bool:
    cause = exc.__cause__
    parts = [str(exc), str(cause or ""), type(cause).__name__ if cause is not None else ""]
    text = " ".join(parts).lower()
    return any(marker in text for marker in _ENCRYPTED_MARKERS)
