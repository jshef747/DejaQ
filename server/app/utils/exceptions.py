class ExternalLLMError(Exception):
    """Generic error from an external LLM provider (rate limit, network, etc.)."""


class ExternalLLMAuthError(ExternalLLMError):
    """Raised when the API key is missing or invalid."""


class ExternalLLMTimeoutError(ExternalLLMError):
    """Raised when the external LLM request exceeds the configured timeout."""
