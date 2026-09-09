"""Real-Docling smoke test for path A (T046) — run with ``-m acceptance``.

Uses a frozen local synthetic PDF (built at test time with ``reportlab``, no committed
binary) and the real, pre-fetched, digest-verified local model artifacts under
``SOLARI_DOCLING_ARTIFACTS_PATH`` (default ``.docling_models/`` at the repo root — see
``scripts/docling_models/README.md``). Proves Docling actually imports and runs on this
Python / platform, entirely offline, and produces genuine native-text evidence.

On a clean clone that has not run ``python scripts/fetch_docling_models.py``, this test
is **skipped** with an explicit reason — never a silent green, and never a weakened
offline check to make it pass anyway.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

pytestmark = pytest.mark.acceptance

from reportlab.pdfgen import canvas  # noqa: E402

from solari_converter.extract.docling_path import (  # noqa: E402
    REQUIRED_ARTIFACT_DIGESTS,
    DoclingExtractionPath,
    DoclingModelUnavailable,
    _resolve_artifacts_path,
    _verify_artifact_digests,
)


def _artifacts_ready() -> Path | None:
    """Prefer an explicitly-configured artifacts path (env var); fall back to
    ``scripts/fetch_docling_models.py``'s own default location as a convenience for a
    developer who just ran the setup script with no arguments. Skips (never fails) if
    neither is present/verified — a clean clone that has not run the setup script."""
    candidates = [_resolve_artifacts_path(None)]
    try:
        import fetch_docling_models  # scripts/ is on sys.path via conftest? -> see below

        candidates.append(fetch_docling_models.DEFAULT_ARTIFACTS_DIR)
    except ImportError:
        repo_root = Path(__file__).resolve().parents[2]
        candidates.append(repo_root / ".docling_models")

    for root in candidates:
        if root is None:
            continue
        try:
            _verify_artifact_digests(root, REQUIRED_ARTIFACT_DIGESTS)
        except DoclingModelUnavailable:
            continue
        return root
    return None


@pytest.fixture
def synthetic_pdf(tmp_path: Path) -> Path:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 720, "Section Heading Example")
    c.setFont("Helvetica", 11)
    c.drawString(72, 690, "This is the first line of body text on the page.")
    c.drawString(72, 674, "This is a second wrapped line of the same paragraph.")
    c.showPage()
    c.save()
    path = tmp_path / "smoke.pdf"
    path.write_bytes(buf.getvalue())
    return path


def test_real_docling_produces_native_text_evidence_offline(synthetic_pdf: Path) -> None:
    root = _artifacts_ready()
    if root is None:
        pytest.skip(
            "Docling model artifacts not fetched/verified — run "
            "`python scripts/fetch_docling_models.py` (setup-time only)."
        )

    path = DoclingExtractionPath(artifacts_path=root, device="cpu", num_threads=2)

    from solari_converter.pdf.loader import load_pdf

    with load_pdf(synthetic_pdf) as source:
        envelope = {
            "run_id": "0" * 16,
            "tool_version": "0.1.0",
            "source_pdf": str(synthetic_pdf),
            "source_sha256": "0" * 64,
            "page_selection": "all",
        }
        candidate = path.extract(source, envelope=envelope)

    assert candidate.technique == "docling"
    assert candidate.status == "ok"
    assert candidate.segments, "expected at least one native-text segment"
    texts = [s.text for s in candidate.segments]
    assert any("Section Heading Example" in t for t in texts)
    assert any("first line of body text" in t for t in texts)
    # literal fidelity: the two body lines must remain separate segments, never merged
    # into one normalized paragraph string (the exact behaviour this adapter avoids)
    assert not any("first line" in t and "second wrapped line" in t for t in texts)
    assert all(0 <= s.reading_order_index < len(candidate.segments) for s in candidate.segments)
    assert candidate.reading_order.technique == "docling"
    assert len(candidate.reading_order.order) == len(candidate.segments)

    # OCR isolation held for a real run too
    assert candidate.page_ocr == []
    for segment in candidate.segments:
        assert segment.source.origin_kind == "native_text"
        assert segment.source.ocr_confidence is None
