"""Measure the image-anchored validator mode (question vs question) on the real model.

The image gate already proved both requests carry the same image; the only
question left is whether the two QUESTIONS ask for the same thing about it.
The embedding cannot decide that: numbered-item swaps land at BGE distance
0.0867-0.1351, overlapping legitimate paraphrases at 0.0753-0.1094 — hence a
model call. This script checks the prompt actually separates them.

Pass bar: 0 sibling pairs answered VALID. A missed paraphrase costs a cache
miss; a served sibling serves the wrong answer.

    cd server && uv run python ../evals/validator/scripts/image_intent_check.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "server"))

from app.services.service_factory import get_validator_service  # noqa: E402

# (must_hit, cached_query, new_query, measured BGE distance)
PAIRS: list[tuple[bool, str, str, float]] = [
    # --- paraphrases: must be VALID ---
    (True, "how to solve this?", "how to solve?", 0.0753),
    (True, "explain this", "explain this simply", 0.0675),
    (True, "what is in this image?", "what does this image show?", 0.0803),
    (True, "solve this problem", "how do i solve this problem", 0.0984),
    (True, "what is this document about?", "what is the topic of this document?", 0.1094),
    (True, "what is in this image?", "waht is in ths image?", 0.0),
    (True, "summarize this", "give me a summary of this", 0.0),
    # Containment with a tone/depth modifier — must NOT be caught by the form rule.
    (True, "explain this", "explain this step by step", 0.0),
    (True, "solve this", "solve this in short", 0.0),
    # --- siblings: must be INVALID (the first three sit in the trusted zone) ---
    (False, "solve q1", "solve q2", 0.0867),
    (False, "solve part a", "solve part b", 0.0898),
    (False, "what is the answer to question 1?", "what is the answer to question 2?", 0.1026),
    (False, "how do i solve question 1?", "how do i solve question 3?", 0.1351),
    (False, "row 1", "row 2", 0.1175),
    (False, "explain line 3", "explain line 4", 0.1521),
    (False, "solve problem 5", "solve problem 6", 0.1342),
    (False, "what is the first question?", "what is the last question?", 0.2427),
    # Different task on the same content — reachable phrasings.
    (False, "solve this", "explain this", 0.1747),
    (False, "transcribe this text", "translate this text", 0.1603),
    (False, "what is written here?", "translate what is written here", 0.1359),
    # Verbatim few-shot: measures instruction-following, not generalisation.
    (False, "what does this say?", "translate this to english", 0.2497),
    (False, "what does the title say?", "what is the lecturer name?", 0.4631),
    (False, "summarize this syllabus", "who teaches this course?", 0.3395),
    (False, "how many credits is this course?", "when does this course start?", 0.2430),
    (False, "what is question 2?", "what is question 20?", 0.2193),
]

TRUSTED_MAX = 0.15  # DEJAQ_CACHE_TRUST_DISTANCE
BAND_MAX = 0.20  # DEJAQ_CACHE_BAND_MAX_DISTANCE — past this the validator is never called


async def main() -> int:
    validator = get_validator_service()
    await validator.validate("warmup", "warmup", "", image_anchored=True)  # exclude model load

    missed: list[str] = []
    false_serves: list[tuple[bool, str]] = []  # (reachable, description)
    latencies: list[float] = []

    print(f"{'exp':>7} {'got':>7} {'dist':>7}  pair   (* trusted zone, ~ out of reach)")
    for must_hit, cached, new, distance in PAIRS:
        start = time.perf_counter()
        accepted, raw = await validator.validate(new, cached, "", image_anchored=True)
        latencies.append((time.perf_counter() - start) * 1000)

        reachable = distance <= BAND_MAX
        mark = " " if accepted == must_hit else "X"
        zone = "*" if distance and distance <= TRUSTED_MAX else ("~" if not reachable else " ")
        print(
            f"{mark}{'VALID' if must_hit else 'INVALID':>6} {'VALID' if accepted else 'INVALID':>7}"
            f" {distance:>7.4f}{zone} {cached!r} vs {new!r}"
        )
        if accepted == must_hit:
            continue
        detail = f"{cached!r} vs {new!r} (distance {distance:.4f}) -> {raw.strip()[:20]!r}"
        (missed if must_hit else false_serves).append(detail if must_hit else (reachable, detail))

    hits = sum(1 for p in PAIRS if p[0])
    siblings = sum(1 for p in PAIRS if not p[0])
    blocking = [d for reachable, d in false_serves if reachable]
    latencies.sort()
    print(
        f"\nparaphrases {hits - len(missed)}/{hits} served"
        f" | siblings {siblings - len(false_serves)}/{siblings} rejected"
        f" ({len(blocking)} of them within cache reach)"
        f" | latency median {latencies[len(latencies) // 2]:.0f}ms max {latencies[-1]:.0f}ms"
    )
    for reachable, detail in false_serves:
        print(f"  {'BLOCKING' if reachable else 'out of reach'}: served {detail}")
    for detail in missed:
        print(f"  missed (costs a cache miss, not a wrong answer): {detail}")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
