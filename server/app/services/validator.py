import logging
import time

from app.config import OLLAMA_NUM_CTX, VALIDATOR_MODEL_NAME
from app.services.model_backends import (
    CompletionRequest,
    ModelBackend,
    complete_with_default_fallback,
)

logger = logging.getLogger("dejaq.services.validator")

DEFAULT_SYSTEM_PROMPT = (
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
    # --- Single-word swap, same template: the answer is about a DIFFERENT thing → INVALID ---
    (
        "CACHED QUESTION: what is the boiling point of water?\n"
        "CACHED ANSWER: Water boils at 100 degrees Celsius at sea level.\n"
        "NEW QUESTION: what is the freezing point of water?",
        "INVALID",
    ),
    # --- Single-word swap in a coding question → INVALID ---
    (
        "CACHED QUESTION: how do i reverse a string in python?\n"
        "CACHED ANSWER: Use slicing: s[::-1] reverses a string in Python.\n"
        "NEW QUESTION: how do i reverse a list in python?",
        "INVALID",
    ),
    # --- Long question, one swapped term changes the subject → INVALID ---
    (
        "CACHED QUESTION: when should i use multiprocessing instead of multithreading in python?\n"
        "CACHED ANSWER: Use multiprocessing for CPU-bound work: each process has its own interpreter "
        "and memory space, bypassing the GIL. Threads share memory and suit I/O-bound work.\n"
        "NEW QUESTION: when should i use asyncio instead of multithreading in python?",
        "INVALID",
    ),
    # --- Heavy typos, same question → VALID (typos never change the ask) ---
    (
        "CACHED QUESTION: what is the capital of russia?\n"
        "CACHED ANSWER: The capital of Russia is Moscow.\n"
        "NEW QUESTION: what is teh captial of rusia?",
        "VALID",
    ),
]

# --- Image-anchored mode: compare QUESTION to QUESTION, never to the answer ---
# When the image gate accepted a hit it has already proven the two requests carry
# the SAME image. The answer is then useless to the validator: an image query's
# meaning lives in the picture ("how to solve?"), so judging "does this answer
# cover this question?" is underdetermined and over-rejects (observed live:
# "how to solve this?" vs "how to solve?" at distance 0.0753 was rejected).
# The one thing left to check is whether the two questions ask for the same
# thing about that image — and the embedding cannot do it: numbered-item swaps
# land at distance 0.0867-0.1351, overlapping legitimate paraphrases
# (0.0753-0.1094). See docs/image-gate.md.
DEFAULT_IMAGE_SYSTEM_PROMPT = (
    "Two questions were asked about THE SAME image. The image has already been verified "
    "identical, so you do NOT need to see it.\n"
    "Decide whether both questions ask for the same thing about that image.\n"
    "Reply with exactly one word: VALID or INVALID.\n"
    "VALID = the same request, reworded, retyped with typos, or asked in a different tone.\n"
    "INVALID = a different part, element, item, or fact of the image, a different number or "
    "letter (question 1 vs question 2, part a vs part b), or a different task on it "
    "(reading vs translating vs summarising).\n"
    "One question containing the other does NOT make them the same. Judge the extra words:\n"
    "- extra words about tone or depth (simply, in short, step by step, in detail) = same "
    "request, VALID.\n"
    "- extra words changing the output language or form (in Hebrew, translate, as a table, "
    "as code) = different request, INVALID.\n"
    "The image content is unknown to you, so a difference you cannot resolve is a real "
    "difference: when in doubt, choose INVALID."
)

_IMAGE_FEW_SHOTS = [
    # Paraphrase — the live false rejection this mode exists to fix.
    ("CACHED QUESTION: how to solve this?\nNEW QUESTION: how to solve?", "VALID"),
    # Tone only.
    ("CACHED QUESTION: explain this\nNEW QUESTION: explain this simply", "VALID"),
    # Typos never change the ask.
    ("CACHED QUESTION: what is in this image?\nNEW QUESTION: waht is in ths image?", "VALID"),
    # Numbered-item swap: the worksheet trap. Distance 0.0867-0.1026 — trusted zone.
    (
        "CACHED QUESTION: what is the answer to question 1?\n"
        "NEW QUESTION: what is the answer to question 2?",
        "INVALID",
    ),
    ("CACHED QUESTION: solve part a\nNEW QUESTION: solve part b", "INVALID"),
    # Different element of the same document.
    (
        "CACHED QUESTION: what does the title say?\nNEW QUESTION: what is the lecturer name?",
        "INVALID",
    ),
    # Different task on the same image.
    ("CACHED QUESTION: what does this say?\nNEW QUESTION: translate this to english", "INVALID"),
    # Containment: the new question is the old one plus a form-changing modifier.
    ("CACHED QUESTION: summarize this\nNEW QUESTION: summarize this in hebrew", "INVALID"),
]

# Word-count cap on cached_answer before validator call.
# At ~400 words (~500 tokens) we stay under ~42% of the 2048-ctx window,
# safely below the 56% threshold where the model outputs garbage.
_MAX_ANSWER_WORDS = 400


class ValidatorService:
    def __init__(
        self,
        backend: ModelBackend,
        model_name: str,
        system_prompt: str | None = None,
        image_system_prompt: str | None = None,
    ):
        self.backend = backend
        self.model_name = model_name
        # Few-shots for both modes stay hardcoded - only the two system
        # prompts are per-workspace overrides (see llm_config_service.py).
        self.system_prompt = system_prompt if system_prompt is not None else DEFAULT_SYSTEM_PROMPT
        self.image_system_prompt = (
            image_system_prompt if image_system_prompt is not None else DEFAULT_IMAGE_SYSTEM_PROMPT
        )

    async def validate(
        self,
        new_query: str,
        cached_query: str,
        cached_answer: str,
        mismatch_hint: str | None = None,
        attachment_anchored: bool = False,
    ) -> tuple[bool, str]:
        """Return (is_valid, raw_verdict). Fail-safe: unparseable output → False (INVALID).

        mismatch_hint: optional note naming the word pairs where the two
        questions differ (e.g. "'list' vs 'string'") — computed by the lexical
        alignment gate. Sharpens the verdict on single-word-swap traps, where
        near-identical wording otherwise invites a false VALID.

        attachment_anchored: the image gate (or the file gate, which proves it
        exactly) already established that both requests carry the same attachment,
        so cached_answer is ignored and the two QUESTIONS are compared instead
        (see DEFAULT_IMAGE_SYSTEM_PROMPT). The prompt is worded around images because
        that is where the failure mode was measured — numbered-item siblings like
        "solve part a"/"part b" sit CLOSER in embedding space than legitimate
        paraphrases — but the question it asks ("do these ask for the same thing
        about the same attachment?") is identical for a PDF.
        """
        if attachment_anchored:
            system_prompt, few_shots = self.image_system_prompt, _IMAGE_FEW_SHOTS
            cached_answer = ""  # never sent in this mode
            final = f"CACHED QUESTION: {cached_query}\nNEW QUESTION: {new_query}"
        else:
            system_prompt, few_shots = self.system_prompt, _FEW_SHOTS
            words = cached_answer.split()
            if len(words) > _MAX_ANSWER_WORDS:
                cached_answer = " ".join(words[:_MAX_ANSWER_WORDS])
            final = (
                f"CACHED QUESTION: {cached_query}\n"
                f"CACHED ANSWER: {cached_answer}\n"
                f"NEW QUESTION: {new_query}"
            )
        if mismatch_hint:
            final += (
                f"\nNOTE: the new question differs from the cached question at these words: "
                f"{mismatch_hint}. If any of these word differences change what is being "
                f"asked, reply INVALID."
            )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for user_msg, assistant_msg in few_shots:
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": assistant_msg})
        messages.append({"role": "user", "content": final})

        was_truncated = len(cached_answer.split()) >= _MAX_ANSWER_WORDS

        start = time.time()
        raw = (await complete_with_default_fallback(
            self.backend,
            CompletionRequest(
                model_name=self.model_name,
                messages=messages,
                max_tokens=8,
                # A one-word verdict needs nothing near this window. It is set
                # to match generalize(), which runs on the SAME model
                # (gemma4:e2b): Ollama treats a changed runner option as a
                # reload, so two different windows make it unload and reload
                # the model between roles - here on the synchronous band-hit
                # path, in front of a waiting user. Costs no extra memory - the
                # model is already loaded at this window whenever generalize()
                # runs.
                num_ctx=OLLAMA_NUM_CTX,
                temperature=0.0,
            ),
            VALIDATOR_MODEL_NAME,
            "validator",
        )).text
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
