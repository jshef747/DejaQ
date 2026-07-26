"""Build the labelled image corpus for sweeping the image-gate thresholds.

Two sources, both real captures — no filter-based simulation of anything.

A) A directory of your own PDFs (--pdf-dir): each page rasterised at several DPI
   and cropped at several offsets. These are genuinely different renderings of
   the same page, which is what a screenshot at a different zoom or scroll
   position is. Documents from one template (e.g. several sittings of one exam)
   are the most valuable material here — they are the hard negatives.

B) DocUNet (fetch separately, see README): 65 real paper documents, each captured
   as 2 camera photos, their 2 document-centred crops, and 1 flatbed scan.

Labels are (group, capture) where group identifies the content. Same group =
must hit, different group = must miss.

    uv run python ../evals/image_similarity/build_corpus.py --pdf-dir ~/Documents/exams

Pass --exclude to skip files by substring. Anything containing personal data
(identity documents, signed forms) should be excluded — the corpus is written to
disk and the labels file records every filename.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "corpus"

# Rasterisation settings — each is a real, independent render of the page.
DPI_VARIANTS = (110, 150, 200)
# Crop windows as fractions (left, top, right, bottom) of the rendered page:
# whole page, and two windows that keep most of the text but reframe it, the way
# a re-taken screenshot does.
CROPS = {
    "full": (0.0, 0.0, 1.0, 1.0),
    "tight": (0.04, 0.03, 0.96, 0.97),
    "upper": (0.0, 0.0, 1.0, 0.75),
}
MAX_PAGES_PER_PDF = 4  # keep the corpus a few hundred images, not thousands


def source_pdfs(pdf_dir: Path, exclude: tuple[str, ...]) -> list[Path]:
    pdfs = list(pdf_dir.glob("*.pdf")) + list(pdf_dir.glob("*/*.pdf"))
    return sorted(p for p in pdfs if not any(x in str(p) for x in exclude))


def render(pdf: Path, page: int, dpi: int, dest: Path) -> Path | None:
    stem = dest.with_suffix("")
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
         str(pdf), str(stem)],
        check=True, capture_output=True,
    )
    produced = sorted(stem.parent.glob(f"{stem.name}-*.png"))
    if not produced:
        return None
    produced[0].rename(dest)
    return dest


def crop(src: Path, box: tuple[float, float, float, float], dest: Path) -> None:
    from PIL import Image

    with Image.open(src) as im:
        w, h = im.size
        l, t, r, b = box
        im.crop((int(l * w), int(t * h), int(r * w), int(b * h))).save(dest)


def build_from_pdfs(pdf_dir: Path, exclude: tuple[str, ...]) -> list[dict]:
    records = []
    tmp = OUT / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for pdf in source_pdfs(pdf_dir, exclude):
        # Group by document AND page: two pages of one exam are different content.
        doc_id = pdf.stem[:40].replace(" ", "_")
        pages = int(subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True)
                    .stdout.split("Pages:")[1].split()[0])
        for page in range(1, min(pages, MAX_PAGES_PER_PDF) + 1):
            group = f"{doc_id}__p{page}"
            for dpi in DPI_VARIANTS:
                base = render(pdf, page, dpi, tmp / f"{group}__dpi{dpi}.png")
                if base is None:
                    continue
                for cname, box in CROPS.items():
                    dest = OUT / f"{group}__dpi{dpi}_{cname}.png"
                    crop(base, box, dest)
                    records.append({
                        "path": dest.name, "group": group,
                        "capture": f"render_dpi{dpi}_{cname}", "source": "pdfs",
                        "doc": doc_id,
                    })
                base.unlink()
    shutil.rmtree(tmp, ignore_errors=True)
    return records


def build_docunet() -> list[dict]:
    root = HERE / "docunet" / "unzipped"
    if not root.exists():
        return []
    records = []
    for sub, capture in (("original", "photo"), ("crop", "photo_crop"), ("scan", "scan")):
        for img in sorted((root / sub).rglob("*")):
            if img.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                continue
            # Filenames look like "1_1.png" / "1.png": the leading number is the document.
            doc = img.stem.split("_")[0]
            dest = OUT / f"docunet{doc}__{capture}_{img.stem}.png"
            shutil.copy(img, dest)
            records.append({
                "path": dest.name, "group": f"docunet_{doc}",
                "capture": f"{capture}_{img.stem}", "source": "docunet",
                "doc": f"docunet_{doc}",
            })
    return records


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf-dir", type=Path,
                    help="Directory of PDFs to rasterise (searched one level deep).")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="Skip files whose path contains any of these substrings.")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    recs = build_docunet()
    if args.pdf_dir:
        recs = build_from_pdfs(args.pdf_dir, tuple(args.exclude)) + recs
    (OUT / "labels.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1))
    groups = {r["group"] for r in recs}
    by_source: dict[str, int] = {}
    for r in recs:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    print(f"{len(recs)} images, {len(groups)} content groups")
    print("by source:", by_source)
