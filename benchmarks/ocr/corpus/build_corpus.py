"""OCR benchmark corpus generator (T007).

Every corpus page is a rasterized image whose transcription is **exact by
construction**: the text below is authored here, rendered to a PNG, and written
verbatim to ground_truth/<name>.json. That is the "hand-verified transcription"
the benchmark scores against.

Why fully synthetic (see corpus/README.md): the repo's real long-form sample
(`Convencao_MARQUEZ_REGISTRADA_1.pdf`) carries a *degraded OCR* text layer of its
own, so it cannot serve as authoritative ground truth for scoring OCR engines.
Synthetic pages with exact ground truth make the benchmark rigorous and
reproducible; layout/degradation is modelled deliberately per category.

Categories (research §4.1): PT accents/diacritics; small text; numeric & monetary;
simple table; degraded/scanned; image-only; mixed/hybrid native-text + OCR region;
2 target-representative multi-column legal layouts.

REOPENED 2026-09-07 — the primary benchmark languages are now Portuguese, English
and Spanish (spec Clarifications 2026-09-07). Four pages added: ``en_text_01``
(clean English), ``es_diacritics_01`` (Spanish accents / punctuation),
``es_numeric_01`` (Spanish monetary), and ``latin_coverage_01`` — a FR/IT/DE
character-representability guard that is **not** a primary scored language
dimension (``scored: false`` in its ground truth; excluded from per-language
aggregation). Structural / degraded / table fixtures are not duplicated per
language: Portuguese keeps the deepest category matrix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
GT_DIR = HERE.parent / "ground_truth"

_TTF_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in _TTF_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


# US-Letter at ~150 dpi
PAGE = (1275, 1650)
MARGIN = 110


@dataclass
class Page:
    name: str
    category: str
    language: str
    reading_order: str
    lines: list[str]
    columns: list[list[str]] = field(default_factory=list)  # for multi-column pages
    font_size: int = 34
    degrade: bool = False
    #: False => character-coverage guard only, NOT a primary scored language
    #: dimension (excluded from PT/EN/ES per-language aggregation — research §4.1).
    scored: bool = True

    @property
    def text(self) -> str:
        if self.columns:
            return "\n".join("\n".join(col) for col in self.columns)
        return "\n".join(self.lines)


PAGES: list[Page] = [
    Page(
        "pt_diacritics_01", "pt_diacritics", "pt", "top-to-bottom",
        [
            "AÇÃO E CORAÇÃO",
            "As informações a seguir são de responsabilidade do declarante.",
            "José Antônio da Conceição, órfão, brasileiro, residente à Rua Ipê.",
            "Não há óbice à averbação; três irmãos assinam em conjunto.",
            "Observação: acentuação aguda (á), grave (à), circunflexa (â), til (ã).",
        ],
    ),
    Page(
        "small_text_01", "small_text", "pt", "top-to-bottom",
        [
            "Parágrafo único. O disposto neste artigo aplica-se, no que couber, às",
            "unidades autônomas e às áreas de uso comum, observada a fração ideal",
            "atribuída a cada condômino no instrumento de instituição do condomínio,",
            "bem como as deliberações regularmente tomadas em assembleia geral.",
        ],
        font_size=20,
    ),
    Page(
        "numeric_monetary_01", "numeric_monetary", "pt", "top-to-bottom",
        [
            "Valor total da transação: R$ 1.234.567,89",
            "Taxa condominial mensal: R$ 987,50 (novecentos e oitenta e sete reais)",
            "Multa de 2% sobre R$ 10.000,00 corresponde a R$ 200,00",
            "Parcelamento: 12x de R$ 999,99, totalizando R$ 11.999,88",
            "Índices: 0,5% | 1,25% | 100% | USD 45,000.00 | EUR 3.141,59",
        ],
    ),
    Page(
        "simple_table_01", "simple_table", "pt", "top-to-bottom",
        [
            "Item            Qtd     Unit (R$)      Total (R$)",
            "Bloco A          1       12.500,00     12.500,00",
            "Bloco B          3        4.750,00     14.250,00",
            "Garagem         12          350,00      4.200,00",
            "TOTAL GERAL                            30.950,00",
        ],
        font_size=30,
    ),
    Page(
        "degraded_scan_01", "degraded_scan", "pt", "top-to-bottom",
        [
            "DECLARAÇÃO DE QUITAÇÃO",
            "Declaro, para os devidos fins, que o valor de R$ 8.750,00 foi",
            "integralmente quitado na data de 03 de março de 2026.",
            "Assinatura do credor: ______________________",
        ],
        degrade=True,
    ),
    Page(
        "image_only_01", "image_only", "pt", "top-to-bottom",
        [
            "ESCRITURA PÚBLICA DE COMPRA E VENDA",
            "Aos sete dias do mês de setembro do ano de dois mil e vinte e seis,",
            "nesta cidade de São Paulo, perante mim, Tabelião, compareceram as",
            "partes entre si justas e contratadas, a saber: o outorgante vendedor e",
            "o outorgado comprador, ambos maiores e capazes.",
        ],
    ),
    Page(
        "hybrid_native_ocr_01", "hybrid_native_ocr", "pt", "top-to-bottom",
        [
            "REGISTRO CIVIL DAS PESSOAS NATURAIS",
            "Selo Digital de Fiscalização nº 4471-A-0092",
            "Emolumentos: R$ 27,50    Taxa de Fiscalização: R$ 5,10",
            "Confira a autenticidade em: selo.tjsp.jus.br",
        ],
        font_size=30,
    ),
    Page(
        "multicolumn_legal_01", "multicolumn_legal", "pt",
        "left column top-to-bottom, then right column top-to-bottom",
        [],
        columns=[
            [
                "CAPÍTULO I",
                "DA INSTITUIÇÃO",
                "",
                "Art. 1º Fica instituído,",
                "sob a forma de condomínio",
                "edilício, o empreendimento",
                "denominado “Marquez Alto",
                "do Ipiranga”, situado na",
                "Rua das Palmeiras, nº 210.",
                "",
                "Art. 2º O condomínio",
                "compõe-se de 4 (quatro)",
                "blocos residenciais e área",
                "comum de lazer.",
            ],
            [
                "CAPÍTULO II",
                "DAS DESPESAS",
                "",
                "Art. 3º As despesas",
                "ordinárias serão rateadas",
                "entre os condôminos na",
                "proporção da fração ideal.",
                "",
                "Parágrafo único. As",
                "despesas extraordinárias",
                "dependem de aprovação em",
                "assembleia por maioria",
                "qualificada de 2/3 dos",
                "presentes.",
            ],
        ],
        font_size=26,
    ),
    Page(
        "multicolumn_legal_02", "multicolumn_legal", "pt",
        "left column top-to-bottom, then right column top-to-bottom",
        [],
        columns=[
            [
                "CAPÍTULO III",
                "DA ADMINISTRAÇÃO",
                "",
                "Art. 4º O condomínio será",
                "administrado por um síndico,",
                "eleito em assembleia geral",
                "para mandato de 2 anos,",
                "permitida a reeleição.",
                "",
                "Art. 5º Compete ao síndico",
                "representar o condomínio",
                "ativa e passivamente.",
            ],
            [
                "CAPÍTULO IV",
                "DAS PENALIDADES",
                "",
                "Art. 6º O condômino que",
                "não cumprir seus deveres",
                "pagará multa equivalente a",
                "R$ 500,00 por infração.",
                "",
                "Art. 7º Em caso de",
                "reincidência, a multa será",
                "elevada ao quíntuplo, sem",
                "prejuízo das perdas e danos.",
            ],
        ],
        font_size=26,
    ),
    # ---- primary benchmark languages: English + Spanish (added 2026-09-07) --------
    Page(
        "en_text_01", "en_text", "en", "top-to-bottom",
        [
            "THE QUARTERLY REPORT",
            "The Board’s decision, reached after review, was unanimous and final.",
            "“We project revenue of $1,234.56 this year,” the chair noted.",
            "Cross-border fees rose to £1,000 — a 4.5% year-over-year increase.",
            "Well-founded, cost-effective, time-limited measures were approved.",
            "The efficient workflow was finalized before the office closed.",
        ],
        font_size=32,
    ),
    Page(
        "es_diacritics_01", "es_diacritics", "es", "top-to-bottom",
        [
            "COMUNICACIÓN OFICIAL EN ESPAÑOL",
            "El señor pregunta: ¿Cómo está su corazón después de un año difícil?",
            "¡Hola! Un niño pequeño y un pingüino jugaban juntos en el jardín.",
            "La niña dijo: «Añoran la canción tradicional española del pueblo».",
            "Vocales acentuadas: á é í ó ú; diéresis: ü; letra eñe: ñ.",
        ],
        font_size=32,
    ),
    Page(
        "es_numeric_01", "es_numeric", "es", "top-to-bottom",
        [
            "FACTURA Y LIQUIDACIÓN MENSUAL",
            "Importe total de la operación: € 1.234,56",
            "Cuota mensual: € 987,50 (novecientos ochenta y siete euros)",
            "Recargo del 2% sobre € 10.000,00 equivale a € 200,00",
            "Índices aplicados: 0,5% | 1,25% | 100% | USD 45,000.00",
        ],
        font_size=32,
    ),
    # ---- FR/IT/DE character-coverage guard — NOT a primary scored dimension ------
    Page(
        "latin_coverage_01", "latin_coverage", "mul", "top-to-bottom",
        [
            "COBERTURA DE CARACTERES LATINOS (FR / IT / DE)",
            "Français : à â ç é è ê ë î ï ô û ù ü œ — déjà, forêt, garçon, cœur.",
            "Italiano : à è é ì î ò ó ù — città, perché, così, virtù, sarà.",
            "Deutsch : ä ö ü ß Ä Ö Ü — Straße, Grüße, Fußgänger, schön.",
        ],
        font_size=30,
        scored=False,
    ),
]


def _render(page: Page) -> Image.Image:
    img = Image.new("RGB", PAGE, "white")
    d = ImageDraw.Draw(img)
    font = _font(page.font_size)
    lh = int(page.font_size * 1.55)
    if page.columns:
        col_w = (PAGE[0] - 2 * MARGIN - 60) // 2
        for ci, col in enumerate(page.columns):
            x = MARGIN + ci * (col_w + 60)
            y = MARGIN
            for line in col:
                d.text((x, y), line, fill="black", font=font)
                y += lh
    else:
        y = MARGIN
        for line in page.lines:
            d.text((MARGIN, y), line, fill="black", font=font)
            y += lh
    if page.degrade:
        import random

        rnd = random.Random(7)
        px = img.load()
        for _ in range(70000):
            xx, yy = rnd.randrange(PAGE[0]), rnd.randrange(PAGE[1])
            v = rnd.randrange(70, 190)
            px[xx, yy] = (v, v, v)
        img = img.filter(ImageFilter.GaussianBlur(1.1))
        img = Image.eval(img, lambda c: int(40 + c * 0.72))  # lower contrast
    return img


def build_corpus() -> list[Path]:
    HERE.mkdir(parents=True, exist_ok=True)
    GT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for page in PAGES:
        img_path = HERE / f"{page.name}.png"
        _render(page).save(img_path)
        gt = {
            "name": page.name,
            "category": page.category,
            "language": page.language,
            "reading_order": page.reading_order,
            "text": page.text,
            "lines": (
                [ln for col in page.columns for ln in col if ln]
                if page.columns
                else [ln for ln in page.lines if ln]
            ),
            "columns": page.columns or None,
            "scored": page.scored,
            "source": "synthetic (benchmarks/ocr/corpus/build_corpus.py) — exact ground truth",
        }
        gt_path = GT_DIR / f"{page.name}.json"
        gt_path.write_text(json.dumps(gt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        written.append(img_path)
    return written


if __name__ == "__main__":
    for p in build_corpus():
        print(p.relative_to(HERE.parent), p.stat().st_size, "bytes")
