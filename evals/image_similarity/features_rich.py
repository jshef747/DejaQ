"""Extract EVERY signal any candidate approach might need, once, into one file.

Per image:
  words   : [[text, conf, x, y, w, h], ...] in Tesseract reading order,
            with x/y/w/h normalised to [0,1] so different DPI/crops are comparable
  text    : the words joined in reading order (for n-grams, LCS, embeddings)
  tokens  : the normalised token SET the shipped gate uses
  dhash   : 64-bit perceptual hash (hex)
  clip    : CLIP ViT-B/32 embedding (base64 float32)
  tiles   : 4x4 grid of per-tile dHashes, for region-level comparison

Agents read this file; nobody re-runs OCR.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from app.config import TESSERACT_BIN, TESSERACT_LANGS  # noqa: E402
from app.services.image_fingerprint import dhash, fingerprint  # noqa: E402
from app.services.image_text import _TOKEN_RE  # noqa: E402

import os
CORPUS = Path(__file__).parent / os.environ.get("CORPUS_DIR", "corpus")
OUT = Path(__file__).parent / os.environ.get("FEATURES_OUT", "features_rich.jsonl")
# Two ways to normalise resolution before OCR. Measured: two renders of one page
# at the same DPI agree on 63-78% of their words, but at different DPI only
# 3-35% - resolution, not framing, is what breaks the document path.
#
#   CANON_HEIGHT      scale every image to a fixed pixel height. Fixes the DPI
#                     axis but PENALISES crops, because a cropped page is shorter
#                     and therefore gets scaled by a different factor than the
#                     full page it should match.
#   CANON_WORD_HEIGHT scale so the median OCR word is a fixed pixel height. Costs
#                     a throwaway OCR pass to measure, but it is invariant to
#                     cropping, which is what CANON_HEIGHT gets wrong.
CANON_HEIGHT = int(os.environ.get("CANON_HEIGHT", "0"))
CANON_WORD_HEIGHT = float(os.environ.get("CANON_WORD_HEIGHT", "0"))


def _rescale(data: bytes, factor: float) -> bytes:
    import io

    if abs(factor - 1.0) < 0.02:
        return data
    with Image.open(io.BytesIO(data)) as im:
        size = (max(1, round(im.width * factor)), max(1, round(im.height * factor)))
        buf = io.BytesIO()
        im.convert("RGB").resize(size, Image.LANCZOS).save(buf, "PNG")
        return buf.getvalue()


def _median_word_height(words: list) -> float:
    heights = sorted(h for _, c, _, _, _, h in words if c >= 60.0)
    return heights[len(heights) // 2] if heights else 0.0


def ocr_words(data: bytes, _rescaled: bool = False) -> tuple[list, float, float]:
    """Return (words, page_w, page_h) with pixel boxes, in reading order."""
    if CANON_HEIGHT and not _rescaled:
        import io

        with Image.open(io.BytesIO(data)) as im:
            data = _rescale(data, CANON_HEIGHT / im.height)
    proc = subprocess.run(
        [TESSERACT_BIN, "stdin", "stdout", "-l", TESSERACT_LANGS, "--psm", "3", "tsv"],
        input=data, capture_output=True, timeout=60,
    )
    rows = proc.stdout.decode("utf-8", "replace").splitlines()
    if not rows:
        return [], 1.0, 1.0
    header = rows[0].split("\t")
    idx = {name: i for i, name in enumerate(header)}
    words, page_w, page_h = [], 1.0, 1.0
    for line in rows[1:]:
        c = line.split("\t")
        if len(c) <= idx.get("text", 11):
            continue
        try:
            level = int(c[idx["level"]])
            left, top = int(c[idx["left"]]), int(c[idx["top"]])
            width, height = int(c[idx["width"]]), int(c[idx["height"]])
            conf = float(c[idx["conf"]])
        except (ValueError, KeyError):
            continue
        if level == 1:  # page-level row carries the page box
            page_w, page_h = max(width, 1), max(height, 1)
            continue
        text = c[idx["text"]].strip()
        if level == 5 and text and conf >= 0:
            words.append([text, conf, left, top, width, height])

    if CANON_WORD_HEIGHT and not _rescaled:
        median = _median_word_height(words)
        if median > 0:
            # Re-read at the scale that makes text a fixed size. Unlike page
            # height this is unaffected by how the page was cropped.
            return ocr_words(_rescale(data, CANON_WORD_HEIGHT / median), _rescaled=True)
    return words, page_w, page_h


def tile_hashes(data: bytes, grid: int = 4) -> list[str]:
    """Per-region dHash: a small differing area (a date block) shows up as one tile."""
    import io

    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("L")
        w, h = im.size
        out = []
        for gy in range(grid):
            for gx in range(grid):
                box = (gx * w // grid, gy * h // grid,
                       (gx + 1) * w // grid, (gy + 1) * h // grid)
                out.append(f"{dhash(im.crop(box)):016x}")
    return out


def main() -> None:
    labels = json.loads((CORPUS / "labels.json").read_text())
    done = set()
    if OUT.exists():
        done = {json.loads(line)["path"] for line in OUT.open()}
        print(f"resuming: {len(done)} done", flush=True)
    start = time.perf_counter()
    with OUT.open("a") as out:
        for i, rec in enumerate(labels, 1):
            if rec["path"] in done:
                continue
            data = (CORPUS / rec["path"]).read_bytes()
            try:
                words, pw, ph = ocr_words(data)
            except Exception:
                words, pw, ph = [], 1.0, 1.0
            norm = [[t, round(c, 1), round(x / pw, 4), round(y / ph, 4),
                     round(w / pw, 4), round(h / ph, 4)] for t, c, x, y, w, h in words]
            text = " ".join(t for t, *_ in words)
            confident = [c for _, c, *_ in words if c >= 60.0]
            all_conf = [c for _, c, *_ in words]
            try:
                fp = fingerprint(data)
                clip, dh = fp.clip_b64, fp.dhash_hex
            except Exception:
                clip = dh = None
            try:
                tiles = tile_hashes(data)
            except Exception:
                tiles = []
            out.write(json.dumps({
                **rec,
                "words": norm,
                "text": text,
                "tokens": sorted({t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 3}),
                "word_count": len(confident),
                "mean_confidence": round(sum(all_conf) / len(all_conf), 2) if all_conf else 0.0,
                "dhash": dh, "clip": clip, "tiles": tiles,
            }, ensure_ascii=False) + "\n")
            out.flush()
            if i % 50 == 0:
                print(f"{i}/{len(labels)}  {(time.perf_counter() - start) / 60:.1f} min", flush=True)
    print(f"done in {(time.perf_counter() - start) / 60:.1f} min")


if __name__ == "__main__":
    main()
