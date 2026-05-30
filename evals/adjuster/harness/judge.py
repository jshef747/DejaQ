"""LLM-as-judge for tone matching evaluation.

Uses Claude Haiku 4.5 to score how well the adjusted answer matches the
tone/style of the original query. Returns a 1-5 score per scenario.

Requires ANTHROPIC_API_KEY environment variable.
"""

from __future__ import annotations

import json
import logging
import time

import anthropic

logger = logging.getLogger("harness.judge")

MODEL = "claude-haiku-4-5-20251001"

JUDGE_SYSTEM = """\
You are an expert evaluator of writing tone and style. You will be given:
1. A user QUERY written in a specific tone/style
2. A NEUTRAL ANSWER (factual, no personality)
3. An ADJUSTED ANSWER that was supposed to rewrite the neutral answer to match the query's tone

Score the ADJUSTED ANSWER on two dimensions:

**tone_score** (1-5): How well does the adjusted answer match the tone/style of the query?
- 5: Perfect tone match — reads like a natural response to that specific query style
- 4: Good match — clearly adapted to the tone with minor inconsistencies
- 3: Partial match — some tone adaptation but still feels off or mixed
- 2: Weak match — barely adapted, mostly neutral/generic
- 1: No match — tone is completely wrong or unchanged from neutral

**content_score** (1-5): How well does the adjusted answer preserve the facts from the neutral answer?
- 5: All facts preserved accurately
- 4: Nearly all facts preserved, minor omissions
- 3: Most facts preserved but some missing or altered
- 2: Significant facts missing or incorrect
- 1: Most facts lost or wrong

Respond with ONLY a JSON object: {"tone_score": N, "content_score": N, "tone_reason": "brief reason", "content_reason": "brief reason"}"""

JUDGE_USER_TEMPLATE = """\
QUERY: {query}

NEUTRAL ANSWER: {neutral_answer}

ADJUSTED ANSWER: {adjusted}"""


def create_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def judge_single(
    client: anthropic.Anthropic,
    query: str,
    neutral_answer: str,
    adjusted: str,
) -> dict:
    """Score a single adjusted answer. Returns dict with tone_score, content_score, reasons."""
    user_msg = JUDGE_USER_TEMPLATE.format(
        query=query,
        neutral_answer=neutral_answer,
        adjusted=adjusted,
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = response.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        result = json.loads(text)
        # Validate scores are in range
        result["tone_score"] = max(1, min(5, int(result["tone_score"])))
        result["content_score"] = max(1, min(5, int(result["content_score"])))
        return result
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("Judge parse error: %s — raw: %s", e, text)
        return {
            "tone_score": 0,
            "content_score": 0,
            "tone_reason": f"parse_error: {text[:200]}",
            "content_reason": "parse_error",
        }


def judge_batch(
    rows: list[dict],
) -> list[dict]:
    """Score a batch of rows. Each row needs query, neutral_answer, adjusted fields.

    Returns list of judge result dicts aligned with input rows.
    """
    client = create_client()
    results: list[dict] = []
    total = len(rows)

    for i, row in enumerate(rows):
        start = time.time()
        result = judge_single(
            client,
            row["query"],
            row["neutral_answer"],
            row["adjusted"],
        )
        elapsed = (time.time() - start) * 1000

        results.append(result)

        if (i + 1) % 10 == 0 or (i + 1) == total:
            logger.info(
                "  Judge: %d/%d scored (tone=%d, content=%d, %.0fms)",
                i + 1, total,
                result["tone_score"], result["content_score"],
                elapsed,
            )

    return results
