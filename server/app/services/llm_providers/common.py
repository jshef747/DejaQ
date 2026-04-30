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
