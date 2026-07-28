"""arXiv half of round 2: the field-less near-duplicate case.

v1 vs v2 of one paper is the same document with genuinely changed content and no
date/time/version field the veto can read — precisely what the field approach is
blind to. Different papers on one LaTeX template are the field-less template
collision negatives.

Uses curl (urllib timed out against export.arxiv.org) and an older submission
window, so revisions have had time to appear.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from PIL import Image

OUT = Path(__file__).parent / "corpus2"
N_PAPERS = 28
SCALES = {"full": 1.0, "small": 0.62}
CROPS = {"whole": None, "tight": (0.05, 0.04, 0.95, 0.96)}


def curl(url: str, timeout: int = 90) -> bytes:
    r = subprocess.run(["curl", "-sL", "--max-time", str(timeout),
                        "-A", "DejaQ-cache-eval/1.0", url], capture_output=True)
    return r.stdout


def listing() -> list[str]:
    """Address papers directly by ID instead of the API, which rate-limits.

    arXiv IDs are YYMM.NNNNN. A window ~18 months old gives revisions time to
    appear; not every number resolves, so we over-generate and skip misses.
    """
    return [f"25{mm:02d}.{n:05d}" for mm in (1, 2, 3) for n in range(1, 60)]


def render(pdf: bytes, stem: Path, dpi: int = 130) -> Image.Image | None:
    tmp = stem.with_suffix(".pdf")
    tmp.write_bytes(pdf)
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", "1",
                    str(tmp), str(stem)], check=False, capture_output=True)
    tmp.unlink(missing_ok=True)
    made = sorted(stem.parent.glob(f"{stem.name}-*.png"))
    if not made:
        return None
    img = Image.open(made[0])
    img.load()
    made[0].unlink()
    return img


def variants(img, stem, group, records):
    for sname, scale in SCALES.items():
        w, h = img.size
        base = img.resize((int(w * scale), int(h * scale))) if scale != 1.0 else img
        for cname, box in CROPS.items():
            out = base
            if box:
                bw, bh = base.size
                out = base.crop((int(box[0] * bw), int(box[1] * bh),
                                 int(box[2] * bw), int(box[3] * bh)))
            name = f"{stem}__{sname}_{cname}.png"
            out.convert("RGB").save(OUT / name)
            records.append({"path": name, "group": group, "capture": f"{sname}_{cname}",
                            "source": "arxiv", "doc": group})


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    existing = json.loads((OUT / "labels.json").read_text()) if (OUT / "labels.json").exists() else []
    existing = [r for r in existing if r["source"] != "arxiv"]
    records: list[dict] = []
    ids = listing()
    print(f"{len(ids)} candidate papers", flush=True)
    kept = 0
    revised = 0
    for aid in ids:
        if kept >= N_PAPERS:
            break
        pages = {}
        for ver in ("v1", "v2"):
            pdf = curl(f"https://arxiv.org/pdf/{aid}{ver}")
            if not pdf.startswith(b"%PDF"):
                continue
            img = render(pdf, OUT / f"tmp{kept}{ver}")
            if img is not None:
                pages[ver] = img
            time.sleep(3)
        if "v1" not in pages:
            continue
        group = f"arxiv_{kept:03d}"
        for ver, img in pages.items():
            variants(img, f"arxiv{kept:03d}_{ver}", group, records)
        if len(pages) == 2:
            revised += 1
        print(f"  {aid}: {sorted(pages)}  ({kept + 1}/{N_PAPERS})", flush=True)
        kept += 1
    (OUT / "labels.json").write_text(json.dumps(existing + records, ensure_ascii=False, indent=1))
    print(f"\n{len(records)} arxiv images, {kept} papers, {revised} with a real v1+v2 revision pair")
