"""Batch-cluster a folder of images by CLIP similarity.

Run from server/ (reuses its venv):
    uv run python ../evals/image_similarity/cluster.py <input_dir> [--threshold 0.10] [--out DIR]
    uv run python ../evals/image_similarity/cluster.py <input_dir> --group-sep __  # auto-score vs. augment.py labels
    uv run python ../evals/image_similarity/cluster.py --self-test
"""
from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from clip_embed import embed_images
from report_he import write_report, write_sweep_report

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[rx] = ry


def cluster_by_threshold(dist_matrix: np.ndarray, threshold: float) -> list[int]:
    """Union-find over the distance matrix; returns a cluster id per index."""
    n = dist_matrix.shape[0]
    uf = UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if dist_matrix[i, j] <= threshold:
                uf.union(i, j)
    return [uf.find(i) for i in range(n)]


def score_against_groundtruth(paths: list[Path], labels: list[int], group_sep: str, verbose: bool = True) -> dict:
    """Score predicted clusters against ground-truth groups encoded in filenames
    as `<group><group_sep><variant>` (see augment.py). Returns the computed data
    (used for both the console summary and the HTML report)."""

    def group_of(p: Path) -> str:
        stem = p.stem
        return stem.split(group_sep)[0] if group_sep in stem else stem

    true_groups: dict[str, list[int]] = defaultdict(list)
    for idx, p in enumerate(paths):
        true_groups[group_of(p)].append(idx)

    # recall: fraction of each group's own members that landed in its majority predicted cluster
    recalls = []
    split_groups = []
    for group, indices in true_groups.items():
        majority_cluster, majority_count = Counter(labels[i] for i in indices).most_common(1)[0]
        recall = majority_count / len(indices)
        recalls.append(recall)
        if recall < 1.0:
            split_groups.append({"group": group, "recall": recall, "indices": indices})

    # purity: fraction of each predicted cluster's members from its majority true group
    pred_clusters: dict[int, list[int]] = defaultdict(list)
    for idx, label in enumerate(labels):
        pred_clusters[label].append(idx)

    purities = []
    mixed_clusters = []
    for label, indices in pred_clusters.items():
        counts = Counter(group_of(paths[i]) for i in indices)
        majority_group, majority_count = counts.most_common(1)[0]
        purity = majority_count / len(indices)
        purities.append((purity, len(indices)))
        if purity < 1.0:
            mixed_clusters.append({"counts": dict(counts), "indices": indices})

    avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
    weighted_purity = (
        sum(p * n for p, n in purities) / sum(n for _, n in purities) if purities else 0.0
    )

    if verbose:
        print(f"\nGround-truth scoring ({len(true_groups)} true groups, group-sep={group_sep!r}):")
        print(f"  avg group recall (variants staying together): {avg_recall:.3f}")
        print(f"  weighted cluster purity (no false merges):    {weighted_purity:.3f}")
        if split_groups:
            print(f"  {len(split_groups)} group(s) split across clusters (threshold too strict):")
            for g in sorted(split_groups, key=lambda x: x["recall"]):
                print(f"    {g['group']}: recall={g['recall']:.2f} ({len(g['indices'])} images)")
        if mixed_clusters:
            print(f"  {len(mixed_clusters)} cluster(s) mixing multiple true groups (threshold too loose):")
            for m in mixed_clusters:
                print(f"    {m['counts']} ({len(m['indices'])} images)")

    return {
        "n_groups": len(true_groups),
        "avg_recall": avg_recall,
        "weighted_purity": weighted_purity,
        "split_groups": split_groups,
        "mixed_clusters": mixed_clusters,
    }


def load_and_embed(input_dir: Path) -> tuple[list[Path], np.ndarray]:
    """Load every image in input_dir, embed once, return (valid_paths, dist_matrix)."""
    paths = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not paths:
        raise SystemExit(f"No images found in {input_dir}")

    images = []
    valid_paths = []
    for p in paths:
        try:
            img = Image.open(p).convert("RGB")
            # ponytail: bound memory regardless of source resolution/dataset size;
            # CLIP resizes to 224x224 internally anyway, so this loses no accuracy.
            img.thumbnail((256, 256))
            images.append(img)
            valid_paths.append(p)
        except Exception as e:
            print(f"skip {p.name}: {e}")

    print(f"Embedding {len(valid_paths)} images...")
    vecs = embed_images(images)

    # ponytail: O(n^2) pairwise matrix, fine for hundreds of images; switch to
    # an ANN index (e.g. faiss/hnsw) if this is ever run on thousands.
    dist_matrix = 1.0 - vecs @ vecs.T
    return valid_paths, dist_matrix


def run(input_dir: Path, threshold: float, out_dir: Path, group_sep: str | None = None) -> None:
    valid_paths, dist_matrix = load_and_embed(input_dir)
    labels = cluster_by_threshold(dist_matrix, threshold)

    groups: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        groups.setdefault(label, []).append(idx)

    multi = {k: v for k, v in groups.items() if len(v) > 1}
    singles = {k: v for k, v in groups.items() if len(v) == 1}

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    print(f"\n{len(multi)} clusters, {len(singles)} singleton(s), threshold={threshold}\n")

    cluster_info = []  # for the HTML report: (cluster_num, indices, max_dist)
    for cluster_num, (_, indices) in enumerate(
        sorted(multi.items(), key=lambda kv: -len(kv[1])), start=1
    ):
        cluster_dir = out_dir / f"cluster_{cluster_num:02d}"
        cluster_dir.mkdir()
        max_dist = max(
            dist_matrix[i, j] for i in indices for j in indices if i != j
        )
        cluster_info.append({"num": cluster_num, "indices": indices, "max_dist": max_dist})
        print(f"cluster_{cluster_num:02d}: {len(indices)} images, max intra-cluster distance {max_dist:.4f}")
        for idx in indices:
            shutil.copy2(valid_paths[idx], cluster_dir / valid_paths[idx].name)
            print(f"    {valid_paths[idx].name}")

    if singles:
        singles_dir = out_dir / "singletons"
        singles_dir.mkdir()
        for _, indices in singles.items():
            shutil.copy2(valid_paths[indices[0]], singles_dir / valid_paths[indices[0]].name)

    print("\nNearest-neighbor distances (tuning instrument):")
    nearest = []  # for the HTML report
    n = len(valid_paths)
    for i in range(n):
        row = dist_matrix[i].copy()
        row[i] = np.inf
        j = int(np.argmin(row))
        nearest.append((i, j, float(row[j])))
        print(f"  {valid_paths[i].name:40s} -> {valid_paths[j].name:40s}  dist={row[j]:.4f}")

    print(f"\nOutput copied to {out_dir}")

    gt_scores = None
    if group_sep:
        gt_scores = score_against_groundtruth(valid_paths, labels, group_sep)

    report_path = write_report(
        out_dir=out_dir,
        input_dir=input_dir,
        valid_paths=valid_paths,
        labels=labels,
        threshold=threshold,
        cluster_info=cluster_info,
        n_singles=len(singles),
        nearest=nearest,
        gt_scores=gt_scores,
    )
    print(f"\nHebrew HTML report: {report_path}")


def sweep(input_dir: Path, thresholds: list[float], out_path: Path, group_sep: str | None) -> None:
    """Embed once, re-cluster at every threshold (cheap), compare recall/purity."""
    valid_paths, dist_matrix = load_and_embed(input_dir)

    rows = []
    print(f"\n{'threshold':>10} {'clusters':>9} {'recall':>8} {'purity':>8} {'split':>6} {'mixed':>6}")
    for t in thresholds:
        labels = cluster_by_threshold(dist_matrix, t)
        groups: dict[int, list[int]] = {}
        for idx, label in enumerate(labels):
            groups.setdefault(label, []).append(idx)
        n_clusters = sum(1 for v in groups.values() if len(v) > 1)

        gt = None
        if group_sep:
            gt = score_against_groundtruth(valid_paths, labels, group_sep, verbose=False)

        row = {
            "threshold": t,
            "n_clusters": n_clusters,
            "recall": gt["avg_recall"] if gt else None,
            "purity": gt["weighted_purity"] if gt else None,
            "n_split": len(gt["split_groups"]) if gt else None,
            "n_mixed": len(gt["mixed_clusters"]) if gt else None,
        }
        rows.append(row)
        r = f"{row['recall']:.3f}" if gt else "-"
        p = f"{row['purity']:.3f}" if gt else "-"
        s = str(row["n_split"]) if gt else "-"
        m = str(row["n_mixed"]) if gt else "-"
        print(f"{t:>10.3f} {n_clusters:>9} {r:>8} {p:>8} {s:>6} {m:>6}")

    report_path = write_sweep_report(
        out_path=out_path, input_dir=input_dir, n_images=len(valid_paths), rows=rows,
    )
    print(f"\nHebrew sweep report: {report_path}")


def self_test() -> None:
    # two near-identical vectors + one far vector -> 2 clusters
    vecs = np.array([
        [1.0, 0.0, 0.0],
        [0.99, 0.01, 0.0],
        [0.0, 1.0, 0.0],
    ])
    vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    dist_matrix = 1.0 - vecs @ vecs.T
    labels = cluster_by_threshold(dist_matrix, threshold=0.10)
    assert labels[0] == labels[1], "near-identical vectors should share a cluster"
    assert labels[0] != labels[2], "far vector should be in its own cluster"
    print("self-test passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", nargs="?", type=Path)
    parser.add_argument("--threshold", type=float, default=0.10)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--group-sep", type=str, default=None, help="e.g. '__' to auto-score vs. augment.py labels")
    parser.add_argument(
        "--thresholds", type=str, default=None,
        help="comma-separated list, e.g. '0.05,0.07,0.10,0.15' -- runs a sweep instead of a single clustering pass",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        sys.exit(0)

    if not args.input_dir:
        parser.error("input_dir is required unless --self-test is passed")

    if args.thresholds:
        thresholds = [float(x) for x in args.thresholds.split(",")]
        out_path = args.out or (args.input_dir / "sweep_report.html")
        sweep(args.input_dir, thresholds, out_path, args.group_sep)
    else:
        out_dir = args.out or (args.input_dir / "clusters")
        run(args.input_dir, args.threshold, out_dir, args.group_sep)
