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
