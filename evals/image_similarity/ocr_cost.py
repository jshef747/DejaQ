"""What OCR size normalisation would cost on the request path, in milliseconds.

`image_text.extract()` runs once per image request, on hits and misses alike, so
any normalisation scheme pays its cost on every request. Normalising by word
height needs a throwaway first pass to measure the text, then a second read at
the corrected scale — potentially on a much larger image.

Three variants are timed against the same images:

    shipped       one pass at native size
    fixed 2x      ONE pass on a 2x upscale - no measurement pass at all
    unconditional measure, then always re-read at the target scale
    conditional   measure, and re-read ONLY when the image is below target
                  (an already-large screenshot pays nothing but the first pass)

The fixed variant is the one that matters: measured on 387 renders it beat every
adaptive scheme, because the recall gain comes from giving Tesseract more pixels,
not from normalising anything. Adaptive schemes hand two similar images DIFFERENT
factors and break pairs that used to agree.

    uv run python ../evals/image_similarity/ocr_cost.py corpus_canon --limit 50
"""
from __future__ import annotations

import argparse
import io
import statistics
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from app.config import TESSERACT_BIN, TESSERACT_LANGS  # noqa: E402

TARGET_WORD_HEIGHT = 30.0
QUANT = 1.25


def ocr(data: bytes) -> list[list]:
    proc = subprocess.run(
        [TESSERACT_BIN, "stdin", "stdout", "-l", TESSERACT_LANGS, "--psm", "3", "tsv"],
        input=data, capture_output=True, timeout=60,
    )
    rows = proc.stdout.decode("utf-8", "replace").splitlines()
    out = []
    for line in rows[1:]:
        c = line.split("\t")
        if len(c) > 11 and c[0] == "5" and c[11].strip():
            try:
                out.append([float(c[10]), int(c[9])])   # conf, height
            except ValueError:
                pass
    return out


def scale_factor(words: list[list]) -> float:
    import math

    heights = sorted(h for conf, h in words if conf >= 60.0)
    if not heights:
        return 1.0
    median = heights[len(heights) // 2]
    return QUANT ** round(math.log(TARGET_WORD_HEIGHT / median, QUANT))


def rescale(data: bytes, factor: float) -> bytes:
    with Image.open(io.BytesIO(data)) as im:
        size = (max(1, round(im.width * factor)), max(1, round(im.height * factor)))
        buf = io.BytesIO()
        im.convert("RGB").resize(size, Image.LANCZOS).save(buf, "PNG")
        return buf.getvalue()


def main(corpus: Path, limit: int) -> None:
    images = sorted(p for p in corpus.iterdir()
                    if p.suffix.lower() in (".png", ".jpg", ".jpeg"))[:limit]
    base, fixed, uncond, cond = [], [], [], []
    upscaled = 0
    for path in images:
        data = path.read_bytes()

        t0 = time.perf_counter()
        words = ocr(data)
        first = (time.perf_counter() - t0) * 1000
        base.append(first)

        t0 = time.perf_counter()
        ocr(rescale(data, 2.0))
        fixed.append((time.perf_counter() - t0) * 1000)

        factor = scale_factor(words)
        t0 = time.perf_counter()
        ocr(rescale(data, factor))
        second = (time.perf_counter() - t0) * 1000
        uncond.append(first + second)

        if factor > 1.0:
            upscaled += 1
            cond.append(first + second)
        else:
            cond.append(first)

    def show(name: str, xs: list[float], ref: list[float] | None = None) -> None:
        extra = ""
        if ref:
            extra = (f"   +{statistics.median(xs) - statistics.median(ref):>6.0f} ms median"
                     f" (+{statistics.mean(xs) - statistics.mean(ref):.0f} mean)")
        print(f"{name:<16}{statistics.median(xs):>8.0f} ms median"
              f"{statistics.mean(xs):>9.0f} mean{max(xs):>9.0f} max{extra}")

    print(f"{len(images)} images from {corpus.name}, target word height "
          f"{TARGET_WORD_HEIGHT:.0f}px, ladder {QUANT}\n")
    show("shipped", base)
    show("fixed 2x", fixed, base)
    show("unconditional", uncond, base)
    show("conditional", cond, base)
    print(f"\n{upscaled}/{len(images)} images needed the second pass "
          f"({100 * upscaled / len(images):.0f}%)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("corpus", type=Path, nargs="?",
                    default=Path(__file__).parent / "corpus_canon")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    main(args.corpus if args.corpus.is_absolute() else Path(__file__).parent / args.corpus,
         args.limit)
