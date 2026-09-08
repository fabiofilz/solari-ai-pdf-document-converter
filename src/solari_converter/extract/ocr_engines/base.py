"""Engine-neutral OCR contract (T008).

Defines the ``OcrEngine`` protocol, the ``OcrLine`` value type, and
``normalize_confidence`` — the one place per-engine confidence scales are mapped
onto a common 0-100 scale (research §9a). **No default engine is chosen here**
(the OCR Benchmark Gate, T013, does that).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Per-engine raw confidence scales (research §9a):
#   tesseract : 0-100 per word (-1 => "no confidence" reported)
#   rapidocr  : 0.0-1.0 per detected line/box (PP-OCR)
_ENGINE_SCALE = {
    "tesseract": (0.0, 100.0),
    "rapidocr": (0.0, 1.0),
}


@dataclass(frozen=True, slots=True)
class OcrLine:
    """One recognised text line.

    ``bbox`` is ``[x0, y0, x1, y1]`` in image pixel coordinates (origin top-left),
    or ``None`` when the engine does not report geometry.
    ``confidence`` is always on a 0-100 scale (see ``normalize_confidence``).
    """

    text: str
    bbox: tuple[float, float, float, float] | None
    confidence: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 100.0):
            raise ValueError(f"OcrLine.confidence must be 0-100, got {self.confidence!r}")


def normalize_confidence(raw: float, engine: str) -> float:
    """Map an engine's raw per-token/line confidence onto 0-100.

    Tesseract's 0-100 passes through (with -1 -> 0.0); PP-OCR/RapidOCR's 0-1 is
    scaled by 100. Unknown engines are assumed already 0-100. The result is
    clamped to [0, 100].
    """
    lo, hi = _ENGINE_SCALE.get(engine, (0.0, 100.0))
    if engine == "tesseract" and raw < 0:  # tesseract sentinel for "unknown"
        return 0.0
    span = hi - lo
    value = 0.0 if span == 0 else (raw - lo) / span * 100.0
    return max(0.0, min(100.0, value))


@runtime_checkable
class OcrEngine(Protocol):
    """A fully-local OCR extraction technique (path C, FR-060).

    Implementations are engine-neutral adapters; callers select one explicitly
    (``--ocr-engine``) until T013 records a benchmark-decided default.
    """

    #: stable identifier used in provenance (``ocr:<name>``) and ``--ocr-engine``
    name: str

    def is_available(self) -> bool:
        """True iff the engine's binary / language data / model files are present."""
        ...

    def recognize(self, image: object, languages: list[str]) -> list[OcrLine]:
        """Run OCR on ``image`` (a path or a PIL image) for the given ``languages``
        (BCP-47-ish codes / engine language keys). Raises ``OcrUnavailable`` when
        the engine is not usable."""
        ...
