"""Synthetic fixture PDFs, generated at test time with reportlab / Pillow (T005).

No binary PDFs are committed — every fixture is built from code so its intent is
readable and its ground truth (tests/fixtures/manifests.py, T006) is exact.

``build_all(dest)`` writes all 14 PDFs and returns ``{name: Path}``.
Individual ``build_<name>(dest) -> Path`` builders are also exported.

Fidelity notes for the fixtures reportlab cannot express natively:
  * "image-only" pages are a Pillow-rendered raster embedded full-page with **no**
    text drawn — so there is genuinely no text layer;
  * ``missing_content_layer.pdf`` renders the full page as a raster (visible) and
    draws only a short fragment as real text (severe text-layer gap);
  * ``garbled_layer.pdf`` renders one region as a raster of clean text while the
    text layer for that region carries mojibake (a stand-in for a corrupted
    ToUnicode CMap — the *extracted* text is garbage, the *visible* text is fine).
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = LETTER

_TTF_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _pil_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _TTF_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _text_raster(lines: list[str], *, size: int = 26, dpi_scale: int = 2,
                 noise: int = 0, blur: bool = False) -> Image.Image:
    """Render ``lines`` to a LETTER-proportioned RGB image (no text layer once embedded)."""
    w = int(PAGE_W * dpi_scale)
    h = int(PAGE_H * dpi_scale)
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    font = _pil_font(size * dpi_scale // 2)
    y = int(0.75 * inch * dpi_scale)
    for line in lines:
        d.text((int(0.9 * inch * dpi_scale), y), line, fill="black", font=font)
        y += int(size * dpi_scale * 0.75)
    if noise:
        import random

        rnd = random.Random(1234)
        px = img.load()
        for _ in range(noise):
            x0, y0 = rnd.randrange(w), rnd.randrange(h)
            v = rnd.randrange(60, 180)
            px[x0, y0] = (v, v, v)
    if blur:
        from PIL import ImageFilter

        img = img.filter(ImageFilter.GaussianBlur(radius=dpi_scale * 0.6))
    return img


def _embed_full_page_image(c: canvas.Canvas, img: Image.Image) -> None:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    from reportlab.lib.utils import ImageReader

    c.drawImage(ImageReader(buf), 0, 0, width=PAGE_W, height=PAGE_H)


def _para(c: canvas.Canvas, x: float, y: float, text: str, *, font: str = "Helvetica",
          leading: float = 14) -> float:
    c.setFont(font, 11)
    for line in text.split("\n"):
        c.drawString(x, y, line)
        y -= leading
    return y


# --------------------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------------------

def build_native_text(dest: Path) -> Path:
    p = dest / "native_text.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(inch, PAGE_H - inch, "Native Text Document")
    _para(c, inch, PAGE_H - 1.5 * inch,
          "This page has a healthy, fully selectable native text layer. Every word\n"
          "here is present in the PDF content stream and extracts cleanly. It is the\n"
          "baseline for the native-text-reliability classifier (expected: no OCR).")
    c.showPage()
    c.save()
    return p


def build_agreement(dest: Path) -> Path:
    p = dest / "agreement.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)

    def header_footer(page_no: int) -> None:
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(inch, PAGE_H - 0.6 * inch, "CONFIDENTIAL — MASTER SERVICES AGREEMENT")
        c.drawRightString(PAGE_W - inch, PAGE_H - 0.6 * inch, "Rev. 2026-09")
        c.drawCentredString(PAGE_W / 2, 0.6 * inch, f"Page {page_no}")
        c.drawString(inch, 0.6 * inch, "MSA-2026 / Acme <-> Beta")

    # Page 1 — headings L1..L8 + nested lists + numbered clauses
    header_footer(1)
    y = PAGE_H - 1.2 * inch
    for lvl in range(1, 9):
        c.setFont("Helvetica-Bold", max(15 - lvl, 8))
        c.drawString(inch + (lvl - 1) * 6, y, f"{'#' * 0}{lvl}. Heading level {lvl}")
        y -= 18
    y -= 8
    c.setFont("Helvetica", 11)
    for i, item in enumerate(["First bullet", "Second bullet", "  - nested bullet a",
                              "  - nested bullet b"], 1):
        c.drawString(inch, y, ("• " + item.strip()) if not item.startswith("  ")
                     else ("   ◦ " + item.strip("- ").strip()))
        y -= 14
    for n, item in enumerate(["Numbered one", "Numbered two", "Numbered three"], 1):
        c.drawString(inch, y, f"{n}. {item}")
        y -= 14
    y -= 8
    for cl in ["1.1 The Provider shall deliver the Services with due care.",
               "1.2 Fees are payable within thirty (30) days of invoice.",
               "1.2.1 Late amounts accrue interest at 1% per month."]:
        c.drawString(inch, y, cl)
        y -= 14
    c.showPage()

    # Pages 2-4 — a 3-page table with a REPEATED header row
    rows_all = [["Item", "Qty", "Unit (USD)", "Line total (USD)"]]
    for i in range(1, 34):
        rows_all.append([f"SKU-{i:03d}", str(i % 5 + 1), f"{i * 3.5:,.2f}",
                         f"{(i % 5 + 1) * i * 3.5:,.2f}"])
    header = rows_all[0]
    body = rows_all[1:]
    per_page = 11
    for pidx, start in enumerate(range(0, len(body), per_page), start=2):
        header_footer(pidx)
        chunk = body[start:start + per_page]
        y = PAGE_H - 1.3 * inch
        c.setFont("Helvetica-Bold", 12)
        c.drawString(inch, y, "Schedule A — Line Items (continued)")
        y -= 22
        c.setFont("Helvetica-Bold", 10)
        col_x = [inch, inch + 1.8 * inch, inch + 2.7 * inch, inch + 3.9 * inch]
        for x, cell in zip(col_x, header):
            c.drawString(x, y, cell)
        y -= 14
        c.setFont("Helvetica", 10)
        for r in chunk:
            for x, cell in zip(col_x, r):
                c.drawString(x, y, cell)
            y -= 13
        c.showPage()
    c.save()
    return p


def build_merged_cells(dest: Path) -> Path:
    p = dest / "merged_cells.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(inch, PAGE_H - inch, "Table with merged / spanned cells")
    x0, y0 = inch, PAGE_H - 3.2 * inch
    w, h = 1.4 * inch, 0.4 * inch
    # A 3x3 grid where the top-left 2x2 is one merged cell.
    c.rect(x0, y0 + h, 2 * w, h)                       # merged header spanning 2 cols
    c.drawString(x0 + 6, y0 + h + 12, "Region (colspan=2)")
    c.rect(x0 + 2 * w, y0 + h, w, h)
    c.drawString(x0 + 2 * w + 6, y0 + h + 12, "Total")
    for r in range(2):
        for col in range(3):
            c.rect(x0 + col * w, y0 - r * h, w, h)
            c.drawString(x0 + col * w + 6, y0 - r * h + 12, f"r{r}c{col}")
    c.showPage()
    c.save()
    return p


def build_multipage_table(dest: Path) -> Path:
    p = dest / "multipage_table.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    header = ["Date", "Description", "Amount (USD)"]
    rows = [[f"2026-{(i % 12) + 1:02d}-05", f"Transaction {i}", f"{i * 12.75:,.2f}"]
            for i in range(1, 41)]
    per_page = 14
    for pidx, start in enumerate(range(0, len(rows), per_page), start=1):
        y = PAGE_H - 1.2 * inch
        c.setFont("Helvetica-Bold", 12)
        c.drawString(inch, y, "Ledger extract")
        y -= 20
        c.setFont("Helvetica-Bold", 10)
        for j, cell in enumerate(header):
            c.drawString(inch + j * 2.1 * inch, y, cell)
        y -= 14
        c.setFont("Helvetica", 10)
        for r in rows[start:start + per_page]:
            for j, cell in enumerate(r):
                c.drawString(inch + j * 2.1 * inch, y, cell)
            y -= 13
        c.drawCentredString(PAGE_W / 2, 0.6 * inch, f"Page {pidx}")
        c.showPage()
    c.save()
    return p


def build_two_column(dest: Path) -> Path:
    p = dest / "two_column.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    # Page 1 — geometrically clear two columns with a wide gutter.
    c.setFont("Helvetica", 10)
    left = ["Left column line %d — clearly separated by a wide gutter." % i for i in range(1, 18)]
    right = ["Right column line %d — no ambiguity about reading order." % i for i in range(1, 18)]
    y = PAGE_H - inch
    for ln in left:
        c.drawString(0.8 * inch, y, ln)
        y -= 13
    y = PAGE_H - inch
    for ln in right:
        c.drawString(4.6 * inch, y, ln)
        y -= 13
    c.showPage()
    # Page 2 — ambiguous: narrow gutter + a full-width line crossing both columns.
    c.setFont("Helvetica", 10)
    y = PAGE_H - inch
    for i in range(1, 16):
        c.drawString(1.0 * inch, y, f"col A {i} ...")
        c.drawString(3.4 * inch, y, f"col B {i} ...")
        y -= 13
    c.drawString(1.0 * inch, y - 10, "A FULL-WIDTH SENTENCE THAT SPANS THE WHOLE PAGE WIDTH HERE")
    c.showPage()
    c.save()
    return p


def build_scanned(dest: Path) -> Path:
    p = dest / "scanned.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    img = _text_raster(["ESCRITURA PÚBLICA", "", "Aos sete dias do mês de setembro,",
                        "compareceu a parte outorgante para,",
                        "de livre e espontânea vontade, declarar..."])
    _embed_full_page_image(c, img)  # no text drawn -> image-only page
    c.showPage()
    c.save()
    return p


def build_hybrid(dest: Path) -> Path:
    p = dest / "hybrid.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    # Top half: reliable native text.
    c.setFont("Helvetica-Bold", 14)
    c.drawString(inch, PAGE_H - inch, "Hybrid page — native heading and body")
    _para(c, inch, PAGE_H - 1.4 * inch,
          "This upper region is a clean native text layer and MUST be kept verbatim.\n"
          "Only the stamped region below needs OCR; OCR must not touch this text.")
    # Bottom region: an image-only stamp with NO text layer.
    stamp = _text_raster(["REGISTRO CIVIL", "Selo de autenticidade nº 4471-A",
                          "Valor: R$ 27,50"], size=22)
    stamp = stamp.crop((0, 0, stamp.width, stamp.height // 3))
    buf = io.BytesIO()
    stamp.save(buf, format="PNG")
    buf.seek(0)
    from reportlab.lib.utils import ImageReader

    c.drawImage(ImageReader(buf), inch, inch, width=PAGE_W - 2 * inch, height=2.2 * inch)
    c.showPage()
    c.save()
    return p


def build_missing_content_layer(dest: Path) -> Path:
    p = dest / "missing_content_layer.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    visible = ["CONTRATO DE PRESTAÇÃO DE SERVIÇOS",
               "Cláusula 1 — Do objeto: prestação de serviços de consultoria.",
               "Cláusula 2 — Do preço: R$ 12.500,00 mensais.",
               "Cláusula 3 — Do prazo: 12 (doze) meses, renováveis.",
               "Cláusula 4 — Da rescisão: mediante aviso de 30 dias."]
    _embed_full_page_image(c, _text_raster(visible))
    # Text layer carries only a tiny fragment -> severe gap vs the visible page.
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(1, 1, 1)  # invisible-ish, but still a real text object
    c.drawString(inch, inch, "CONTRATO")
    c.showPage()
    c.save()
    return p


def build_garbled_layer(dest: Path) -> Path:
    p = dest / "garbled_layer.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(inch, PAGE_H - inch, "Document with one garbled region")
    _para(c, inch, PAGE_H - 1.4 * inch,
          "The first paragraph extracts cleanly. The boxed region below shows clean\n"
          "text visually but its text layer is mojibake (stand-in for a broken ToUnicode).")
    clean = "Locação de imóvel residencial — aluguel mensal de R$ 3.200,00"
    # visible = clean raster
    raster = _text_raster([clean], size=18)
    raster = raster.crop((0, 0, raster.width, raster.height // 8))
    buf = io.BytesIO()
    raster.save(buf, format="PNG")
    buf.seek(0)
    from reportlab.lib.utils import ImageReader

    c.drawImage(ImageReader(buf), inch, 3 * inch, width=PAGE_W - 2 * inch, height=0.5 * inch)
    # text layer for that region: mojibake of the same string
    mojibake = clean.encode("utf-8").decode("latin-1")
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(1, 1, 1)
    c.drawString(inch, 3.1 * inch, mojibake)
    c.showPage()
    c.save()
    return p


def build_pt_diacritics(dest: Path) -> Path:
    p = dest / "pt_diacritics.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    c.setFont("Helvetica", 12)
    lines = ["Ação, coração, pão, mãe, informações, José, Ceará.",
             "Àgua não; à vista; três irmãos; ré­u; ç cedilha.",
             "Português: acentuação aguda (á), grave (à), circunflexa (â), til (ã).",
             "Ünïcödé edge: naïve, façade, Zürich."]
    y = PAGE_H - inch
    for ln in lines:
        c.drawString(inch, y, ln)
        y -= 18
    c.showPage()
    c.save()
    return p


def build_monetary(dest: Path) -> Path:
    p = dest / "monetary.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    c.setFont("Helvetica", 12)
    lines = ["Total devido: R$ 1.234.567,89",
             "USD 45,000.00 and EUR 3.141,59",
             "Multa de 2% sobre R$ 10.000,00 = R$ 200,00",
             "Parcelas: 12x de R$ 999,99 (total R$ 11.999,88)",
             "Percentuais: 0,5% | 1,25% | 100%"]
    y = PAGE_H - inch
    for ln in lines:
        c.drawString(inch, y, ln)
        y -= 18
    c.showPage()
    c.save()
    return p


def build_degraded_scan(dest: Path) -> Path:
    p = dest / "degraded_scan.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    img = _text_raster(
        ["DECLARAÇÃO", "", "Declaro para os devidos fins que o valor de",
         "R$ 8.750,00 foi integralmente quitado em 03/2026.",
         "Assinatura: ____________________"],
        size=24, noise=45000, blur=True,
    )
    _embed_full_page_image(c, img)
    c.showPage()
    c.save()
    return p


def build_clean_transform(dest: Path) -> Path:
    p = dest / "clean_transform.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    # reflow: visually wrapped lines that form one paragraph
    c.setFont("Helvetica-Bold", 14)
    c.drawString(inch, PAGE_H - inch, "Section Title")
    c.setFont("Helvetica", 11)
    wrapped = ["This is a single logical paragraph that has been hard-",
               "wrapped across several visual lines and also contains a com-",
               "pound-word hyphen that must be preserved, unlike the line-",
               "break hyphens above it."]
    y = PAGE_H - 1.4 * inch
    for ln in wrapped:
        c.drawString(inch, y, ln)
        y -= 13
    y -= 10
    for n, it in enumerate(["Article 1 — scope", "Article 2 — term", "Article 3 — fees"], 1):
        c.drawString(inch, y, f"{n}. {it}")
        y -= 13
    # a small two-page-safe table start near the bottom (stitch candidate, legitimate)
    y -= 12
    c.setFont("Helvetica-Bold", 10)
    c.drawString(inch, y, "Milestone")
    c.drawString(inch + 2 * inch, y, "Due")
    y -= 12
    c.setFont("Helvetica", 10)
    for r in [("Kickoff", "2026-10-01"), ("Draft", "2026-11-15"), ("Final", "2026-12-20")]:
        c.drawString(inch, y, r[0])
        c.drawString(inch + 2 * inch, y, r[1])
        y -= 12
    c.showPage()
    c.save()
    return p


def build_conflict_literal(dest: Path) -> Path:
    p = dest / "conflict_literal.pdf"
    c = canvas.Canvas(str(p), pagesize=LETTER)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(inch, PAGE_H - inch, "Clause with a low-legibility number")
    # A clause whose amount is rendered in a way that two extractors read differently:
    # visible raster says "R$ 4.800,00"; a faint text layer says "R$ 4.300,00".
    raster = _text_raster(["Cláusula 5 — O aluguel mensal é de R$ 4.800,00 (quatro mil e",
                           "oitocentos reais), reajustado anualmente pelo IGP-M."], size=16)
    raster = raster.crop((0, 0, raster.width, raster.height // 6))
    buf = io.BytesIO()
    raster.save(buf, format="PNG")
    buf.seek(0)
    from reportlab.lib.utils import ImageReader

    c.drawImage(ImageReader(buf), inch, PAGE_H - 2.4 * inch, width=PAGE_W - 2 * inch,
                height=0.8 * inch)
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.75, 0.75, 0.75)
    c.drawString(inch, PAGE_H - 2.0 * inch,
                 "Clausula 5 - O aluguel mensal e de R$ 4.300,00 (quatro mil e trezentos reais),")
    c.showPage()
    c.save()
    return p


_BUILDERS = {
    "native_text.pdf": build_native_text,
    "agreement.pdf": build_agreement,
    "merged_cells.pdf": build_merged_cells,
    "multipage_table.pdf": build_multipage_table,
    "two_column.pdf": build_two_column,
    "scanned.pdf": build_scanned,
    "hybrid.pdf": build_hybrid,
    "missing_content_layer.pdf": build_missing_content_layer,
    "garbled_layer.pdf": build_garbled_layer,
    "pt_diacritics.pdf": build_pt_diacritics,
    "monetary.pdf": build_monetary,
    "degraded_scan.pdf": build_degraded_scan,
    "clean_transform.pdf": build_clean_transform,
    "conflict_literal.pdf": build_conflict_literal,
}


def build_all(dest: Path) -> dict[str, Path]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    return {name: fn(dest) for name, fn in _BUILDERS.items()}


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("_fixtures_out")
    built = build_all(out)
    for name, path in built.items():
        print(f"{name:28s} {path.stat().st_size:>8d} bytes")
