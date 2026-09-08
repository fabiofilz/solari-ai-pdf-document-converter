"""OCR benchmark harness (T012) — reproducible, seed-pinned.

**REOPENED 2026-09-07.** ``python -m benchmarks.ocr.run`` scores every available
engine on every corpus page against the exact ground truth, then:

* aggregates fidelity **overall** and **per primary language** (PT / EN / ES);
* evaluates each engine×language against the AUTHORITATIVE per-language
  acceptance floor (``benchmarks.ocr.metrics.LANGUAGE_ACCEPTANCE_FLOOR`` /
  research §4.1) — deterministic PASS/FAIL, plus a "materially worse" flag
  (fails ≥1 applicable criterion, absolute — never relative to the other engine);
* reports the ``latin_coverage_01`` FR/IT/DE page as a **compatibility
  observation only** (not scored, not gated);
* runs the language-detection sub-metric across {langdetect (seed 0), lingua}
  on the scored PT/EN/ES pages, overall and per language;
* runs a two-run determinism self-check (OCR recognition is re-executed on each
  pass — the result cache is cleared between them);
* writes ``benchmarks/ocr/RESULTS.md`` (the GATE decision block is filled by T013).

RapidOCR uses the **multilingual Latin** recognition model from
``benchmarks/ocr/models/`` (explicit ``rec_model_path`` / ``rec_keys_path``,
zero runtime download) — never the bundled Chinese model.
"""

from __future__ import annotations

import atexit
import gc
import json
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from benchmarks.ocr import metrics
from solari_converter.extract.ocr_engines.base import OcrEngine
from solari_converter.extract.ocr_engines.rapidocr_engine import RapidOcrEngine
from solari_converter.extract.ocr_engines.tesseract_engine import TesseractEngine

HERE = Path(__file__).resolve().parent
CORPUS_DIR = HERE / "corpus"
GT_DIR = HERE / "ground_truth"
MODELS_DIR = HERE / "models"
RESULTS_MD = HERE / "RESULTS.md"

LATIN_MODEL_PATH = MODELS_DIR / "latin_PP-OCRv3_rec_infer.onnx"
LATIN_DICT_PATH = MODELS_DIR / "latin_dict.txt"

# one clean page per primary benchmark language (degraded fixtures are not
# duplicated per language — research §4.1 / T007)
SMOKE_CLEAN_PAGES = {
    "pt": CORPUS_DIR / "pt_diacritics_01.png",
    "en": CORPUS_DIR / "en_text_01.png",
    "es": CORPUS_DIR / "es_diacritics_01.png",
}
DEGRADED_SMOKE_PAGE = CORPUS_DIR / "degraded_scan_01.png"
# back-compat aliases
CLEAN_SMOKE_PAGE = SMOKE_CLEAN_PAGES["pt"]

SEED = 0
_LANG_SUBSET = ("pt", "en", "es", "fr", "de", "it")
_TABLE_CATEGORIES = {"simple_table"}


def _rapidocr() -> RapidOcrEngine:
    return RapidOcrEngine(rec_model_path=LATIN_MODEL_PATH, rec_keys_path=LATIN_DICT_PATH)


_ENGINE_CACHE: list[OcrEngine] | None = None
#: per-process OCR result cache — keyed by (engine name, page stem). It lets the
#: two ``run_benchmark()`` calls *inside a single pass* (per-engine scoring + the
#: reference-engine detector pass) avoid re-recognising the same page, and lets
#: the acceptance smoke reuse the benchmark's recognitions. It is **cleared
#: before each pass of ``determinism_selfcheck()``** so that check exercises real,
#: independent OCR execution — it is not a determinism shortcut. Engine/session
#: objects live in ``_ENGINE_CACHE`` and are reused (avoids an onnxruntime
#: session-teardown race on macOS/arm64).
_OCR_CACHE: dict[tuple[str, str], list] = {}


def load_engines() -> list[OcrEngine]:
    global _ENGINE_CACHE
    if _ENGINE_CACHE is None:
        _ENGINE_CACHE = [e for e in (TesseractEngine(), _rapidocr()) if e.is_available()]
    return list(_ENGINE_CACHE)


def _recognize(engine: OcrEngine, page_stem: str, language: str) -> list:
    key = (engine.name, page_stem)
    if key not in _OCR_CACHE:
        _OCR_CACHE[key] = engine.recognize(str(CORPUS_DIR / f"{page_stem}.png"), [language])
    return _OCR_CACHE[key]


@atexit.register
def _drop_engine_cache() -> None:
    """Release ONNX sessions while the interpreter is still healthy."""
    global _ENGINE_CACHE
    _OCR_CACHE.clear()
    _ENGINE_CACHE = None
    gc.collect()


# --------------------------------------------------------------------------------------
# language detectors
# --------------------------------------------------------------------------------------

def _langdetect(text: str) -> str:
    from langdetect import DetectorFactory, detect

    DetectorFactory.seed = SEED
    try:
        return detect(text)
    except Exception:
        return "und"


_lingua_detector = None


def _lingua(text: str) -> str:
    global _lingua_detector
    if _lingua_detector is None:
        from lingua import Language, LanguageDetectorBuilder

        by_iso = {
            "pt": Language.PORTUGUESE, "en": Language.ENGLISH, "es": Language.SPANISH,
            "fr": Language.FRENCH, "de": Language.GERMAN, "it": Language.ITALIAN,
        }
        langs = [by_iso[c] for c in _LANG_SUBSET]
        _lingua_detector = LanguageDetectorBuilder.from_languages(*langs).build()
    lang = _lingua_detector.detect_language_of(text or "")
    return lang.iso_code_639_1.name.lower() if lang else "und"


# --------------------------------------------------------------------------------------
# per-page scoring
# --------------------------------------------------------------------------------------

def _ground_truth(name: str) -> dict:
    return json.loads((GT_DIR / f"{name}.json").read_text())


def _reading_order_tau(gt_lines: list[str], ocr_lines: list[str]) -> float:
    if len(gt_lines) < 2 or not ocr_lines:
        return 1.0
    seq: list[int] = []
    for oc in ocr_lines:
        best_i, best_s = 0, -1.0
        for i, gl in enumerate(gt_lines):
            s = fuzz.ratio(oc, gl)
            if s > best_s:
                best_i, best_s = i, s
        if best_s >= 40:
            seq.append(best_i)
    return metrics.reading_order_kendall_tau(list(range(len(gt_lines))), seq)


@dataclass
class PageScore:
    engine: str
    page: str
    category: str
    language: str
    scored: bool
    per_metric: dict[str, float]
    weighted: float
    ref_text: str
    ocr_text: str


def score_page(engine: OcrEngine, name: str) -> PageScore:
    gt = _ground_truth(name)
    ref_text: str = gt["text"]
    ref_lines: list[str] = gt["lines"]
    scored = gt.get("scored", True)
    # latin_coverage is a FR/IT/DE compatibility page — feed a representative
    # supported language so the (unscored) observation still exercises the model.
    lang_arg = gt["language"] if gt["language"] in _LANG_SUBSET else "fr"
    lines = _recognize(engine, name, lang_arg)
    hyp_lines = [ln.text for ln in lines]
    hyp_text = "\n".join(hyp_lines)

    ins, dele = metrics.insertion_deletion_rates(ref_text, hyp_text)
    pm: dict[str, float] = {
        "cer": metrics.cer(ref_text, hyp_text),
        "numeric_token_exact_match": metrics.numeric_token_exact_match(ref_text, hyp_text),
        "diacritic_accuracy": metrics.diacritic_accuracy(ref_text, hyp_text),
        "reading_order_kendall_tau": _reading_order_tau(ref_lines, hyp_lines),
        "insertion_rate": ins,
        "deletion_rate": dele,
    }
    if gt["category"] in _TABLE_CATEGORIES:
        pm["table_cell_cer"] = metrics.table_cell_cer(ref_lines, hyp_lines)
    return PageScore(
        engine.name, name, gt["category"], gt["language"], scored,
        pm, metrics.weighted_total(pm), ref_text, hyp_text,
    )


# --------------------------------------------------------------------------------------
# full run
# --------------------------------------------------------------------------------------

_AGG_KEYS = ("cer", "numeric_token_exact_match", "diacritic_accuracy",
             "reading_order_kendall_tau", "insertion_rate", "deletion_rate")


def _aggregate(scores: list[PageScore]) -> dict[str, float]:
    agg: dict[str, float] = {}
    for key in _AGG_KEYS:
        vals = [s.per_metric[key] for s in scores if key in s.per_metric]
        if vals:
            agg[key] = metrics._mean(vals)
    tbl = [s.per_metric["table_cell_cer"] for s in scores if "table_cell_cer" in s.per_metric]
    if tbl:
        agg["table_cell_cer"] = metrics._mean(tbl)
    return agg


def _lang_applicability(scores: list[PageScore], lang: str) -> tuple[bool, bool]:
    """(diacritic_applicable, numeric_applicable) for a primary language, from the
    union of that language's scored ground-truth pages."""
    texts = [s.ref_text for s in scores if s.language == lang and s.scored]
    joined = "\n".join(texts)
    return metrics.text_has_diacritics(joined), metrics.text_has_numeric_tokens(joined)


def _detector_accuracy(scores: list[PageScore], detect_fn) -> dict:
    """Overall + per-language accuracy of ``detect_fn`` on scored PT/EN/ES pages,
    detecting on each engine-output text."""
    per_lang: dict[str, list[int]] = {}
    hits = total = 0
    for s in scores:
        if not s.scored or s.language not in metrics.PRIMARY_LANGUAGES:
            continue
        ok = int(detect_fn(s.ocr_text) == s.language)
        per_lang.setdefault(s.language, []).append(ok)
        hits += ok
        total += 1
    return {
        "overall": (hits / total) if total else 0.0,
        "per_language": {lg: (sum(v) / len(v)) for lg, v in sorted(per_lang.items())},
    }


@dataclass
class EngineResult:
    name: str
    identity: dict
    per_page: dict = field(default_factory=dict)
    aggregate: dict = field(default_factory=dict)
    weighted_total: float = 0.0
    per_language: dict = field(default_factory=dict)
    language_floor: dict = field(default_factory=dict)
    regression_flags: dict = field(default_factory=dict)
    latin_coverage: dict = field(default_factory=dict)
    detectors: dict = field(default_factory=dict)


def _engine_identity(engine: OcrEngine) -> dict:
    if isinstance(engine, RapidOcrEngine):
        return engine.model_identity
    from solari_converter.extract.ocr_engines.tesseract_engine import _LANG_MAP

    return {
        "engine": engine.name,
        "version": _tess_version(),
        "traineddata_map": {k: v for k, v in _LANG_MAP.items()
                            if k in ("pt", "en", "es", "fr", "it", "de")},
    }


def _evaluate_engine(engine: OcrEngine) -> EngineResult:
    pages = sorted(p.stem for p in CORPUS_DIR.glob("*.png"))
    scores = [score_page(engine, name) for name in pages]
    scored = [s for s in scores if s.scored]

    res = EngineResult(engine.name, _engine_identity(engine))
    res.per_page = {
        s.page: {"category": s.category, "language": s.language, "scored": s.scored,
                 "weighted": round(s.weighted, 4),
                 **{k: round(v, 4) for k, v in s.per_metric.items()}}
        for s in scores
    }
    res.aggregate = _aggregate(scored)

    # language-detection sub-metric feeds language_detection_accuracy into the
    # aggregate weighted total (best of the two detectors, on this engine's text)
    det_ld = _detector_accuracy(scored, _langdetect)
    det_lg = _detector_accuracy(scored, _lingua)
    res.aggregate["language_detection_accuracy"] = max(det_ld["overall"], det_lg["overall"])
    res.weighted_total = metrics.weighted_total(res.aggregate)
    res.detectors = {"langdetect_seed0": det_ld, "lingua": det_lg}

    # per-language aggregation + §4.1 floor
    lang_pages = [{"language": s.language, "scored": s.scored, "metrics": s.per_metric}
                  for s in scores]
    res.per_language = metrics.per_language_aggregate(lang_pages)
    for lang, agg in res.per_language.items():
        # fold this language's detector accuracy into its weighted total too
        best_det = max(det_ld["per_language"].get(lang, 0.0), det_lg["per_language"].get(lang, 0.0))
        agg["language_detection_accuracy"] = best_det
        agg["weighted_total"] = metrics.weighted_total(agg)
        dia_ok, num_ok = _lang_applicability(scores, lang)
        res.language_floor[lang] = metrics.evaluate_language_floor(
            agg, diacritic_applicable=dia_ok, numeric_applicable=num_ok
        )
    res.regression_flags = metrics.language_regression_flags(res.language_floor)

    # latin_coverage — compatibility observation only
    for s in [x for x in scores if x.category == "latin_coverage"]:
        res.latin_coverage = {
            "page": s.page,
            "cer": round(s.per_metric["cer"], 4),
            "diacritic_accuracy": round(s.per_metric["diacritic_accuracy"], 4),
            "note": "FR/IT/DE character-coverage guard — not scored, not gated (research §4.1)",
        }
    return res


def run_benchmark() -> dict:
    engines = load_engines()
    pages = sorted(p.stem for p in CORPUS_DIR.glob("*.png"))
    results = {e.name: _evaluate_engine(e) for e in engines}

    # cross-engine language-detector comparison, on the first engine's PT/EN/ES text
    detectors: dict = {}
    if engines:
        ref_scores = [score_page(engines[0], n) for n in pages]
        detectors = {
            "reference_engine": engines[0].name,
            "langdetect_seed0": _detector_accuracy(
                [s for s in ref_scores if s.scored], _langdetect),
            "lingua": _detector_accuracy(
                [s for s in ref_scores if s.scored], _lingua),
            "engine_native": {"overall": 0.0, "per_language": {},
                              "note": "OCR reports script, not language"},
        }

    return {
        "seed": SEED,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "onnxruntime": _ort_info(),
        "engine_identity": {name: r.identity for name, r in results.items()},
        "corpus_pages": pages,
        "scored_pages": sorted(p for p in pages
                               if _ground_truth(p).get("scored", True)),
        "per_engine": {
            name: {
                "aggregate": r.aggregate,
                "weighted_total": r.weighted_total,
                "per_page": r.per_page,
                "per_language": r.per_language,
                "language_floor": r.language_floor,
                "regression_flags": r.regression_flags,
                "latin_coverage": r.latin_coverage,
                "detectors": r.detectors,
            }
            for name, r in results.items()
        },
        "language_detectors": detectors,
        "floor_definition": metrics.LANGUAGE_ACCEPTANCE_FLOOR,
    }


def _ort_info() -> str:
    try:
        import onnxruntime as ort

        return f"onnxruntime {ort.__version__} {ort.get_available_providers()}"
    except Exception:
        return "onnxruntime (unavailable)"


def _tess_version() -> str:
    try:
        import pytesseract

        return f"tesseract {pytesseract.get_tesseract_version()}"
    except Exception:
        return "tesseract (unavailable)"


def determinism_selfcheck() -> bool:
    """Two independent benchmark passes must produce byte-identical results.

    The OCR result cache (``_OCR_CACHE``) is cleared before **each** pass, so both
    passes re-execute engine recognition end to end — this checks *OCR*
    determinism, not merely harness determinism. The engine/session objects
    (``_ENGINE_CACHE``) are reused: recognition is a pure function of the image +
    model, so this stays offline and avoids an onnxruntime session-teardown race
    on macOS/arm64.
    """
    _OCR_CACHE.clear()
    a = _stable(run_benchmark())
    _OCR_CACHE.clear()
    b = _stable(run_benchmark())
    return a == b


def _stable(d: dict) -> str:
    scrub = {k: v for k, v in d.items() if k not in ("platform", "python", "onnxruntime")}
    # engine_identity carries absolute paths — keep only the stable identity bits
    ident = {}
    for name, val in scrub.get("engine_identity", {}).items():
        ident[name] = {k: v for k, v in val.items() if "path" not in k}
    scrub["engine_identity"] = ident
    return json.dumps(scrub, sort_keys=True)


# --------------------------------------------------------------------------------------
# RESULTS.md
# --------------------------------------------------------------------------------------

_METRIC_ORDER = ["cer", "diacritic_accuracy", "numeric_token_exact_match", "table_cell_cer",
                 "reading_order_kendall_tau", "insertion_rate", "deletion_rate",
                 "language_detection_accuracy"]
_DECISION_MARKER = "<!-- GATE:DECISION -->"
_PENDING_BLOCK = (
    "## Gate decision (T013)\n\n"
    "_Pending — recorded by T013 from the scores above per the research §4.1 "
    "engine-selection procedure._\n"
)


def _fmt(v) -> str:
    return "—" if v is None else f"{v:.4f}"


def _pf(ok) -> str:
    return "—" if ok is None else ("PASS" if ok else "**FAIL**")


def _floor_cell(criteria: dict, name: str) -> str:
    c = criteria.get(name, {})
    if not c.get("applicable"):
        return "n/a"
    return f"{c['value']:.4f} {_pf(c['pass'])}"


def write_results(data: dict, deterministic: bool) -> None:
    L: list[str] = []
    engs = list(data["per_engine"])
    L.append("# OCR Benchmark — RESULTS\n")
    L.append(f"- seed: `{data['seed']}`  |  python: `{data['python']}`  "
             f"|  platform: `{data['platform']}`  |  `{data['onnxruntime']}`")
    for name in engs:
        ident = data["engine_identity"][name]
        if name == "rapidocr":
            L.append(f"- **rapidocr**: `{ident['package']}` — recognition model "
                     f"`{ident['rec_model_name']}` (sha256 `{ident['rec_model_sha256'][:16]}…`, "
                     f"dict {ident['rec_dict_symbols']} symbols, {ident['rec_model_family']}); "
                     f"bundled `ch_PP-OCRv4_det` + `ch_ppocr_mobile_v2.0_cls` for "
                     f"detection/orientation")
        else:
            L.append(f"- **tesseract**: `{ident['version']}` — traineddata "
                     f"{ident['traineddata_map']}")
    L.append(f"- corpus: {len(data['corpus_pages'])} pages; "
             f"{len(data['scored_pages'])} scored "
             f"(`{', '.join(data['scored_pages'])}`); `latin_coverage_01` = FR/IT/DE "
             f"compatibility only (unscored)")
    L.append(f"- two-run determinism self-check (OCR re-executed each pass): "
             f"**{'PASS' if deterministic else 'FAIL'}**")
    f = data["floor_definition"]
    _num_min = f["numeric_token_exact_match_min"]
    L.append(f"- per-language acceptance floor (research §4.1): "
             f"`weighted_total ≥ {f['weighted_total_min']}`, `CER ≤ {f['cer_max']}`, "
             f"`diacritic_accuracy ≥ {f['diacritic_accuracy_min']}` (PT/ES slices), "
             f"`numeric_token_exact_match ≥ {_num_min}` (numeric slices)\n")

    # aggregate
    L.append("## Per-engine aggregate scores (all scored pages)\n")
    L.append("| metric | " + " | ".join(engs) + " |")
    L.append("|---|" + "|".join(["---"] * len(engs)) + "|")
    for m in _METRIC_ORDER:
        row = [m] + [_fmt(data["per_engine"][e]["aggregate"].get(m)) for e in engs]
        L.append("| " + " | ".join(row) + " |")
    _wt = " | ".join(f"**{data['per_engine'][e]['weighted_total']:.4f}**" for e in engs)
    L.append(f"| **weighted total (higher = better)** | {_wt} |\n")

    # per-language
    L.append("## Per-language fidelity — Portuguese / English / Spanish\n")
    for lang in metrics.PRIMARY_LANGUAGES:
        L.append(f"### {lang.upper()}\n")
        L.append("| metric | " + " | ".join(engs) + " |")
        L.append("|---|" + "|".join(["---"] * len(engs)) + "|")
        for m in _METRIC_ORDER:
            row = [m]
            for e in engs:
                row.append(_fmt(data["per_engine"][e]["per_language"].get(lang, {}).get(m)))
            L.append("| " + " | ".join(row) + " |")
        row = ["**weighted total**"]
        for e in engs:
            wt = data["per_engine"][e]["per_language"].get(lang, {}).get("weighted_total", 0.0)
            row.append(f"**{wt:.4f}**")
        L.append("| " + " | ".join(row) + " |\n")

    # §4.1 PASS/FAIL matrix
    L.append("## §4.1 per-language acceptance floor — PASS / FAIL\n")
    L.append("| engine × language | weighted_total | CER | diacritic_accuracy | numeric_token "
             "| **language verdict** | materially worse |")
    L.append("|---|---|---|---|---|---|---|")
    for e in engs:
        for lang in metrics.PRIMARY_LANGUAGES:
            fl = data["per_engine"][e]["language_floor"].get(lang, {})
            crit = fl.get("criteria", {})
            verdict = "**PASS**" if fl.get("pass") else "**FAIL**"
            worse = "yes" if data["per_engine"][e]["regression_flags"].get(lang) else "no"
            L.append(
                f"| {e} × {lang.upper()} | {_floor_cell(crit, 'weighted_total')} "
                f"| {_floor_cell(crit, 'cer')} | {_floor_cell(crit, 'diacritic_accuracy')} "
                f"| {_floor_cell(crit, 'numeric_token_exact_match')} | {verdict} | {worse} |"
            )
    L.append("")

    # latin_coverage
    L.append("## FR / IT / DE character-coverage (compatibility only — not scored)\n")
    L.append("| engine | page | CER | diacritic_accuracy | note |")
    L.append("|---|---|---|---|---|")
    for e in engs:
        lc = data["per_engine"][e]["latin_coverage"]
        if lc:
            L.append(f"| {e} | `{lc['page']}` | {lc['cer']:.4f} | "
                     f"{lc['diacritic_accuracy']:.4f} | {lc['note']} |")
    L.append("")

    # language detectors
    L.append("## Language-detector sub-metric (scored PT/EN/ES pages)\n")
    det = data["language_detectors"]
    if det:
        L.append(f"_Detected on `{det['reference_engine']}` OCR output._\n")
        L.append("| detector | overall | pt | en | es |")
        L.append("|---|---|---|---|---|")
        for key, label in (("langdetect_seed0", "langdetect (seed 0)"),
                           ("lingua", "lingua"), ("engine_native", "engine-native")):
            d = det[key]
            pl = d.get("per_language", {})
            L.append(f"| {label} | {d['overall']:.4f} | "
                     f"{_fmt(pl.get('pt'))} | {_fmt(pl.get('en'))} | {_fmt(pl.get('es'))} |")
    L.append("")

    # per-page
    L.append("## Per-page weighted score\n")
    L.append("| page | category | language | scored | " + " | ".join(engs) + " |")
    L.append("|---|---|---|---|" + "|".join(["---"] * len(engs)) + "|")
    first = engs[0]
    for name in data["corpus_pages"]:
        meta = data["per_engine"][first]["per_page"][name]
        row = [name, meta["category"], meta["language"], "yes" if meta["scored"] else "no"]
        row += [f"{data['per_engine'][e]['per_page'][name]['weighted']:.4f}" for e in engs]
        L.append("| " + " | ".join(row) + " |")
    L.append("")

    L.append(_DECISION_MARKER)
    L.append(_existing_decision_block())
    RESULTS_MD.write_text("\n".join(L) + "\n")


def _existing_decision_block() -> str:
    if RESULTS_MD.exists():
        text = RESULTS_MD.read_text()
        if _DECISION_MARKER in text:
            block = text.split(_DECISION_MARKER, 1)[1].lstrip("\n")
            if block.strip() and "_Pending" not in block:
                return block.rstrip() + "\n"
    return _PENDING_BLOCK


#: the OCR Benchmark Gate is a *two-engine* comparison — it is meaningless with
#: one engine and must never silently produce a single-engine RESULTS.md.
REQUIRED_ENGINES = {"tesseract", "rapidocr"}


def _require_two_engines() -> list[OcrEngine]:
    engines = load_engines()
    have = {e.name for e in engines}
    missing = REQUIRED_ENGINES - have
    if missing:
        print(
            "REFUSING to run the OCR Benchmark Gate — it is a two-engine comparison "
            f"and these engines are unavailable: {sorted(missing)}.\n"
            "  - tesseract: install the `tesseract` binary + "
            "`por eng spa fra ita deu` traineddata\n"
            "  - rapidocr : run "
            "`uv run python benchmarks/ocr/models/fetch_latin_model.py`\n"
            "RESULTS.md is left unchanged; no single-engine gate is claimed."
        )
    return engines


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--smoke" in argv:
        engines = _require_two_engines()
        if {e.name for e in engines} != REQUIRED_ENGINES:
            return 2
        pairs = [(lg, p) for lg, p in SMOKE_CLEAN_PAGES.items()] + [("pt", DEGRADED_SMOKE_PAGE)]
        for eng in engines:
            for lang, page in pairs:
                txt = " ".join(ln.text for ln in eng.recognize(str(page), [lang])).strip()
                status = "ok" if txt else "EMPTY"
                print(f"{eng.name:10s} {lang} {page.name:22s} -> {status} ({len(txt)} chars)")
                if not txt:
                    return 1
        print("smoke OK")
        return 0

    if {e.name for e in _require_two_engines()} != REQUIRED_ENGINES:
        return 2

    data = run_benchmark()
    deterministic = determinism_selfcheck()
    write_results(data, deterministic)
    print(f"wrote {RESULTS_MD.relative_to(HERE.parent.parent)}  "
          f"(determinism: {'PASS' if deterministic else 'FAIL'})")
    for eng, block in data["per_engine"].items():
        flags = [lg for lg, bad in block["regression_flags"].items() if bad]
        print(f"  {eng:10s} weighted_total = {block['weighted_total']:.4f}  "
              f"materially-worse: {flags or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
