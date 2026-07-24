"""Generate a large, labeled similar/different photo test set from your Photos Library.

Samples N random real photos, then creates several realistic near-duplicate
variants of each (resize, heavy JPEG recompression, crop, rotate, brightness).
Output filenames encode the ground-truth group as `srcNNN__variant.jpg`, so
cluster.py's --group-sep flag can auto-score clustering accuracy against them.

Run from server/ (reuses its venv):
    uv run python ../evals/image_similarity/augment.py --n-sources 40
    uv run python ../evals/image_similarity/cluster.py ../evals/image_similarity/dataset --group-sep __
"""
from __future__ import annotations

import argparse
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageEnhance

DEFAULT_LIBRARY = Path.home() / "Pictures" / "Photos Library.photoslibrary" / "originals"
DIRECT_EXTS = {".jpg", ".jpeg", ".png"}
HEIC_EXTS = {".heic"}
READABLE_EXTS = DIRECT_EXTS | HEIC_EXTS


def find_source_photos(library: Path) -> list[Path]:
    return [p for p in library.rglob("*") if p.is_file() and p.suffix.lower() in READABLE_EXTS]


def open_photo(path: Path) -> Image.Image:
    """Open jpg/png directly; convert HEIC to JPEG via macOS's built-in `sips` first
    (no new dependency needed for HEIC support)."""
    if path.suffix.lower() not in HEIC_EXTS:
        return Image.open(path).convert("RGB")

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        subprocess.run(
            ["sips", "-s", "format", "jpeg", str(path), "--out", str(tmp_path)],
            check=True, capture_output=True,
        )
        return Image.open(tmp_path).convert("RGB")
    finally:
        tmp_path.unlink(missing_ok=True)


def make_variants(img: Image.Image) -> dict[str, tuple[Image.Image, int]]:
    """Return {variant_name: (image, jpeg_quality)}."""
    w, h = img.size
    return {
        "original": (img, 95),
        "resized": (img.resize((max(1, int(w * 0.7)), max(1, int(h * 0.7)))), 85),
        "recompressed": (img, 25),  # same pixels, heavy JPEG artifacting
        "crop95": (img.crop((int(w * 0.05), int(h * 0.05), int(w * 0.95), int(h * 0.95))), 85),
        "rot3": (img.rotate(3, expand=True, fillcolor=(255, 255, 255)), 85),
        "bright": (ImageEnhance.Brightness(img).enhance(1.25), 85),
    }


def run(library: Path, n_sources: int, out_dir: Path, seed: int | None) -> None:
    if seed is not None:
        random.seed(seed)

    candidates = find_source_photos(library)
    if not candidates:
        raise SystemExit(f"No jpg/png photos found under {library}")

    n_sources = min(n_sources, len(candidates))
    chosen = random.sample(candidates, n_sources)

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Found {len(candidates)} candidate photos under {library}, sampling {n_sources}.")

    total = 0
    for i, src_path in enumerate(chosen, start=1):
        try:
            img = open_photo(src_path)
        except Exception as e:
            print(f"skip {src_path.name}: {e}")
            continue

        group_id = f"src{i:03d}"
        for variant_name, (variant_img, quality) in make_variants(img).items():
            out_path = out_dir / f"{group_id}__{variant_name}.jpg"
            variant_img.convert("RGB").save(out_path, format="JPEG", quality=quality)
            total += 1

    print(f"\nWrote {total} images ({n_sources} groups x 6 variants) to {out_dir}")
    print(f"Run: uv run python cluster.py {out_dir} --group-sep __ --threshold 0.10")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-sources", type=int, default=40, help="number of distinct source photos to sample")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "dataset")
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    run(args.library, args.n_sources, args.out, args.seed)
