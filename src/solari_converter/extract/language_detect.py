"""OCR language detection (T045).

Two-pass OCR needs a per-page/region language guess before the recognition pass
(research §5). The benchmark decision (`benchmarks/ocr/RESULTS.md`, T013) is:

* default detector **lingua** (``lingua-language-detector``) — deterministic, no seed needed;
* fallback **langdetect** with ``DetectorFactory.seed = 0`` (seed-pinned);
* primary validated languages **Portuguese / English / Spanish**; French / Italian / German
  are architecture-compatible coverage only; **no CJK / non-Latin expansion**.

A ``--ocr-lang`` override wins over auto-detection and is recorded as
``language_source == "override"`` (FR-027a). Unknown / empty / featureless text degrades to
the safe sentinel ``"und"`` — never a crash (M3).

The result is **routing / provenance metadata only** — it carries no text payload and is
never accepted as source content.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "UNDETERMINED",
    "PRIMARY_LANGUAGES",
    "COVERAGE_LANGUAGES",
    "LanguageResult",
    "LanguageDetector",
    "LinguaDetector",
    "LangdetectDetector",
    "build_detector",
    "detect_language",
    "detect_regions",
]

UNDETERMINED = "und"
PRIMARY_LANGUAGES: tuple[str, ...] = ("pt", "en", "es")
COVERAGE_LANGUAGES: tuple[str, ...] = ("fr", "it", "de")
_SUPPORTED = PRIMARY_LANGUAGES + COVERAGE_LANGUAGES

LanguageSource = Literal["auto", "override"]


@dataclass(frozen=True)
class LanguageResult:
    """Per page/region language evidence (FR-027a). Metadata only — no text payload."""

    languages: tuple[str, ...]
    language_source: LanguageSource
    detector: str

    @property
    def primary(self) -> str:
        return self.languages[0] if self.languages else UNDETERMINED


@runtime_checkable
class LanguageDetector(Protocol):
    name: str

    def detect(self, text: str) -> str | None:
        """Return an ISO 639-1 code among the supported set, or ``None`` when undetermined."""
        ...


def _normalise_override(override: str | Sequence[str] | None) -> tuple[str, ...]:
    if override is None:
        return ()
    if isinstance(override, str):
        parts = [p.strip().lower() for p in override.split(",")]
    else:
        parts = [str(p).strip().lower() for p in override]
    return tuple(p for p in parts if p)


class LinguaDetector:
    """Default detector — lingua over the supported Latin set. Deterministic by construction."""

    name = "lingua"

    def __init__(self) -> None:
        from lingua import Language, LanguageDetectorBuilder

        by_iso = {
            "pt": Language.PORTUGUESE, "en": Language.ENGLISH, "es": Language.SPANISH,
            "fr": Language.FRENCH, "it": Language.ITALIAN, "de": Language.GERMAN,
        }
        self._detector = LanguageDetectorBuilder.from_languages(
            *(by_iso[code] for code in _SUPPORTED)
        ).build()

    def detect(self, text: str) -> str | None:
        if not text or not text.strip():
            return None
        language = self._detector.detect_language_of(text)
        if language is None:
            return None
        code = language.iso_code_639_1.name.lower()
        return code if code in _SUPPORTED else None


class LangdetectDetector:
    """Fallback detector — langdetect, seed-pinned for reproducibility (research §5)."""

    name = "langdetect"

    def __init__(self) -> None:
        from langdetect import DetectorFactory

        DetectorFactory.seed = 0

    def detect(self, text: str) -> str | None:
        if not text or not text.strip():
            return None
        from langdetect import detect as _detect
        from langdetect.lang_detect_exception import LangDetectException

        try:
            code = _detect(text).lower()
        except LangDetectException:
            return None
        code = code.split("-", 1)[0]
        return code if code in _SUPPORTED else None


_DETECTORS: dict[str, type] = {
    "lingua": LinguaDetector,
    "langdetect": LangdetectDetector,
}

_DEFAULT_CACHE: dict[str, LanguageDetector] = {}


def build_detector(name: str = "lingua") -> LanguageDetector:
    """Construct a detector by benchmark name (``"lingua"`` default, ``"langdetect"`` fallback)."""
    try:
        return _DETECTORS[name]()  # type: ignore[return-value]
    except KeyError:
        raise ValueError(
            f"unknown language detector {name!r}; expected one of {sorted(_DETECTORS)}"
        ) from None


def _shared(name: str) -> LanguageDetector:
    if name not in _DEFAULT_CACHE:
        _DEFAULT_CACHE[name] = build_detector(name)
    return _DEFAULT_CACHE[name]


def detect_language(
    text: str,
    *,
    override: str | Sequence[str] | None = None,
    detector: LanguageDetector | None = None,
) -> LanguageResult:
    """Detect the language of one page/region.

    ``override`` (a ``--ocr-lang`` value — a bare string, comma string, or sequence) wins
    over auto-detection. Auto-detection falls back to ``"und"`` on undetermined text (M3).
    """
    ov = _normalise_override(override)
    if ov:
        return LanguageResult(languages=ov, language_source="override", detector="override")

    det = detector or _shared("lingua")
    code = det.detect(text)
    if code is None:
        return LanguageResult(languages=(), language_source="auto", detector=det.name)
    return LanguageResult(languages=(code,), language_source="auto", detector=det.name)


def detect_regions(
    texts: Mapping[str, str],
    *,
    override: str | Sequence[str] | None = None,
    detector: LanguageDetector | None = None,
) -> dict[str, LanguageResult]:
    """Per page/region detection — a region-key → text mapping in, region-key → result out."""
    det = detector or _shared("lingua")
    return {
        key: detect_language(text, override=override, detector=det)
        for key, text in texts.items()
    }
