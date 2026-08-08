"""Round 3 corpora: the four populations rounds 1 and 2 never covered.

Round 1 (coursework + DocUNet) and round 2 (FUNSD + arXiv) are both documents,
and the photo path was only ever measured on synthetic augmentations of 60
source images. That leaves four real populations unmeasured:

    photos     INRIA Holidays - 1491 holiday snapshots in 500 scenes. Two shots
               of one scene from different viewpoints is the photo path's actual
               recall case; 500 different scenes are its false-merge case. The
               grouping is the dataset's own convention (id // 100).
               ftp://ftp.inrialpes.fr/pub/lear/douze/data/jpg1.tar.gz
               Cite Jegou et al., ECCV 2008.

    receipts   SROIE 2019 - real scanned receipts. Many come from one store on
               one printer template and differ only in items and total, which
               makes them the hardest document negatives available anywhere.
               huggingface.co/datasets/rth/sroie-2019-v2

    screens    Rico (via Screen2Words) - Android UI screenshots. Text-bearing
               images that are NOT documents: the "ambiguous" class the router
               refuses, which has never been measured on anything. Two screens
               of ONE app are near-identical but show different data, which is
               the realistic screenshot false-merge case, so the app package is
               recorded per image.
               huggingface.co/datasets/rootsautomation/RICO-Screen2Words
               NB: creative-graphic-design/Rico serves the *semantic annotation*
               renderings (flat colour blocks) in its `screenshot` column, not
               photographs of screens. Measuring those measures nothing.

    recapture  UHDM - 4K pairs of (image shown on a screen, camera photo of that
               screen). Ground truth for "a screenshot and a phone photo of that
               same screen must hit", which is the live complaint that started
               this work.  github.com/CVMI-Lab/UHDM, Yu et al., ECCV 2022.

Every corpus writes `labels.json` in the same shape as build_corpus.py, so
features_rich.py and protocol.py consume them unchanged.

    uv run python ../evals/image_similarity/fetch_round3.py holidays
    uv run python ../evals/image_similarity/fetch_round3.py sroie --limit 200
    uv run python ../evals/image_similarity/fetch_round3.py rico --limit 150
    uv run python ../evals/image_similarity/fetch_round3.py uhdm --limit 150
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import tarfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
DL = HERE / "dl"

# Documents and screenshots get the same re-render treatment round 2 used: a
# scale change and a reframe stand in for the same page screenshotted twice.
# Photos and recaptures get NO synthetic variants - their variants are real.
SCALES = {"full": 1.0, "small": 0.62}
CROPS: dict[str, tuple[float, float, float, float] | None] = {
    "whole": None,
    "tight": (0.05, 0.04, 0.95, 0.96),
}


def _save(img: Image.Image, dest: Path, max_side: int) -> None:
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    img.convert("RGB").save(dest, quality=92)


def _variants(img: Image.Image, stem: str, group: str, source: str,
              out: Path, records: list, max_side: int = 1400) -> None:
    for sname, scale in SCALES.items():
        w, h = img.size
        base = img if scale == 1.0 else img.resize((int(w * scale), int(h * scale)))
        for cname, box in CROPS.items():
            frame = base
            if box:
                bw, bh = base.size
                frame = base.crop((int(box[0] * bw), int(box[1] * bh),
                                   int(box[2] * bw), int(box[3] * bh)))
            name = f"{stem}__{sname}_{cname}.jpg"
            _save(frame, out / name, max_side)
            records.append({"path": name, "group": group, "capture": f"{sname}_{cname}",
                            "source": source, "doc": group})


def _finish(out: Path, records: list) -> None:
    (out / "labels.json").write_text(json.dumps(records, ensure_ascii=False, indent=1))
    groups = {r["group"] for r in records}
    print(f"{out.name}: {len(records)} images, {len(groups)} content groups")


def build_holidays(limit: int) -> None:
    """Holidays names images 1DDDNN.jpg where DDD is the scene: group = id // 100."""
    out = HERE / "corpus_photos"
    out.mkdir(exist_ok=True)
    records: list[dict] = []
    seen_groups: set[int] = set()
    with tarfile.open(DL / "jpg1.tar.gz") as tf:
        members = sorted((m for m in tf.getmembers()
                          if m.isfile() and m.name.lower().endswith(".jpg")),
                         key=lambda m: m.name)
        for m in members:
            stem = Path(m.name).stem
            if not stem.isdigit():
                continue
            group = int(stem) // 100
            if group not in seen_groups and len(seen_groups) >= limit:
                continue
            seen_groups.add(group)
            fh = tf.extractfile(m)
            if fh is None:
                continue
            with Image.open(io.BytesIO(fh.read())) as img:
                img.load()
                name = f"hol{group:05d}_{stem}.jpg"
                # 1024 keeps CLIP honest while making 700 images tractable to OCR.
                _save(img, out / name, 1024)
            records.append({"path": name, "group": f"holidays_{group}",
                            "capture": stem, "source": "holidays",
                            "doc": f"holidays_{group}"})
    _finish(out, records)


def _parquet_rows(pattern: str, columns: list[str], limit: int):
    """Yield (index, row-dict) for the first `limit` rows carrying image bytes."""
    import pyarrow.parquet as pq

    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"no parquet matching {pattern} - download it first")
    seen = 0
    for path in files:
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=32, columns=columns):
            for row in batch.to_pylist():
                if seen >= limit:
                    return
                if row.get(columns[0], {}).get("bytes"):
                    yield seen, row
                    seen += 1


HF = str(Path.home() / ".cache/huggingface/hub")


def build_sroie(limit: int) -> None:
    out = HERE / "corpus_receipts"
    out.mkdir(exist_ok=True)
    records: list[dict] = []
    pattern = f"{HF}/datasets--rth--sroie-2019-v2/snapshots/*/data/*.parquet"
    for i, row in _parquet_rows(pattern, ["image"], limit):
        with Image.open(io.BytesIO(row["image"]["bytes"])) as img:
            img.load()
            _variants(img, f"sroie{i:04d}", f"sroie_{i:04d}", "sroie", out, records)
    _finish(out, records)


def build_rico(limit: int) -> None:
    out = HERE / "corpus_screens"
    out.mkdir(exist_ok=True)
    records: list[dict] = []
    pattern = (f"{HF}/datasets--rootsautomation--RICO-Screen2Words/snapshots/*/"
               "data/*.parquet")
    start = len(records)
    for i, row in _parquet_rows(pattern, ["image", "app_package_name"], limit):
        with Image.open(io.BytesIO(row["image"]["bytes"])) as img:
            img.load()
            _variants(img, f"rico{i:04d}", f"rico_{i:04d}", "rico", out, records)
        for rec in records[start:]:
            rec.setdefault("app", row["app_package_name"])
        start = len(records)
    _finish(out, records)
    apps = {r["app"] for r in records}
    print(f"  from {len(apps)} distinct apps "
          f"({len(records) // 4 - len(apps)} screens share an app with another)")


def build_uhdm(limit: int) -> None:
    """UHDM ships each pair as <name>_gt.jpg (the screen image) + <name>_moire.jpg
    (a camera photo of that screen). Both members of a pair are one group."""
    out = HERE / "corpus_recapture"
    out.mkdir(exist_ok=True)
    records: list[dict] = []
    pairs: dict[str, dict[str, tarfile.TarInfo]] = {}
    with tarfile.open(DL / "uhdm_test.tar.gz") as tf:
        for m in tf:
            if not m.isfile() or not m.name.lower().endswith((".jpg", ".png")):
                continue
            stem = Path(m.name).stem
            for suffix, role in (("_gt", "screen"), ("_moire", "photo"),
                                 ("_source", "photo")):
                if stem.endswith(suffix):
                    pairs.setdefault(stem[: -len(suffix)], {})[role] = m
                    break
        complete = [k for k, v in sorted(pairs.items()) if len(v) == 2][:limit]
        for i, key in enumerate(complete):
            for role, member in pairs[key].items():
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                with Image.open(io.BytesIO(fh.read())) as img:
                    img.load()
                    name = f"uhdm{i:04d}_{role}.jpg"
                    # A phone photo of a screen is what a user actually uploads:
                    # 1600 is a realistic upload size, not the 4K source.
                    _save(img, out / name, 1600)
                records.append({"path": name, "group": f"uhdm_{i:04d}",
                                "capture": role, "source": "uhdm",
                                "doc": f"uhdm_{i:04d}"})
    _finish(out, records)


BUILDERS = {"holidays": build_holidays, "sroie": build_sroie,
            "rico": build_rico, "uhdm": build_uhdm}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", choices=sorted(BUILDERS))
    ap.add_argument("--limit", type=int, default=150,
                    help="content groups (scenes / receipts / screens / pairs)")
    args = ap.parse_args()
    BUILDERS[args.corpus](args.limit)
