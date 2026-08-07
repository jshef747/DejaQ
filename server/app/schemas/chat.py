from pydantic import BaseModel, Field


class ExternalLLMRequest(BaseModel):
    query: str = Field(..., description="The user's query to send to the external LLM")
    history: list[dict] = Field(default_factory=list, description="Multi-turn conversation messages")
    system_prompt: str = Field(
        "You are a helpful assistant. Answer the user's query concisely and accurately.",
        description="System prompt guiding the external model's behavior",
    )
    model: str = Field("gemini-2.5-flash", description="External model name to use")
    max_tokens: int = Field(1024, description="Maximum tokens to generate")
    temperature: float = Field(0.7, description="Sampling temperature")
    image_b64: str | None = Field(None, description="Base64 image bytes attached to the query, if any")
    image_mime: str | None = Field(None, description="MIME type of the attached image, e.g. image/jpeg")
    # PDFs only. Markdown is inlined into `query` instead — it is already text,
    # and no provider has a markdown part to send it as.
    file_b64: str | None = Field(None, description="Base64 PDF bytes attached to the query, if any")
    file_mime: str | None = Field(None, description="MIME type of the attached file, e.g. application/pdf")
    file_name: str | None = Field(None, description="Original filename, sent where the provider wants one")


class ExternalLLMResponse(BaseModel):
    text: str = Field(..., description="The generated response text")
    model_used: str = Field(..., description="Actual model that produced the response")
    prompt_tokens: int = Field(0, description="Number of input tokens consumed")
    completion_tokens: int = Field(0, description="Number of output tokens generated")
    latency_ms: float = Field(0.0, description="Total request time in milliseconds")
    # Normalized to "stop" | "length" by each provider client (see
    # llm_providers/common.py:normalize_finish_reason) from that provider's
    # own stop/finish reason (Anthropic stop_reason, OpenAI finish_reason,
    # Google finish_reason) — the same truncation signal OllamaBackend
    # captures for local generation, so the client-facing finish_reason can
    # be honest regardless of which route answered the request.
    finish_reason: str = Field("stop", description="'stop' if the model finished naturally, 'length' if the token budget cut it off")
