"""Round 2 corpus, aimed squarely at the hole: documents with no date/time/version field.

FUNSD  - 199 real scanned business forms (noisy, varied, many share a template).
         Same form rescaled/cropped = same-content positives; different forms =
         negatives, including template-sharing ones.
arXiv  - papers whose v1 and v2 both exist. v1 vs v2 is the same document with
         genuinely changed content and NO date field anywhere in the body: exactly
         the case the field veto cannot see. Different papers on one LaTeX template
         are the field-less template-collision negatives.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image

SCRATCH = Path(__file__).parent
OUT = SCRATCH / "corpus2"
UA = {"User-Agent": "DejaQ-cache-eval/1.0 (research; contact via repo owner)"}

N_FORMS = 120
N_PAPERS = 30
SCALES = {"full": 1.0, "small": 0.62}
CROPS = {"whole": None, "tight": (0.05, 0.04, 0.95, 0.96)}


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def variants(img: Image.Image, stem: str, group: str, source: str, records: list) -> None:
    for sname, scale in SCALES.items():
        w, h = img.size
        base = img.resize((max(1, int(w * scale)), max(1, int(h * scale)))) if scale != 1.0 else img
        for cname, box in CROPS.items():
            out = base
            if box:
                bw, bh = base.size
                out = base.crop((int(box[0] * bw), int(box[1] * bh),
                                 int(box[2] * bw), int(box[3] * bh)))
            name = f"{stem}__{sname}_{cname}.png"
            out.convert("RGB").save(OUT / name)
            records.append({"path": name, "group": group, "capture": f"{sname}_{cname}",
                            "source": source, "doc": group})


def build_funsd(records: list) -> None:
    print("downloading FUNSD...", flush=True)
    data = fetch("https://guillaumejaume.github.io/FUNSD/dataset.zip", timeout=300)
    zf = zipfile.ZipFile(io.BytesIO(data))
    pngs = [n for n in zf.namelist() if n.lower().endswith(".png") and "__MACOSX" not in n]
    print(f"  {len(pngs)} form images in archive; using {N_FORMS}", flush=True)
    for i, name in enumerate(sorted(pngs)[:N_FORMS]):
        with Image.open(io.BytesIO(zf.read(name))) as img:
            img.load()
            variants(img, f"funsd{i:03d}", f"funsd_{i:03d}", "funsd", records)


def arxiv_ids(n: int) -> list[str]:
    """Recent papers, oldest-first within a slice, so revisions have had time to appear."""
    url = ("https://export.arxiv.org/api/query?search_query=cat:cs.LG"
           "&start=0&max_results=%d&sortBy=submittedDate&sortOrder=descending" % (n * 6))
    xml = fetch(url).decode("utf-8", "replace")
    ids = re.findall(r"<id>https?://arxiv\.org/abs/([^<]+)</id>", xml)
    return [i.split("v")[0] for i in ids]


def render_pdf_page1(pdf: bytes, dest_stem: Path, dpi: int = 130) -> Image.Image | None:
    tmp = dest_stem.with_suffix(".pdf")
    tmp.write_bytes(pdf)
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", "1",
                    str(tmp), str(dest_stem)], check=False, capture_output=True)
    tmp.unlink(missing_ok=True)
    made = sorted(dest_stem.parent.glob(f"{dest_stem.name}-*.png"))
    if not made:
        return None
    img = Image.open(made[0])
    img.load()
    made[0].unlink()
    return img


def build_arxiv(records: list) -> None:
    print("querying arXiv...", flush=True)
    ids = arxiv_ids(N_PAPERS)
    kept = 0
    for aid in ids:
        if kept >= N_PAPERS:
            break
        pages = {}
        for ver in ("v1", "v2"):
            try:
                pdf = fetch(f"https://arxiv.org/pdf/{aid}{ver}", timeout=90)
            except Exception:
                continue
            if not pdf.startswith(b"%PDF"):
                continue
            img = render_pdf_page1(pdf, OUT / f"tmp_{aid.replace('/', '_')}{ver}")
            if img is not None:
                pages[ver] = img
            time.sleep(3)  # be polite to arXiv
        if not pages:
            continue
        stem = f"arxiv{kept:03d}"
        group = f"arxiv_{kept:03d}"
        for ver, img in pages.items():
            # v1 and v2 are the SAME paper: same content group, different capture.
            variants(img, f"{stem}_{ver}", group, "arxiv", records)
        print(f"  {aid}: {sorted(pages)} ({kept + 1}/{N_PAPERS})", flush=True)
        kept += 1


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    try:
        build_funsd(records)
    except Exception as exc:
        print(f"FUNSD failed: {exc}", flush=True)
    try:
        build_arxiv(records)
    except Exception as exc:
        print(f"arXiv failed: {exc}", flush=True)
    (OUT / "labels.json").write_text(json.dumps(records, ensure_ascii=False, indent=1))
    groups = {r["group"] for r in records}
    by_src: dict[str, int] = {}
    for r in records:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    print(f"\n{len(records)} images, {len(groups)} groups, by source: {by_src}")
