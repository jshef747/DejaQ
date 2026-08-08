"""Offline test for the caption+validator safeguard (band-tier image validation).

Tests whether captioning a band-distance image pair + judging the captions with a
text validator can catch false merges that pure CLIP similarity misses (see the
cluster.py sweep: 6 mixed clusters at threshold=0.07, incl. two different cities'
skylines merging), while still accepting legitimate band-tier matches (crops,
rotations, retakes of the same subject).

Mirrors the production validator's structure (server/app/services/validator.py):
system prompt + few-shots + single-word VALID/INVALID verdict, temperature 0,
first-token parsing, fail-safe INVALID on anything unparseable.

Run from server/ (reuses its venv; requires Ollama running with both models):
    ollama pull qwen2.5vl:7b
    uv run python ../evals/image_similarity/validate_pairs.py ../evals/image_similarity/dataset
    uv run python ../evals/image_similarity/validate_pairs.py --self-test
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from cluster import load_and_embed
from report_he import write_validation_report

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_CAPTION_MODEL = "qwen2.5vl:7b"
DEFAULT_VALIDATOR_MODEL = "gemma4:e2b"

CAPTION_PROMPTS = {
    # v1: open-ended prose -- prone to focusing on different incidental details
    # (framing, mood, camera angle) on minor crops/rotations of the same photo,
    # which then reads as "different content" to the text validator.
    "v1": (
        "Describe this image in 1-2 sentences. Name the main subject, any recognizable "
        "place or landmark, any visible text, and distinctive details."
    ),
    # v2: structured + explicitly invariant to framing/crop/rotation -- asks for the
    # underlying scene facts only, in a fixed order, so minor geometric changes to
    # the same photo produce near-identical captions.
    "v2": (
        "Describe the underlying scene in this image, ignoring how it happens to be "
        "cropped, rotated, or framed. State only, in this fixed order, as a single "
        "short sentence each:\n"
        "SUBJECT: the main subject(s) or object(s).\n"
        "SETTING: the type of place or setting.\n"
        "IDENTIFIERS: any specific named place, landmark, brand, or visible text (or 'none').\n"
        "Do not mention composition, angle, cropping, lighting, or image quality."
    ),
}

_VALIDATOR_SYSTEM = (
    "You decide if an ANSWER about a CACHED IMAGE would correctly apply to a NEW IMAGE, "
    "based on their descriptions.\n"
    "Reply with exactly one word: VALID or INVALID.\n"
    "VALID = the two images show the same subject/scene -- an answer about one would "
    "correctly describe the other, even if angle, lighting, crop, or format differs.\n"
    "INVALID = the images show a different place, different named entity, different "
    "visible text, or a different specific object/person, even if the general type of "
    "photo (e.g. both are skylines, both are selfies) is the same.\n"
    "When in doubt, choose VALID -- a wrong INVALID only costs a cache miss (the image "
    "is re-processed correctly); a wrong VALID serves a wrong answer to the user."
)

_VALIDATOR_FEWSHOTS = [
    (
        "CACHED IMAGE: A close-up selfie of a man with glasses and a beard, indoors.\n"
        "NEW IMAGE: A close-up selfie of a man with glasses and a beard, in a different room.",
        "VALID",
    ),
    (
        "CACHED IMAGE: A photo of a stone bridge over a river at sunset, with buildings along the bank.\n"
        "NEW IMAGE: A photo of the same stone bridge and river from a slightly different angle, same lighting.",
        "VALID",
    ),
    (
        "CACHED IMAGE: An aerial view of a city skyline with a tall historic domed building visible, overcast sky.\n"
        "NEW IMAGE: An aerial view of a city skyline with the Empire State Building visible, clear sky.",
        "INVALID",
    ),
    (
        "CACHED IMAGE: A toddler eating breakfast (eggs and tomatoes) at a wooden table.\n"
        "NEW IMAGE: A different toddler eating dinner (meat and mushrooms) at a different table.",
        "INVALID",
    ),
    (
        "CACHED IMAGE: A screenshot of a form titled 'Add Subscription' with fields for service name and yearly cost.\n"
        "NEW IMAGE: A photo of the same 'Add Subscription' form on a laptop screen, slightly blurry.",
        "VALID",
    ),
    (
        "CACHED IMAGE: A photo of a red car parked on a street.\n"
        "NEW IMAGE: A photo of a blue car parked in a driveway.",
        "INVALID",
    ),
]


def group_of(path: Path, sep: str = "__") -> str:
    stem = path.stem
    return stem.split(sep)[0] if sep in stem else stem


def select_pairs(
    valid_paths: list[Path], dist_matrix: np.ndarray, band_min: float, band_max: float, max_pairs: int,
) -> list[dict]:
    """Pure/testable: pick cross-group pairs (expected REJECT, hardest/closest first)
    and same-group pairs (expected ACCEPT) whose distance falls in the band.

    Cross-group pairs are deduped to ONE representative (the closest image-pair) per
    distinct (group_a, group_b) relationship before ranking. Without this, a single
    pair of visually-similar groups with many variants each (e.g. two source photos
    with 6 augmented variants -> up to 36 image-pairs) can flood max_pairs with
    near-duplicate pairs of itself, crowding out other, looser but equally important
    group-pair relationships (this is exactly what happened with a same-person selfie
    cluster starving out a looser cross-city false-merge pair in initial testing)."""
    n = len(valid_paths)
    groups = [group_of(p) for p in valid_paths]

    same = []
    best_cross: dict[tuple[str, str], dict] = {}
    for i in range(n):
        for j in range(i + 1, n):
            d = float(dist_matrix[i, j])
            if not (band_min <= d <= band_max):
                continue
            if groups[i] == groups[j]:
                same.append({"i": i, "j": j, "distance": d})
                continue
            key = tuple(sorted((groups[i], groups[j])))
            entry = {"i": i, "j": j, "distance": d}
            if key not in best_cross or d < best_cross[key]["distance"]:
                best_cross[key] = entry

    cross = sorted(best_cross.values(), key=lambda e: e["distance"])
    same.sort(key=lambda e: e["distance"])

    pairs = []
    for e in cross[:max_pairs]:
        pairs.append({**e, "expected": "REJECT"})
    for e in same[:max_pairs]:
        pairs.append({**e, "expected": "ACCEPT"})
    return pairs


def parse_verdict(raw: str) -> tuple[bool, str]:
    """Fail-safe first-token parsing, mirrors validator.py: unparseable -> False (INVALID)."""
    first_token = raw.strip().split()[0].upper() if raw.strip() else ""
    if first_token == "VALID":
        return True, raw
    return False, raw  # INVALID or unparseable both fail safe to False


def _thumbnail_b64(path: Path, max_side: int = 512) -> str:
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def caption_image(client: httpx.Client, ollama_url: str, model: str, path: Path, prompt_version: str = "v1") -> tuple[str, float]:
    b64 = _thumbnail_b64(path)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": CAPTION_PROMPTS[prompt_version], "images": [b64]}],
        "stream": False,
        "options": {"temperature": 0.0, "seed": 42},
    }
    start = time.time()
    resp = client.post(f"{ollama_url}/api/chat", json=payload, timeout=120.0)
    resp.raise_for_status()
    latency_ms = (time.time() - start) * 1000
    caption = resp.json()["message"]["content"].strip()
    return caption, latency_ms


def validate_captions(client: httpx.Client, ollama_url: str, model: str, cached_caption: str, new_caption: str) -> tuple[bool, str]:
    messages: list[dict] = [{"role": "system", "content": _VALIDATOR_SYSTEM}]
    for user_msg, assistant_msg in _VALIDATOR_FEWSHOTS:
        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": assistant_msg})
    messages.append({"role": "user", "content": f"CACHED IMAGE: {cached_caption}\nNEW IMAGE: {new_caption}"})

    payload = {
        "model": model, "messages": messages, "stream": False,
        "options": {"temperature": 0.0, "num_predict": 8},
    }
    resp = client.post(f"{ollama_url}/api/chat", json=payload, timeout=60.0)
    resp.raise_for_status()
    raw = resp.json()["message"]["content"]
    return parse_verdict(raw)


def run(
    input_dir: Path, band_min: float, band_max: float, max_pairs: int,
    ollama_url: str, caption_model: str, validator_model: str, prompt_version: str = "v1",
) -> None:
    valid_paths, dist_matrix = load_and_embed(input_dir)
    pairs = select_pairs(valid_paths, dist_matrix, band_min, band_max, max_pairs)
    n_cross = sum(1 for p in pairs if p["expected"] == "REJECT")
    n_same = sum(1 for p in pairs if p["expected"] == "ACCEPT")
    print(f"Selected {n_cross} cross-group pairs (expect REJECT) and {n_same} same-group pairs (expect ACCEPT)")

    cache_path = input_dir / "captions.json"
    captions: dict[str, str] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    latencies: list[float] = []

    def cache_key(name: str) -> str:
        return f"{name}::{caption_model}::{prompt_version}"

    unique_indices = sorted({p["i"] for p in pairs} | {p["j"] for p in pairs})
    with httpx.Client() as client:
        for n, idx in enumerate(unique_indices, start=1):
            key = cache_key(valid_paths[idx].name)
            if key in captions:
                continue
            caption, latency_ms = caption_image(client, ollama_url, caption_model, valid_paths[idx], prompt_version)
            captions[key] = caption
            latencies.append(latency_ms)
            print(f"  [{n}/{len(unique_indices)}] captioned {valid_paths[idx].name} ({latency_ms:.0f}ms): {caption[:80]}")
            cache_path.write_text(json.dumps(captions, ensure_ascii=False, indent=2))

        print(f"\nValidating {len(pairs)} pairs...")
        results = []
        for p in pairs:
            path_i, path_j = valid_paths[p["i"]], valid_paths[p["j"]]
            cap_i = captions[cache_key(path_i.name)]
            cap_j = captions[cache_key(path_j.name)]
            is_valid, raw = validate_captions(client, ollama_url, validator_model, cap_i, cap_j)
            verdict = "ACCEPT" if is_valid else "REJECT"
            results.append({
                **p, "path_i": path_i, "path_j": path_j,
                "cap_i": cap_i, "cap_j": cap_j, "verdict": verdict,
                "correct": verdict == p["expected"],
            })
            mark = "OK" if verdict == p["expected"] else "MISMATCH"
            print(f"  [{mark}] {path_i.name} <-> {path_j.name} dist={p['distance']:.4f} expected={p['expected']} got={verdict}")

    n_cross_results = [r for r in results if r["expected"] == "REJECT"]
    n_same_results = [r for r in results if r["expected"] == "ACCEPT"]
    cross_reject_rate = sum(r["correct"] for r in n_cross_results) / len(n_cross_results) if n_cross_results else None
    same_accept_rate = sum(r["correct"] for r in n_same_results) / len(n_same_results) if n_same_results else None

    print(f"\nCross-group rejection rate (catches false merges): {cross_reject_rate}")
    print(f"Same-group acceptance rate (keeps legit matches):    {same_accept_rate}")
    if latencies:
        arr = np.array(latencies)
        print(f"Caption latency: mean={arr.mean():.0f}ms p95={np.percentile(arr, 95):.0f}ms n={len(arr)}")

    report_name = "validation_report.html" if prompt_version == "v1" else f"validation_report_{prompt_version}.html"
    report_path = write_validation_report(
        out_path=input_dir / report_name,
        input_dir=input_dir,
        results=results,
        cross_reject_rate=cross_reject_rate,
        same_accept_rate=same_accept_rate,
        latencies=latencies,
        caption_model=f"{caption_model} ({prompt_version})",
        validator_model=validator_model,
    )
    print(f"\nHebrew validation report: {report_path}")


def self_test() -> None:
    # verdict parsing: fail-safe on anything but exact VALID
    assert parse_verdict("VALID")[0] is True
    assert parse_verdict("INVALID")[0] is False
    assert parse_verdict("garbage output")[0] is False
    assert parse_verdict("")[0] is False

    # pair selection: 3 groups (a, b, c), 2 images each.
    # a<->b appears TWICE (indices 0-2 dist=0.05, 1-3 dist=0.06) -- must dedup to
    # the closer one only. a<->c appears once (0-4 dist=0.045) -- a distinct
    # relationship that must survive even though a<->b is closer/more numerous.
    paths = [Path("a__1.jpg"), Path("a__2.jpg"), Path("b__1.jpg"), Path("b__2.jpg"),
             Path("c__1.jpg"), Path("c__2.jpg")]
    far = 0.90
    dist = np.array([
        [0.00, 0.04, 0.05, far,  0.045, far ],
        [0.04, 0.00, far,  0.06, far,   far ],
        [0.05, far,  0.00, 0.03, far,   far ],
        [far,  0.06, 0.03, 0.00, far,   far ],
        [0.045,far,  far,  far,  0.00,  far ],
        [far,  far,  far,  far,  far,   0.00],
    ])
    pairs = select_pairs(paths, dist, band_min=0.03, band_max=0.07, max_pairs=10)
    cross = [p for p in pairs if p["expected"] == "REJECT"]
    same = [p for p in pairs if p["expected"] == "ACCEPT"]
    assert len(same) == 2, f"expected 2 same-group pairs (a, b), got {len(same)}"
    assert len(cross) == 2, f"expected 2 distinct cross-group relationships (a-b, a-c), got {len(cross)}"
    assert cross[0]["distance"] <= cross[1]["distance"], "cross pairs should be sorted ascending"
    assert cross[0]["distance"] == 0.045, "closer a-c relationship should rank first"
    assert cross[1]["i"] == 0 and cross[1]["j"] == 2, "a-b representative should be the closer of its two instances (0.05, not 0.06)"
    print("self-test passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", nargs="?", type=Path)
    parser.add_argument("--band-min", type=float, default=0.03)
    parser.add_argument("--band-max", type=float, default=0.07)
    parser.add_argument("--max-pairs", type=int, default=40)
    parser.add_argument("--ollama-url", type=str, default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--caption-model", type=str, default=DEFAULT_CAPTION_MODEL)
    parser.add_argument("--validator-model", type=str, default=DEFAULT_VALIDATOR_MODEL)
    parser.add_argument("--caption-prompt-version", type=str, choices=list(CAPTION_PROMPTS), default="v1")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        sys.exit(0)

    if not args.input_dir:
        parser.error("input_dir is required unless --self-test is passed")

    run(
        args.input_dir, args.band_min, args.band_max, args.max_pairs,
        args.ollama_url, args.caption_model, args.validator_model, args.caption_prompt_version,
    )
