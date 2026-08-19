from pydantic import BaseModel, Field


class ExternalLLMRequest(BaseModel):
    query: str = Field(..., description="The user's query to send to the external LLM")
    history: list[dict] = Field(default_factory=list, description="Multi-turn conversation messages")
    system_prompt: str = Field(
        "You are a helpful assistant. Answer the user's query concisely and accurately.",
        description="System prompt guiding the external model's behavior",
    )
    model: str = Field(..., description="External model name to use")
    max_tokens: int = Field(1024, description="Maximum tokens to generate")
    temperature: float | None = Field(
        None, description="Sampling temperature; omitted from the provider call when unset"
    )
    image_b64: str | None = Field(None, description="Base64 image bytes attached to the query, if any")
    image_mime: str | None = Field(None, description="MIME type of the attached image, e.g. image/jpeg")
    # PDFs only. Every other file kind (DOCX, Markdown, plain text, source/config
    # files) is inlined into `query` instead — once extracted it is already text,
    # and no provider has a native part to send it as.
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


class ExternalStreamChunk(BaseModel):
    """One incremental piece of a streamed external-provider answer.

    `text` carries new characters. The LAST chunk carries `final` and no text:
    usage counts and the finish reason are only known once the provider has
    closed the stream, and they are exactly the fields the store guards and
    the usage block need. Same contract shape as
    `model_backends.CompletionChunk` on the local path.
    """

    text: str = Field("", description="Newly generated characters")
    final: ExternalLLMResponse | None = Field(
        None, description="Set on the terminal chunk only: usage + finish_reason"
    )
