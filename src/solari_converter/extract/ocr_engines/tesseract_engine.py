"""Tesseract 5 OCR adapter (T009).

Wraps ``pytesseract.image_to_data``; groups words into lines; per-line confidence
is the *minimum* per-word confidence (research §9a), normalized to 0-100. Raises
``OcrUnavailable`` (exit 8, mapped in T016) when the ``tesseract`` binary or a
requested language's traineddata is missing.
"""

from __future__ import annotations

from pathlib import Path

from solari_converter.errors import OcrUnavailable

from .base import OcrLine, normalize_confidence

# BCP-47-ish -> tesseract traineddata code
_LANG_MAP = {
    "pt": "por", "pt-br": "por", "por": "por",
    "en": "eng", "eng": "eng",
    "es": "spa", "spa": "spa",
    "fr": "fra", "fra": "fra",
    "de": "deu", "deu": "deu",
    "it": "ita", "ita": "ita",
}


def _tess_lang(languages: list[str]) -> str:
    codes: list[str] = []
    for lang in languages or ["pt"]:
        code = _LANG_MAP.get(lang.lower().strip(), lang.lower().strip())
        if code not in codes:
            codes.append(code)
    return "+".join(codes) or "por"


class TesseractEngine:
    name = "tesseract"

    def is_available(self) -> bool:
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
        except Exception:
            return False
        return True

    def _installed_langs(self) -> set[str]:
        import pytesseract

        try:
            return set(pytesseract.get_languages(config=""))
        except Exception:
            return set()

    def recognize(self, image: object, languages: list[str]) -> list[OcrLine]:
        try:
            import pytesseract
            from pytesseract import Output, TesseractError, TesseractNotFoundError
        except ImportError as exc:  # pragma: no cover - pytesseract is a pinned dep
            raise OcrUnavailable(f"pytesseract not importable: {exc}") from exc

        lang = _tess_lang(languages)
        installed = self._installed_langs()
        if installed:
            for code in lang.split("+"):
                if code not in installed:
                    raise OcrUnavailable(
                        f"tesseract language data '{code}' is not installed "
                        f"(available: {sorted(installed)})"
                    )

        img = _load(image)
        try:
            data = pytesseract.image_to_data(img, lang=lang, output_type=Output.DICT)
        except TesseractNotFoundError as exc:
            raise OcrUnavailable(f"tesseract binary not found: {exc}") from exc
        except TesseractError as exc:
            raise OcrUnavailable(f"tesseract failed (lang={lang!r}): {exc}") from exc

        return _group_lines(data)


def _load(image: object):
    from PIL import Image

    if isinstance(image, (str, Path)):
        return Image.open(image)
    return image  # already a PIL image / ndarray pytesseract accepts


def _group_lines(data: dict) -> list[OcrLine]:
    n = len(data["text"])
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for i in range(n):
        if not data["text"][i].strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        buckets.setdefault(key, []).append(i)

    lines: list[OcrLine] = []
    for key in sorted(buckets):
        idxs = buckets[key]
        words = [data["text"][i] for i in idxs]
        confs = [float(data["conf"][i]) for i in idxs]
        xs0 = [data["left"][i] for i in idxs]
        ys0 = [data["top"][i] for i in idxs]
        xs1 = [data["left"][i] + data["width"][i] for i in idxs]
        ys1 = [data["top"][i] + data["height"][i] for i in idxs]
        min_conf = min(confs) if confs else -1.0
        lines.append(
            OcrLine(
                text=" ".join(words),
                bbox=(float(min(xs0)), float(min(ys0)), float(max(xs1)), float(max(ys1))),
                confidence=normalize_confidence(min_conf, "tesseract"),
            )
        )
    return lines
