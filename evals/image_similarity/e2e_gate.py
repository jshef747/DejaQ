"""End-to-end image-cache checks against a RUNNING DejaQ server.

Everything else in this directory scores fingerprints offline. This drives the
actual HTTP endpoint, so it covers what offline scoring cannot: routing, cache
storage, the validator, the adjuster skip, and cross-kind isolation. Every live
regression in this feature so far was in that plumbing, not in the thresholds.

Each scenario primes the cache with one image+prompt, then sends a second
image+prompt and asserts whether it was served from cache (`x-dejaq-tier`).

Prerequisites: ChromaDB on :8001, the API on :8000, Ollama reachable.

Priming requests MISS by design, and an image miss always routes to the
workspace's external provider. Rather than spend real provider tokens (or
depend on a live key) the harness points a throwaway workspace at Ollama, which
speaks the OpenAI protocol:

    ollama pull qwen2.5vl:7b && ollama cp qwen2.5vl:7b gpt-4o-eval
    dejaq-admin workspace create --name "Eval Harness"
    # openai credential: any string; llm-config external_model: gpt-4o-eval:latest
    OPENAI_BASE_URL=http://127.0.0.1:11434/v1 uv run uvicorn app.main:app

Only the generator changes; routing, the gate, storage, the validator and the
adjuster skip are the shipped code paths. Set DEJAQ_EVAL_KEY to point the
harness at a different workspace.

    uv run python ../evals/image_similarity/e2e_gate.py
    uv run python ../evals/image_similarity/e2e_gate.py --only document_rerender
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
BASE = "http://127.0.0.1:8000"
DEPARTMENT = "eval-test"
# Storage happens in a FastAPI background task (or a Celery worker), so the
# prime is not queryable the instant its response returns.
STORE_WAIT_SECONDS = 25


def api_key() -> str:
    """The eval workspace's key, or the chat app's key as a fallback."""
    if os.environ.get("DEJAQ_EVAL_KEY"):
        return os.environ["DEJAQ_EVAL_KEY"]
    env = (ROOT / "chat" / ".env.local").read_text()
    m = re.search(r"^DEJAQ_API_KEY=(\S+)", env, re.M)
    if not m:
        raise SystemExit("set DEJAQ_EVAL_KEY, or put DEJAQ_API_KEY in chat/.env.local")
    return m.group(1)


def ask(image: Path, prompt: str, key: str, timeout: float = 180) -> dict:
    payload = {
        "model": "dejaq",
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image",
             "image_url": f"data:image/jpeg;base64,{base64.b64encode(image.read_bytes()).decode()}"},
        ]}],
    }
    req = urllib.request.Request(
        f"{BASE}/v1/responses", method="POST",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}",
                 "X-DejaQ-Department": DEPARTMENT},
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
            headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}: {exc.read()[:200].decode('utf-8', 'replace')}"}
    return {
        "tier": headers.get("x-dejaq-tier", "?"),
        "hit": headers.get("x-dejaq-tier") == "cache",
        "distance": headers.get("x-dejaq-cache-distance"),
        "matched": headers.get("x-dejaq-cache-matched-query"),
        "seconds": round(time.perf_counter() - start, 1),
        "text": (body.get("output_text") or "")[:80],
    }


class Case(NamedTuple):
    name: str
    prime: Path | None
    prime_q: str
    probe: Path | None
    probe_q: str
    expect_hit: bool
    why: str
    # True when a MISS here is a measured limitation the project has accepted,
    # not a defect. Kept in the suite because a limitation that quietly becomes
    # a HIT is exactly the regression worth catching.
    known_limit: bool = False


def scenarios() -> list[Case]:
    corpus = HERE / "corpus"
    photos = HERE / "corpus_photos"
    aug = HERE / "dataset"
    screens = HERE / "corpus_screens"
    recap = HERE / "corpus_recapture"
    # Two sittings of one course: same template, different paper.
    exams = sorted(p for p in corpus.glob("*__p1__dpi150_full.png") if "נושא" in p.name)
    exam_a = exams[0] if exams else None
    exam_b = exams[1] if len(exams) > 1 else None

    def variant(page: Path | None, capture: str) -> Path | None:
        return page.parent / page.name.replace("dpi150_full", capture) if page else None

    reframed = variant(exam_a, "dpi150_tight")   # same render, small reframe
    rescaled = variant(exam_a, "dpi200_tight")   # different DPI and reframe
    hol = sorted(photos.glob("hol01000_*.jpg"))
    # Every scenario asks about something different ON PURPOSE. The cache is
    # keyed on the normalised text, so two scenarios sharing a prompt land on
    # one entry and each one's probe is then gated against the other one's
    # image. Distinct subjects keep the scenarios independent.
    return [
        Case("document_same_image", exam_a, "Explain question 1 in this exam.",
             exam_a, "Explain question 1 in this exam.", True,
             "byte-identical re-upload: the floor of the whole feature"),
        Case("document_reframed", exam_a, "Summarise what this page covers.",
             reframed, "Summarise what this page covers.", True,
             "same render, cropped slightly differently"),
        Case("document_rescaled", exam_a, "Which topics appear on this page?",
             rescaled, "Which topics appear on this page?", False,
             "same page at another DPI - OCR reads different words", known_limit=True),
        Case("document_paraphrase", exam_a, "Explain the main task on this page.",
             exam_a, "Can you walk me through the main task here?", True,
             "same image, same intent, different words"),
        Case("document_other_question", exam_a, "Explain the grading scheme here.",
             exam_a, "Who is the lecturer for this course?", False,
             "same image, a different question - the validator must refuse"),
        Case("document_sibling_exam", exam_a, "List the questions on this paper.",
             exam_b, "List the questions on this paper.", False,
             "a different sitting of the same course on the same template"),
        Case("photo_reupload", aug / "src001__original.jpg", "What is in this picture?",
             aug / "src001__recompressed.jpg", "What is in this picture?", True,
             "the same photo re-uploaded after recompression"),
        Case("photo_second_shot", hol[0] if hol else None, "Describe this scene.",
             hol[1] if len(hol) > 1 else None, "Describe this scene.", False,
             "a second photo of one scene - dHash separates these", known_limit=True),
        Case("photo_vs_document", aug / "src001__original.jpg", "What colours dominate here?",
             exam_a, "What colours dominate here?", False,
             "a photo request must never match a document entry"),
        Case("screenshot_recrop", screens / "rico0001__full_whole.jpg",
             "What does this screen do?", screens / "rico0001__small_tight.jpg",
             "What does this screen do?", True, "the same screenshot, reframed"),
        # This one HITS, which was a surprise: the complaint that started the
        # image work was that photographing a screen missed. Measured over 134
        # UHDM pairs the photo path serves 76.9% of them with no false merges,
        # because a camera capture keeps the framing and CLIP tolerates moire.
        Case("recapture_of_screen", recap / "uhdm0000_screen.jpg", "What is on this screen?",
             recap / "uhdm0000_photo.jpg", "What is on this screen?", True,
             "a camera photo of the screen showing the primed image"),
    ]


def main(only: str | None) -> int:
    key = api_key()
    rows, failures = [], 0
    for c in scenarios():
        if only and only != c.name:
            continue
        if not c.prime or not c.probe or not c.prime.exists() or not c.probe.exists():
            print(f"SKIP {c.name}: corpus image missing")
            continue
        print(f"\n--- {c.name}: {c.why}")
        primed = ask(c.prime, c.prime_q, key)
        print(f"    prime {c.prime.name} -> {primed}")
        if primed.get("error"):
            failures += 1
            continue
        time.sleep(STORE_WAIT_SECONDS)
        got = ask(c.probe, c.probe_q, key)
        print(f"    probe {c.probe.name} -> {got}")
        ok = got.get("hit") == c.expect_hit
        failures += not ok
        print(f"    {'PASS' if ok else 'FAIL'}: expected "
              f"{'HIT' if c.expect_hit else 'MISS'}, got {'HIT' if got.get('hit') else 'MISS'}")
        rows.append((c, bool(got.get("hit")), ok, got.get("seconds")))

    print(f"\n{'scenario':<26}{'expected':>10}{'got':>8}{'':>6}{'s':>6}  note")
    for c, hit, ok, secs in rows:
        note = "accepted limitation" if c.known_limit else ""
        print(f"{c.name:<26}{'HIT' if c.expect_hit else 'MISS':>10}"
              f"{'HIT' if hit else 'MISS':>8}{'ok' if ok else 'FAIL':>6}{secs or 0:>6}  {note}")
    print(f"\n{len(rows) - failures}/{len(rows)} scenarios behaved as specified")
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="run a single scenario by name")
    sys.exit(main(ap.parse_args().only))
