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
