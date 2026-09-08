"""RapidOCR (PP-OCR) OCR adapter (T010).

Wraps ``rapidocr-onnxruntime`` (pinned ``1.4.4``). **REOPENED 2026-09-07** — the
first implementation used the package's bundled **Chinese** ``ch_PP-OCRv4_rec``
recognition model, whose dictionary lacks ``ã â ê õ ç ñ`` …; that is invalid for
the v1 languages (research §4.1, spec Clarifications 2026-09-07).

Amended contract:

* one **multilingual Latin** PP-OCR *recognition* model is used for **every**
  supported v1 language (PT / EN / ES / FR / IT / DE) — no per-language model
  switching, no Latin/CJK routing;
* the model + its dictionary are supplied as **explicit local paths**
  (``rec_model_path`` / ``rec_keys_path``; constructor args or the
  ``SOLARI_RAPIDOCR_REC_MODEL`` / ``SOLARI_RAPIDOCR_REC_KEYS`` environment
  variables), acquired at setup time (``benchmarks/ocr/models/``, zero runtime
  download);
* both configured artifacts are **SHA256-verified against the pinned approved v1
  identity** (``APPROVED_V1_REC_MODEL`` / ``APPROVED_V1_REC_DICT`` below — the
  same digests as ``benchmarks/ocr/models/SHA256SUMS`` and the plan.md OCR
  ledger) **before** RapidOCR is instantiated. Identity is content-addressed: a
  renamed copy with a matching digest is accepted; a corrupt / altered / wrong /
  unknown file — or the bundled Chinese model — fails closed with
  ``OcrUnavailable``. Environment-variable overrides select *paths* only; they
  cannot bypass digest verification;
* the recognition-model **provenance reports the approved family/version only
  after digest verification succeeds**, alongside the actual configured basename
  and the verified model + dictionary digests;
* an **unsupported / non-Latin** language request is rejected with
  ``OcrUnavailable`` rather than run against the Latin model.

Only *recognition* is swapped; ``rapidocr-onnxruntime``'s bundled
``ch_PP-OCRv4_det`` / ``ch_ppocr_mobile_v2.0_cls`` models are kept — both are
script-agnostic (box detection + orientation, no character reading).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from solari_converter.errors import OcrUnavailable

from .base import OcrLine, normalize_confidence

PACKAGE_VERSION = "rapidocr-onnxruntime==1.4.4"

# ---------------------------------------------------------------------------------------
# Authoritative pinned identity of the APPROVED v1 RapidOCR recognition artifacts.
# This constant IS the runtime policy — it mirrors (and must stay consistent with)
# benchmarks/ocr/models/README.md, benchmarks/ocr/models/SHA256SUMS, and the
# "OCR engine" ledger entry in specs/001-pdf-markdown-converter/plan.md.
# Nothing here is read from mutable external state at runtime.
# ---------------------------------------------------------------------------------------
APPROVED_V1_REC_MODEL: dict[str, str] = {
    "canonical_name": "latin_PP-OCRv3_rec_infer.onnx",
    "sha256": "e9d7a33667e8aaa702862975186adf2012e3f390cc0f9422865957125f8071cf",
    "family": "PaddleOCR PP-OCRv3 multilingual Latin recognition (mobile)",
}
APPROVED_V1_REC_DICT: dict[str, str] = {
    "canonical_name": "latin_dict.txt",
    "sha256": "8e6d4e3629788c35c31f7e530287d6147b549bb7a265bd6708bb281134429e2c",
}

#: back-compat alias (name-only hint used in log messages / older imports)
EXPECTED_REC_MODEL = APPROVED_V1_REC_MODEL["canonical_name"]

#: supported v1 languages — generic BCP-47-ish ids and their common aliases.
#: RapidOCR does not switch models per language; this set only gates *rejection*
#: of unsupported / non-Latin requests.
_SUPPORTED_LANGS = {
    "pt", "pt-br", "por",
    "en", "eng",
    "es", "spa",
    "fr", "fra",
    "it", "ita",
    "de", "deu",
}

_ENV_MODEL = "SOLARI_RAPIDOCR_REC_MODEL"
_ENV_KEYS = "SOLARI_RAPIDOCR_REC_KEYS"


def _resolve(explicit: str | os.PathLike[str] | None, env_var: str) -> Path | None:
    raw = explicit if explicit is not None else os.environ.get(env_var)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class RapidOcrEngine:
    """PP-OCR via ``rapidocr-onnxruntime`` with a SHA256-pinned multilingual Latin
    recognition model."""

    name = "rapidocr"

    def __init__(
        self,
        rec_model_path: str | os.PathLike[str] | None = None,
        rec_keys_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self._rec_model = _resolve(rec_model_path, _ENV_MODEL)
        self._rec_keys = _resolve(rec_keys_path, _ENV_KEYS)
        self._ocr = None
        self._verified: dict[str, str] | None = None
        self._identity: dict[str, str] | None = None

    # -- artifact verification (fail-closed) ---------------------------------------

    def _verify_artifacts(self) -> dict[str, str]:
        """SHA256-verify the configured model + dictionary against the pinned
        approved v1 identity. Returns the verified digests; raises
        ``OcrUnavailable`` on anything that is not an exact content match."""
        if self._verified is not None:
            return dict(self._verified)

        if not (self._rec_model and self._rec_keys):
            raise OcrUnavailable(
                "RapidOCR Latin recognition model/dictionary not configured "
                f"(pass rec_model_path/rec_keys_path or set {_ENV_MODEL}/{_ENV_KEYS}); "
                "the bundled Chinese ch_PP-OCRv4_rec model must not be used for a "
                "supported v1 language. Run benchmarks/ocr/models/fetch_latin_model.py."
            )
        for label, path in (("model", self._rec_model), ("dictionary", self._rec_keys)):
            if not path.is_file():
                raise OcrUnavailable(
                    f"RapidOCR Latin recognition {label} not found at {str(path)!r}. "
                    "Run benchmarks/ocr/models/fetch_latin_model.py (setup-time, "
                    "checksum-verified). Refusing to fall back to the bundled Chinese model."
                )

        model_sha = _sha256(self._rec_model)
        if model_sha != APPROVED_V1_REC_MODEL["sha256"]:
            raise OcrUnavailable(
                f"RapidOCR recognition model at {str(self._rec_model)!r} does not match the "
                f"approved v1 artifact ({APPROVED_V1_REC_MODEL['canonical_name']}). "
                f"expected sha256 {APPROVED_V1_REC_MODEL['sha256']}, got {model_sha}. "
                "No silent substitution — re-fetch with "
                "benchmarks/ocr/models/fetch_latin_model.py."
            )
        keys_sha = _sha256(self._rec_keys)
        if keys_sha != APPROVED_V1_REC_DICT["sha256"]:
            raise OcrUnavailable(
                f"RapidOCR recognition dictionary at {str(self._rec_keys)!r} does not match the "
                f"approved v1 artifact ({APPROVED_V1_REC_DICT['canonical_name']}). "
                f"expected sha256 {APPROVED_V1_REC_DICT['sha256']}, got {keys_sha}. "
                "No silent substitution — re-fetch with "
                "benchmarks/ocr/models/fetch_latin_model.py."
            )
        self._verified = {"rec_model_sha256": model_sha, "rec_keys_sha256": keys_sha}
        return dict(self._verified)

    # -- availability / provenance -----------------------------------------------

    def is_available(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except Exception:
            return False
        try:
            self._verify_artifacts()
        except OcrUnavailable:
            return False
        return True

    @property
    def model_identity(self) -> dict[str, str]:
        """Actual recognition model in use — verified. Reports the approved
        family/version **only** after SHA256 verification succeeds; otherwise
        raises ``OcrUnavailable`` (provenance can never describe an unverified or
        bundled-Chinese model)."""
        if self._identity is None:
            verified = self._verify_artifacts()
            assert self._rec_model is not None and self._rec_keys is not None
            vocab = sum(
                1 for line in self._rec_keys.read_text(encoding="utf-8").split("\n") if line != ""
            )
            self._identity = {
                "engine": self.name,
                "package": PACKAGE_VERSION,
                "rec_model_path": str(self._rec_model),
                "rec_model_name": self._rec_model.name,
                "rec_model_canonical_name": APPROVED_V1_REC_MODEL["canonical_name"],
                "rec_model_sha256": verified["rec_model_sha256"],
                "rec_keys_path": str(self._rec_keys),
                "rec_keys_name": self._rec_keys.name,
                "rec_keys_sha256": verified["rec_keys_sha256"],
                "rec_dict_symbols": str(vocab),
                "rec_model_family": APPROVED_V1_REC_MODEL["family"],
                "provenance_verified": "sha256",
            }
        return dict(self._identity)

    @property
    def model_version(self) -> str:
        ident = self.model_identity
        return (
            f"{ident['package']} / {ident['rec_model_family']} "
            f"[{ident['rec_model_name']} sha256:{ident['rec_model_sha256'][:12]} "
            f"dict:{ident['rec_dict_symbols']} verified]"
        )

    # -- engine construction -------------------------------------------------------

    def _engine(self):
        if self._ocr is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:  # pragma: no cover - pinned dep
                raise OcrUnavailable(f"rapidocr-onnxruntime not importable: {exc}") from exc
            self._verify_artifacts()  # fail-closed BEFORE instantiating RapidOCR
            assert self._rec_model is not None and self._rec_keys is not None
            try:
                self._ocr = RapidOCR(
                    rec_model_path=str(self._rec_model),
                    rec_keys_path=str(self._rec_keys),
                )
            except Exception as exc:
                raise OcrUnavailable(f"RapidOCR initialisation failed: {exc}") from exc
            self._assert_latin_rec_active()
        return self._ocr

    def _assert_latin_rec_active(self) -> None:
        """Defence-in-depth: fail loudly if the recognizer did not actually pick up
        the configured (verified) model — e.g. a future RapidOCR change that
        silently ignores the kwarg and reverts to the bundled Chinese model."""
        assert self._rec_model is not None
        active = self._active_rec_model_path()
        if active is None:
            return  # cannot introspect this build — the verified kwarg path is the contract
        if Path(active).name != self._rec_model.name:
            raise OcrUnavailable(
                f"RapidOCR recognizer loaded {active!r}, not the configured Latin model "
                f"{self._rec_model.name!r}"
            )
        if "ch_ppocr" in Path(active).name.lower() or Path(active).name.lower().startswith("ch_"):
            raise OcrUnavailable(
                f"RapidOCR recognizer is using a bundled Chinese model ({active!r}) — "
                "forbidden for a supported v1 language"
            )

    def _active_rec_model_path(self) -> str | None:
        ocr = self._ocr
        try:
            rec = ocr.text_rec  # type: ignore[union-attr]
            for holder in (rec, getattr(rec, "session", None)):
                inner = getattr(holder, "session", None)
                path = getattr(inner, "_model_path", None) or getattr(holder, "_model_path", None)
                if path:
                    return str(path)
        except Exception:
            return None
        return None

    # -- recognition -------------------------------------------------------------

    def recognize(self, image: object, languages: list[str]) -> list[OcrLine]:
        self._reject_unsupported(languages)
        ocr = self._engine()
        img = _load(image)
        try:
            result, _elapsed = ocr(img)
        except Exception as exc:
            raise OcrUnavailable(f"RapidOCR recognition failed: {exc}") from exc

        lines: list[OcrLine] = []
        for box, text, score in result or []:
            if not str(text).strip():
                continue
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            lines.append(
                OcrLine(
                    text=str(text),
                    bbox=(float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))),
                    confidence=normalize_confidence(float(score), "rapidocr"),
                )
            )
        lines.sort(key=lambda ln: (ln.bbox[1], ln.bbox[0]) if ln.bbox else (0.0, 0.0))
        return lines

    @staticmethod
    def _reject_unsupported(languages: list[str]) -> None:
        supported = sorted({code.split("-")[0] for code in _SUPPORTED_LANGS})
        for lang in languages or []:
            if lang.lower().strip() not in _SUPPORTED_LANGS:
                raise OcrUnavailable(
                    f"RapidOcrEngine (v1) supports Latin-script {supported} only; "
                    f"refusing language {lang!r}. Non-Latin scripts are out of scope for v1."
                )


def _load(image: object):
    import numpy as np
    from PIL import Image

    if isinstance(image, (str, Path)):
        image = Image.open(image)
    if isinstance(image, Image.Image):
        return np.array(image.convert("RGB"))
    return image
