class ExternalLLMError(Exception):
    """Generic error from an external LLM provider (rate limit, network, etc.).

    `status_code` carries the provider's own HTTP status when the SDK exposes
    one (400/401/429/...), so the router can surface a permanent
    misconfiguration distinctly from a transient failure instead of collapsing
    both into the same apology.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ExternalLLMAuthError(ExternalLLMError):
    """Raised when the API key is missing or invalid."""


class ExternalLLMTimeoutError(ExternalLLMError):
    """Raised when the external LLM request exceeds the configured timeout."""


class ExternalAttachmentUnsupportedError(Exception):
    """Raised when the workspace's configured external model has no
    capability for the attachment on this request (image or PDF document).

    Detected proactively, before the request is sent, via LiteLLM's own
    model catalog (see litellm_transport.py) - the mirror of
    LocalVisionUnsupportedError for the external path. Only raised when the
    catalog affirmatively confirms the model lacks the capability; a model
    LiteLLM has no entry for (an older or very new id it hasn't catalogued
    yet) is not evidence of incapability and is left to reach the provider
    as before.
    """

    def __init__(self, model_name: str, kind: str) -> None:
        self.model_name = model_name
        self.kind = kind  # "image" or "document"
        super().__init__(f"External model {model_name} has no {kind} capability")


class ExternalAttachmentTooLargeError(Exception):
    """Raised when a request's estimated token footprint exceeds the
    workspace's external model's own input-token budget.

    The external-path mirror of `local_attachment_max_tokens`
    (openai_compat.py's bound on the LOCAL context window): a PDF or image
    attachment already goes as a native provider part with its own
    size handling, but a plain text/Markdown/code attachment is inlined
    directly into the prompt (`_query_with_inlined_file`) with nothing
    standing between it and the model's context window. A file legally
    under DejaQ's own 10 MB attachment cap, and under the local model's own
    attachment budget (which is why the request routes external in the first
    place), can still overflow the EXTERNAL model's own - often much smaller
    - effective context, surfacing previously as the same opaque provider
    400 fix #3 already removed for the capability case.

    Detected proactively via LiteLLM's own model catalog
    (max_input_tokens/max_tokens), the same data source
    `_confirmed_incapable` uses for the capability gate - never raised for a
    model LiteLLM has no catalog entry for, the same conservative bias (a
    data gap is not evidence the request is too large).
    """

    def __init__(self, model_name: str, estimated_tokens: int, budget_tokens: int) -> None:
        self.model_name = model_name
        self.estimated_tokens = estimated_tokens
        self.budget_tokens = budget_tokens
        super().__init__(
            f"External model {model_name} input budget is ~{budget_tokens} tokens; "
            f"request is estimated at ~{estimated_tokens} tokens"
        )
