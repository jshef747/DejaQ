import time

from app.schemas.chat import ExternalLLMRequest


def redact_api_key(message: object, api_key: str) -> str:
    text = str(message)
    if api_key:
        return text.replace(api_key, "<redacted>")
    return text


def ensure_query(request: ExternalLLMRequest) -> None:
    if not request.query:
        raise ValueError("ExternalLLMRequest.query must not be empty.")


def elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


# Each provider names "the token budget cut this off" differently (Anthropic
# "max_tokens", OpenAI "length", Google "MAX_TOKENS"/FinishReason.MAX_TOKENS)
# and every other reason (safety filters, tool calls, natural completion)
# with its own vocabulary too. ExternalLLMResponse.finish_reason only needs
# to answer one question honestly — was the answer cut off by the token
# budget — so this collapses every provider's raw value to "length" for that
# one case and "stop" for everything else, rather than inventing a third
# schema of finish-reason literals downstream code would have to branch on.
_LENGTH_MARKERS = frozenset({"max_tokens", "length", "MAX_TOKENS"})


def normalize_finish_reason(raw_reason: object) -> str:
    text = str(raw_reason) if raw_reason is not None else ""
    # Covers enum reprs like "FinishReason.MAX_TOKENS" as well as bare values.
    return "length" if any(marker in text for marker in _LENGTH_MARKERS) else "stop"
