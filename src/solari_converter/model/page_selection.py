"""Page selection parsing + validation (T021).

FR-001..FR-005: convert the whole document by default; accept single pages, contiguous
ranges, and multiple discontinuous ranges in one request; page numbers are **1-based
physical** positions (FR-003), never printed labels; reject invalid selections — out of
range, reversed, non-numeric, overlapping — with a clear message and **produce no output**
(FR-004). The canonical selector token (research §14 / cli.md ``<base> = <stem>[__p<sel>]``)
uses ``_`` between parts and ``-`` inside a range; the whole document is ``"all"``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from solari_converter.errors import InvalidSelection

__all__ = ["PageSelection"]


@dataclass(frozen=True)
class PageSelection:
    """A validated, normalised page selection.

    ``ranges`` are 1-based inclusive ``[start, end]`` pairs — sorted, non-overlapping and
    merged-adjacent. ``is_whole_document`` means "every page"; ``ranges`` is then empty and
    the concrete page list is only known once a page count is supplied.
    """

    ranges: list[list[int]] = field(default_factory=list)
    is_whole_document: bool = False

    # --- factories ------------------------------------------------------------

    @classmethod
    def whole_document(cls) -> PageSelection:
        return cls(ranges=[], is_whole_document=True)

    @classmethod
    def parse(cls, spec: str) -> PageSelection:
        """Parse ``--pages`` (e.g. ``"2,5-7,10-12"``). Raises :class:`InvalidSelection`
        on any malformed or overlapping input."""
        if spec is None or spec.strip() == "":
            return cls.whole_document()

        raw: list[list[int]] = []
        for token in spec.split(","):
            token = token.strip()
            if not token:
                raise InvalidSelection(f"empty page-selection token in {spec!r}")
            if "-" in token.lstrip("-"):  # a range "N-M" (not a lone negative)
                lo_s, _, hi_s = token.partition("-")
                lo, hi = _one(lo_s, spec), _one(hi_s, spec)
                if lo > hi:
                    raise InvalidSelection(
                        f"reversed range {token!r} in {spec!r} (start {lo} > end {hi})"
                    )
                raw.append([lo, hi])
            else:
                n = _one(token, spec)
                raw.append([n, n])

        raw.sort()
        merged: list[list[int]] = []
        for lo, hi in raw:
            if merged and lo <= merged[-1][1]:
                ov_lo, ov_hi = max(merged[-1][0], lo), min(merged[-1][1], hi)
                raise InvalidSelection(
                    f"overlapping ranges in {spec!r}: pages {ov_lo}-{ov_hi} appear twice"
                )
            if merged and lo == merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        return cls(ranges=merged, is_whole_document=False)

    # --- normalisation / resolution -----------------------------------------

    def normalized_token(self) -> str:
        """The canonical selector token — ``"all"`` for the whole document, else e.g.
        ``"2_5-7_10-12"``."""
        if self.is_whole_document:
            return "all"
        parts = [f"{a}" if a == b else f"{a}-{b}" for a, b in self.ranges]
        return "_".join(parts)

    def resolve(self, *, page_count: int) -> list[int]:
        """The concrete ordered list of 1-based physical pages. Raises
        :class:`InvalidSelection` if any selected page exceeds ``page_count`` (FR-004)."""
        if self.is_whole_document:
            return list(range(1, page_count + 1))
        pages: list[int] = []
        for lo, hi in self.ranges:
            if hi > page_count:
                raise InvalidSelection(
                    f"page {hi} is out of range (document has {page_count} pages)"
                )
            pages.extend(range(lo, hi + 1))
        return pages


def _one(text: str, spec: str) -> int:
    text = text.strip()
    if not text.isdigit():  # rejects "", "foo", "-1", "1.0"
        raise InvalidSelection(f"non-numeric page {text!r} in {spec!r}")
    n = int(text)
    if n < 1:
        raise InvalidSelection(f"page {n} is not a 1-based physical page in {spec!r}")
    return n
