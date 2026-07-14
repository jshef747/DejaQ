import logging
import time

from app.services.model_backends import CompletionRequest, ModelBackend

logger = logging.getLogger("dejaq.services.validator")

_SYSTEM_PROMPT = (
    "You decide if a CACHED ANSWER can correctly answer a NEW QUESTION.\n"
    "Reply with exactly one word: VALID or INVALID.\n"
    "VALID = the cached answer covers what the new question is asking — same topic, same "
    "scope, addresses the information need. It does not have to use the exact same words.\n"
    "INVALID = the cached answer is about a different entity, a clearly different topic, "
    "or the new question asks for an additional specific fact the answer does not contain.\n"
    "Three rules:\n"
    "- PARAPHRASE: A different phrasing of the same question is VALID if the answer "
    "covers it. Do not penalise word-order or synonym differences.\n"
    "- MULTIPLE FACTS: If the new question asks for two or more distinct facts (e.g. 'A "
    "and B'), the answer must contain ALL of them. A partial answer is INVALID.\n"
    "- TONE: Ignore tone, formality, and language style. Casual or slang phrasing that "
    "asks for the same information is VALID if the answer contains it.\n"
    "When in doubt, choose VALID. A wrong INVALID only costs a cache miss; the LLM "
    "will answer correctly. A wrong INVALID is always recoverable — a wrong VALID is not."
)

_FEW_SHOTS = [
    # --- Factoid: same question, rephrased ---
    (
        "CACHED QUESTION: What is the capital of France?\n"
        "CACHED ANSWER: The capital of France is Paris.\n"
        "NEW QUESTION: What is France's capital city?",
        "VALID",
    ),
    # --- Tone/slang: same information need ---
    (
        "CACHED QUESTION: What is gravity?\n"
        "CACHED ANSWER: Gravity is a fundamental force that attracts objects with mass toward each other.\n"
        "NEW QUESTION: bro what even is gravity and why do things fall",
        "VALID",
    ),
    # --- CS conceptual: paraphrase → VALID ---
    (
        "CACHED QUESTION: why does writing past the end of a malloc'd array not always crash immediately?\n"
        "CACHED ANSWER: Writing past the end of a malloc'd array is undefined behaviour. It doesn't always "
        "crash immediately because malloc reserves memory in aligned blocks, so the bytes just past your "
        "array may belong to the heap's internal bookkeeping or another allocation. The crash is "
        "non-deterministic and depends on what occupies that memory.\n"
        "NEW QUESTION: I used malloc for an array and wrote one element past the end but it didn't segfault — why?",
        "VALID",
    ),
    # --- CS conceptual: rephrased question, same topic, answer covers it → VALID ---
    (
        "CACHED QUESTION: what is the difference between heapify-up and heapify-down in a min-heap?\n"
        "CACHED ANSWER: heapify-up (also called sift-up or bubble-up) is used after inserting a new element: "
        "you place the element at the end and swap it upward until the heap property is restored. "
        "heapify-down (sift-down) is used after removing the root: you replace the root with the last "
        "element and push it down by swapping with the smaller child until the property is restored.\n"
        "NEW QUESTION: when do I call heapify-up vs heapify-down in a heap?",
        "VALID",
    ),
    # --- Different entity → INVALID ---
    (
        "CACHED QUESTION: What is the capital of France?\n"
        "CACHED ANSWER: The capital of France is Paris.\n"
        "NEW QUESTION: What is the capital of Germany?",
        "INVALID",
    ),
    # --- Missing additional fact → INVALID ---
    (
        "CACHED QUESTION: Who wrote Hamlet?\n"
        "CACHED ANSWER: Hamlet was written by William Shakespeare.\n"
        "NEW QUESTION: Who wrote Hamlet and when was it written?",
        "INVALID",
    ),
    # --- Related but different topic → INVALID ---
    (
        "CACHED QUESTION: What is machine learning?\n"
        "CACHED ANSWER: Machine learning is a branch of AI where systems learn from data to make predictions.\n"
        "NEW QUESTION: What is deep learning?",
        "INVALID",
    ),
    # --- CS: different topic even though related area → INVALID ---
    (
        "CACHED QUESTION: what is the difference between an AVL tree and a Red-Black tree?\n"
        "CACHED ANSWER: Both are self-balancing BSTs with O(log n) operations. AVL trees are more strictly "
        "balanced (height difference ≤ 1) so lookups are faster, but insertions require more rotations. "
        "Red-Black trees allow a height ratio up to 2:1 so insertions are cheaper, which is why std::map "
        "uses them.\n"
        "NEW QUESTION: how does a B-tree differ from a binary search tree?",
        "INVALID",
    ),
]

# Word-count cap on cached_answer before validator call.
# At ~400 words (~500 tokens) we stay under ~42% of the 2048-ctx window,
# safely below the 56% threshold where the model outputs garbage.
_MAX_ANSWER_WORDS = 400


class ValidatorService:
    def __init__(self, backend: ModelBackend, model_name: str):
        self.backend = backend
        self.model_name = model_name

    async def validate(
        self,
        new_query: str,
        cached_query: str,
        cached_answer: str,
    ) -> tuple[bool, str]:
        """Return (is_valid, raw_verdict). Fail-safe: unparseable output → False (INVALID)."""
        words = cached_answer.split()
        if len(words) > _MAX_ANSWER_WORDS:
            cached_answer = " ".join(words[:_MAX_ANSWER_WORDS])

        messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        for user_msg, assistant_msg in _FEW_SHOTS:
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": assistant_msg})
        messages.append({
            "role": "user",
            "content": (
                f"CACHED QUESTION: {cached_query}\n"
                f"CACHED ANSWER: {cached_answer}\n"
                f"NEW QUESTION: {new_query}"
            ),
        })

        was_truncated = len(cached_answer.split()) >= _MAX_ANSWER_WORDS

        start = time.time()
        raw = await self.backend.complete(
            CompletionRequest(
                model_name=self.model_name,
                messages=messages,
                max_tokens=8,
                temperature=0.0,
            )
        )
        latency_ms = (time.time() - start) * 1000

        first_token = raw.strip().split()[0].upper() if raw.strip() else ""
        if first_token == "VALID":
            logger.debug(
                "validator verdict=VALID latency=%.1fms truncated=%s query=%r",
                latency_ms, was_truncated, new_query[:80],
            )
            return True, raw
        if first_token == "INVALID":
            logger.debug(
                "validator verdict=INVALID latency=%.1fms truncated=%s query=%r",
                latency_ms, was_truncated, new_query[:80],
            )
            return False, raw
        logger.warning(
            "validator verdict=UNPARSEABLE raw=%r latency=%.1fms query=%r; treating as INVALID",
            raw[:40], latency_ms, new_query[:60],
        )
        return False, raw
