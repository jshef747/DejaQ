import time
import logging
import openai
from openai import AsyncOpenAI

from app.config import OPENAI_API_KEY, EXTERNAL_MODEL_NAME, EXTERNAL_API_BASE
from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse
from app.utils.exceptions import ExternalLLMError, ExternalLLMAuthError, ExternalLLMTimeoutError

logger = logging.getLogger("dejaq.services.external_llm")

_MAX_RETRIES = 2
_TIMEOUT_SECONDS = 30.0


class ExternalLLMService:
    _instance: "ExternalLLMService | None" = None

    def __new__(cls) -> "ExternalLLMService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = None
        return cls._instance

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            if not OPENAI_API_KEY:
                raise ExternalLLMAuthError(
                    "OPENAI_API_KEY is not set. Configure it via the OPENAI_API_KEY environment variable."
                )
            kwargs: dict = {"api_key": OPENAI_API_KEY, "timeout": _TIMEOUT_SECONDS, "max_retries": _MAX_RETRIES}
            if EXTERNAL_API_BASE:
                kwargs["base_url"] = EXTERNAL_API_BASE
            self._client = AsyncOpenAI(**kwargs)
            logger.info("AsyncOpenAI client initialized (model=%s, base=%s)", EXTERNAL_MODEL_NAME, EXTERNAL_API_BASE or "default")
        return self._client

    async def generate_response(self, request: ExternalLLMRequest) -> ExternalLLMResponse:
        if not request.query:
            raise ValueError("ExternalLLMRequest.query must not be empty.")

        client = self._get_client()

        messages: list[dict] = [{"role": "system", "content": request.system_prompt}]
        messages.extend(request.history)
        messages.append({"role": "user", "content": request.query})

        logger.info(
            "Sending hard query to external LLM (model=%s, history_turns=%d): %.80s",
            request.model,
            len(request.history),
            request.query,
        )

        start = time.perf_counter()
        try:
            completion = await client.chat.completions.create(
                model=request.model,
                messages=messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
        except openai.AuthenticationError as exc:
            logger.error("External LLM authentication failed: %s", exc)
            raise ExternalLLMAuthError(f"Authentication failed: {exc}") from exc
        except openai.APITimeoutError as exc:
            logger.error("External LLM request timed out: %s", exc)
            raise ExternalLLMTimeoutError(f"Request timed out after {_TIMEOUT_SECONDS}s") from exc
        except openai.RateLimitError as exc:
            logger.error("External LLM rate limit hit: %s", exc)
            raise ExternalLLMError(f"Rate limit exceeded: {exc}") from exc
        except openai.APIError as exc:
            logger.error("External LLM API error: %s", exc)
            raise ExternalLLMError(f"Provider error: {exc}") from exc

        latency_ms = (time.perf_counter() - start) * 1000
        text = completion.choices[0].message.content or ""
        usage = completion.usage

        logger.info(
            "External API request successful (model=%s, latency=%.2f ms, prompt_tokens=%d, completion_tokens=%d)",
            completion.model,
            latency_ms,
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        )

        return ExternalLLMResponse(
            text=text,
            model_used=completion.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
        )
