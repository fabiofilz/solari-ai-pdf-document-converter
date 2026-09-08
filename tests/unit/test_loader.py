"""T034 — failing-first tests for the read-only PDF source loader (GREEN owner: **T034**).

Frozen behaviour (plan.md ``pdf/loader.py``, research §24 / M2, FR-004 edge / FR-058):

* the source PDF is opened **once** at the loader boundary and exposes a deterministic
  ``page_count`` and **1-based physical** page addressing;
* each independent extraction path gets a **read-only** handle to the *source* — never
  another path's output — so one path's interpretation can't become another's input;
* a missing / corrupted / encrypted source maps to :class:`SourceUnreadable` (exit 3);
  there is no silent partial success;
* opened resources are context-managed / closable — no leaked handles.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from reportlab.lib import pdfencrypt
from reportlab.pdfgen import canvas

from solari_converter.errors import EXIT_SOURCE_UNREADABLE, SourceUnreadable, exit_code_for


def _loader():
    import solari_converter.pdf.loader as loader  # GREEN owner: T034

    return loader


# --- deterministic local fixtures (no new dependency; reportlab is a dev dep) ----------

_PAGE_TEXT = ["first physical page", "second physical page", "third physical page"]


def _make_pdf(path: Path, *, pages: list[str] = _PAGE_TEXT, encrypt: bool = False) -> Path:
    kwargs = {}
    if encrypt:
        kwargs["encrypt"] = pdfencrypt.StandardEncryption("userpw", "ownerpw")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, **kwargs)
    for text in pages:
        c.drawString(72, 720, text)
        c.showPage()
    c.save()
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture
def good_pdf(tmp_path: Path) -> Path:
    return _make_pdf(tmp_path / "good.pdf")


# --- failure mapping -----------------------------------------------------------------


def test_missing_file_maps_to_source_unreadable(tmp_path: Path) -> None:
    with pytest.raises(SourceUnreadable) as exc:
        _loader().load_pdf(tmp_path / "nope.pdf")
    assert exit_code_for(exc.value) == EXIT_SOURCE_UNREADABLE


def test_corrupted_pdf_maps_to_source_unreadable(tmp_path: Path) -> None:
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.7\nnot really a pdf at all\n%%EOF\n")
    with pytest.raises(SourceUnreadable) as exc:
        _loader().load_pdf(bad)
    assert exit_code_for(exc.value) == EXIT_SOURCE_UNREADABLE


def test_truncated_pdf_maps_to_source_unreadable(tmp_path: Path, good_pdf: Path) -> None:
    truncated = tmp_path / "truncated.pdf"
    truncated.write_bytes(good_pdf.read_bytes()[:180])
    with pytest.raises(SourceUnreadable):
        _loader().load_pdf(truncated)


def test_encrypted_pdf_maps_to_source_unreadable(tmp_path: Path) -> None:
    enc = _make_pdf(tmp_path / "enc.pdf", pages=["secret"], encrypt=True)
    with pytest.raises(SourceUnreadable) as exc:
        _loader().load_pdf(enc)
    assert exit_code_for(exc.value) == EXIT_SOURCE_UNREADABLE


# --- page addressing ----------------------------------------------------------------


def test_page_count_is_deterministic(good_pdf: Path) -> None:
    with _loader().load_pdf(good_pdf) as src:
        assert src.page_count == 3
        assert src.page_count == 3  # stable on repeat access


def test_one_based_physical_page_access(good_pdf: Path) -> None:
    with _loader().load_pdf(good_pdf) as src:
        first = src.plumber_page(1)
        assert "first physical page" in (first.extract_text() or "")
        third = src.plumber_page(3)
        assert "third physical page" in (third.extract_text() or "")
        assert src.pdfium_page(1) is not None


def test_page_zero_and_out_of_range_are_rejected(good_pdf: Path) -> None:
    with _loader().load_pdf(good_pdf) as src:
        for bad in (0, -1, 4, 999):
            with pytest.raises((ValueError, IndexError)):
                src.plumber_page(bad)
            with pytest.raises((ValueError, IndexError)):
                src.pdfium_page(bad)


# --- read-only handles / path independence -----------------------------------------


def test_exposes_independent_source_handles(good_pdf: Path) -> None:
    with _loader().load_pdf(good_pdf) as src:
        assert src.plumber is not None
        assert src.pdfium is not None
        # distinct underlying objects — one path's handle is not the other's
        assert src.plumber is not src.pdfium


def test_repeated_page_reads_are_independent(good_pdf: Path) -> None:
    with _loader().load_pdf(good_pdf) as src:
        a = src.plumber_page(1).extract_text()
        _ = src.pdfium_page(1)
        b = src.plumber_page(1).extract_text()
        assert a == b  # a second path touching the source did not perturb the first


# --- resource management ----------------------------------------------------------


def test_context_manager_closes_handles(good_pdf: Path) -> None:
    loader = _loader()
    with loader.load_pdf(good_pdf) as src:
        assert src.page_count == 3
    assert src.closed is True


def test_explicit_close_is_idempotent(good_pdf: Path) -> None:
    src = _loader().load_pdf(good_pdf)
    src.close()
    src.close()
    assert src.closed is True
