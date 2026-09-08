"""Reproducible, setup-time acquisition of the RapidOCR multilingual Latin
recognition model + dictionary (T010).

Run once, at setup time — **never at document-processing runtime** (the no-egress
and no-model-download guards in tests/conftest.py and T134 enforce that):

    python benchmarks/ocr/models/fetch_latin_model.py

It downloads two files from the **official RapidAI/RapidOCR model repository on
ModelScope** into this directory and verifies both against ``SHA256SUMS``. If a
file is already present and matches, it is left untouched. A checksum mismatch is
a hard error (no silent substitution).

Source repo:  https://www.modelscope.cn/models/RapidAI/RapidOCR
  model  ->  onnx/PP-OCRv4/rec/latin_PP-OCRv3_rec_mobile.onnx
            (saved locally as latin_PP-OCRv3_rec_infer.onnx)
  dict   ->  paddle/PP-OCRv4/rec/latin_PP-OCRv3_rec_mobile/latin_dict.txt

See README.md in this directory for the full model identity / provenance record.
"""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
_BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/master"

FILES = {
    "latin_PP-OCRv3_rec_infer.onnx": f"{_BASE}/onnx/PP-OCRv4/rec/latin_PP-OCRv3_rec_mobile.onnx",
    "latin_dict.txt": f"{_BASE}/paddle/PP-OCRv4/rec/latin_PP-OCRv3_rec_mobile/latin_dict.txt",
}


def _expected_sums() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, name = line.split()
        out[name] = digest
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    expected = _expected_sums()
    for name, url in FILES.items():
        dest = HERE / name
        want = expected[name]
        if dest.exists() and _sha256(dest) == want:
            print(f"ok (cached)   {name}")
            continue
        print(f"downloading   {name}  <-  {url}")
        urllib.request.urlretrieve(url, dest)  # noqa: S310 - documented https source
        got = _sha256(dest)
        if got != want:
            dest.unlink(missing_ok=True)
            print(f"CHECKSUM MISMATCH for {name}\n  expected {want}\n  got      {got}")
            return 1
        print(f"verified      {name}  sha256={got}")
    print("Latin model + dictionary present and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
