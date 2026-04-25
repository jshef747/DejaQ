import time
import logging
from google import genai
from google.genai import types, errors as genai_errors

from app.config import GEMINI_API_KEY, EXTERNAL_MODEL_NAME
from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse
from app.utils.exceptions import ExternalLLMError, ExternalLLMAuthError, ExternalLLMTimeoutError

logger = logging.getLogger("dejaq.services.external_llm")

_TIMEOUT_SECONDS = 30.0


class ExternalLLMService:
    _instance: "ExternalLLMService | None" = None

    def __new__(cls) -> "ExternalLLMService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = None
        return cls._instance

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not GEMINI_API_KEY:
                raise ExternalLLMAuthError(
                    "GEMINI_API_KEY is not set. Configure it via the GEMINI_API_KEY environment variable."
                )
            self._client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("Gemini client initialized (model=%s)", EXTERNAL_MODEL_NAME)
        return self._client

    async def generate_response(self, request: ExternalLLMRequest) -> ExternalLLMResponse:
        if not request.query:
            raise ValueError("ExternalLLMRequest.query must not be empty.")

        client = self._get_client()

        # Convert history from OpenAI format (role="assistant") to Gemini format (role="model")
        contents: list[types.Content] = []
        for msg in request.history:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=request.query)]))

        config = types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            max_output_tokens=request.max_tokens,
            temperature=request.temperature,
        )

        logger.debug(
            "Sending hard query to Gemini model=%s history_turns=%d",
            request.model,
            len(request.history),
        )

        start = time.perf_counter()
        try:
            response = await client.aio.models.generate_content(
                model=request.model,
                contents=contents,
                config=config,
            )
        except genai_errors.ClientError as exc:
            if exc.code == 401:
                logger.error("Gemini authentication failed: %s", exc)
                raise ExternalLLMAuthError(f"Authentication failed: {exc}") from exc
            logger.error("Gemini client error (code=%d): %s", exc.code, exc)
            raise ExternalLLMError(f"Provider error: {exc}") from exc
        except genai_errors.APIError as exc:
            logger.error("Gemini API error: %s", exc)
            raise ExternalLLMError(f"Provider error: {exc}") from exc

        latency_ms = (time.perf_counter() - start) * 1000
        text = response.text or ""
        usage = response.usage_metadata

        logger.debug(
            "Gemini request successful (model=%s, latency=%.2f ms, prompt_tokens=%d, completion_tokens=%d)",
            request.model,
            latency_ms,
            usage.prompt_token_count if usage else 0,
            usage.candidates_token_count if usage else 0,
        )

        return ExternalLLMResponse(
            text=text,
            model_used=request.model,
            prompt_tokens=usage.prompt_token_count if usage else 0,
            completion_tokens=usage.candidates_token_count if usage else 0,
            latency_ms=latency_ms,
        )
