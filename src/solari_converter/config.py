"""Run configuration resolution (T017).

Resolves every runtime setting with precedence **CLI > environment > default**, validates
numeric bounds (rejecting out-of-range values with :class:`InvalidSelection`, exit 2), and
exposes :meth:`Config.output_affecting_config` — the research §14 effective-input subset
(extract-stage vs validate-stage). That subset is exactly what ``run_identity`` folds and
what ``RunContext`` (T137) persists; it **MUST NOT** contain UI / navigation / authorization
metadata, timeouts, ``base_url``, output-dir, the ``--resolution-store`` path, or ``--json``.

The OCR-engine / language-detector defaults come from the frozen T013 benchmark decision
(``benchmarks/ocr/RESULTS.md`` / research §4–§5): **Tesseract** and **lingua**.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from solari_converter.errors import InvalidSelection

__all__ = ["Config", "DEFAULT_ENABLED_PATHS"]

DEFAULT_ENABLED_PATHS: tuple[str, ...] = ("docling", "pdfplumber", "ocr")

# CLI key -> env var. Environment is the middle precedence tier.
_ENV_MAP: dict[str, str] = {
    "llm_base_url": "SOLARI_LLM_BASE_URL",
    "llm_model": "SOLARI_LLM_MODEL",
    "llm_seed": "SOLARI_LLM_SEED",
    "llm_retries": "SOLARI_LLM_RETRIES",
    "ocr_engine": "SOLARI_OCR_ENGINE",
    "ocr_lang": "SOLARI_OCR_LANG",
    "ocr_confidence_threshold": "SOLARI_OCR_CONFIDENCE_THRESHOLD",
    "reconcile_confidence_threshold": "SOLARI_RECONCILE_CONFIDENCE_THRESHOLD",
    "gross_divergence_threshold": "SOLARI_GROSS_DIVERGENCE_THRESHOLD",
    "output_dir": "SOLARI_OUTPUT_DIR",
    "language_detector": "SOLARI_LANGUAGE_DETECTOR",
}


def _pick(key: str, cli: Mapping[str, Any], env: Mapping[str, str], default: Any) -> Any:
    if key in cli and cli[key] is not None:
        return cli[key]
    env_name = _ENV_MAP.get(key)
    if env_name and env_name in env and env[env_name] != "":
        return env[env_name]
    return default


def _as_int(value: Any, *, name: str, lo: int, hi: int) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidSelection(f"{name}: expected an integer, got {value!r}") from exc
    if not lo <= out <= hi:
        raise InvalidSelection(f"{name}: {out} outside [{lo}, {hi}]")
    return out


def _as_float(value: Any, *, name: str, lo: float, hi: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidSelection(f"{name}: expected a number, got {value!r}") from exc
    if not lo <= out <= hi:
        raise InvalidSelection(f"{name}: {out} outside [{lo}, {hi}]")
    return out


@dataclass(frozen=True)
class Config:
    # --- LLM (local, OpenAI-compatible) ---
    llm_base_url: str = "http://127.0.0.1:8000/v1"
    llm_model: str | None = None
    llm_decode: dict[str, Any] = field(default_factory=lambda: {"temperature": 0, "seed": None})
    llm_retries: int = 2
    # --- OCR (default from T013) ---
    ocr_engine: str = "tesseract"
    ocr_languages_override: tuple[str, ...] | None = None
    ocr_confidence_threshold: int = 70
    # --- reconciliation / validation thresholds ---
    reconcile_confidence_threshold: float = 0.75
    gross_divergence_threshold: float = 0.5
    # --- extraction paths ---
    enabled_extraction_paths: tuple[str, ...] = DEFAULT_ENABLED_PATHS
    # --- language detector (default from T013 = lingua) ---
    language_detector: str = "lingua"
    # --- native-reliability routing knobs (values tuned + surfaced by T049) ---
    native_reliability: dict[str, Any] = field(default_factory=dict)
    # --- paths ---
    output_dir: Path = field(default_factory=lambda: Path("./out"))
    resolution_store_path: Path | None = None

    @property
    def intermediates_dir(self) -> Path:
        return self.output_dir / "intermediates"

    def authorization_log_path(self, base: str) -> Path:
        """``<output-dir>/<base>.review-authorizations.jsonl`` (research §22.4)."""
        return self.output_dir / f"{base}.review-authorizations.jsonl"

    # --- resolution -------------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        *,
        cli: Mapping[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Config:
        cli = dict(cli or {})
        env = dict(env or {})

        octh = _as_int(
            _pick("ocr_confidence_threshold", cli, env, 70),
            name="ocr_confidence_threshold", lo=0, hi=100,
        )
        rcth = _as_float(
            _pick("reconcile_confidence_threshold", cli, env, 0.75),
            name="reconcile_confidence_threshold", lo=0.0, hi=1.0,
        )
        gdth = _as_float(
            _pick("gross_divergence_threshold", cli, env, 0.5),
            name="gross_divergence_threshold", lo=0.0, hi=1.0,
        )
        retries = _as_int(
            _pick("llm_retries", cli, env, 2), name="llm_retries", lo=0, hi=100,
        )

        lang_override = _pick("ocr_lang", cli, env, None)
        if isinstance(lang_override, str):
            lang_override = tuple(p.strip() for p in lang_override.split(",") if p.strip())
        elif isinstance(lang_override, Sequence) and not isinstance(lang_override, (str, bytes)):
            lang_override = tuple(lang_override)

        enabled = cli.get("enabled_extraction_paths") or DEFAULT_ENABLED_PATHS

        seed_raw = _pick("llm_seed", cli, env, None)
        seed = int(seed_raw) if seed_raw not in (None, "") else None

        out_dir = Path(str(_pick("output_dir", cli, env, "./out")))
        store = cli.get("resolution_store")
        store_path = Path(str(store)) if store else (out_dir / "resolutions.jsonl")

        return cls(
            llm_base_url=str(_pick("llm_base_url", cli, env, cls.llm_base_url)),
            llm_model=_pick("llm_model", cli, env, None),
            llm_decode={"temperature": 0, "seed": seed},
            llm_retries=retries,
            ocr_engine=str(_pick("ocr_engine", cli, env, "tesseract")),
            ocr_languages_override=lang_override,
            ocr_confidence_threshold=octh,
            reconcile_confidence_threshold=rcth,
            gross_divergence_threshold=gdth,
            enabled_extraction_paths=tuple(enabled),
            language_detector=str(_pick("language_detector", cli, env, "lingua")),
            native_reliability=dict(cli.get("native_reliability") or {}),
            output_dir=out_dir,
            resolution_store_path=store_path,
        )

    def with_native_reliability(self, knobs: Mapping[str, Any]) -> Config:
        """Return a copy carrying the T049-tuned native-reliability knobs."""
        return replace(self, native_reliability=dict(knobs))

    # --- research §14 effective-input subset ----------------------------------

    def output_affecting_config(
        self, *, stage: str, llm_reachable: bool = False
    ) -> dict[str, Any]:
        """The research §14 output-affecting subset for ``stage`` ∈ {"extract", "validate"}.

        Only the settings that change artifact bytes. Excludes timeouts, ``base_url``,
        output dir, the resolution-store path, ``--json``, the review-UI path, and every
        Human-Review workflow *event*.
        """
        if stage not in {"extract", "validate"}:
            raise InvalidSelection(f"unknown output_affecting_config stage {stage!r}")

        base: dict[str, Any] = {
            "ocr_engine": self.ocr_engine,
            "ocr_languages_override": (
                list(self.ocr_languages_override)
                if self.ocr_languages_override is not None
                else None
            ),
            "ocr_confidence_threshold": self.ocr_confidence_threshold,
            "reconcile_confidence_threshold": self.reconcile_confidence_threshold,
            "enabled_extraction_paths": list(self.enabled_extraction_paths),
        }

        include_llm = llm_reachable if stage == "extract" else True
        if include_llm:
            base["llm_model"] = self.llm_model
            base["llm_decode"] = dict(self.llm_decode)

        if stage == "validate":
            base["gross_divergence_threshold"] = self.gross_divergence_threshold

        return base
