"""One-off prep: extract INRIA Copydays tarballs into the harness's
`srcNNN__variant.jpg` naming convention so cluster.py/phash_gate.py work
unmodified against this dataset.

Copydays filename convention: first 4 digits = block/group id, last 2 digits
= variant (00 = unmodified original, 01-05+ = a "strong" attack: print/scan,
paint edits, blur, etc). See https://dl.fbaipublicfiles.com/vissl/datasets/.

Run once:
    uv run python prep_copydays.py dataset_copydays/_raw dataset_copydays
"""
from __future__ import annotations

import argparse
import tarfile
from pathlib import Path


def prep(raw_dir: Path, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for tar_name in ("original.tar.gz", "strong.tar.gz"):
        with tarfile.open(raw_dir / tar_name) as tf:
            for member in tf.getmembers():
                if not member.isfile() or not member.name.endswith(".jpg"):
                    continue
                stem = member.name[:-4]
                block, suffix = stem[:4], stem[4:]
                variant = "original" if suffix == "00" else f"strong{suffix}"
                dest = out_dir / f"src{block}__{variant}.jpg"
                dest.write_bytes(tf.extractfile(member).read())
                n += 1
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()
    n = prep(args.raw_dir, args.out_dir)
    print(f"Wrote {n} images to {args.out_dir}")
