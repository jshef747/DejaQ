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


class ExternalLLMResponse(BaseModel):
    text: str = Field(..., description="The generated response text")
    model_used: str = Field(..., description="Actual model that produced the response")
    prompt_tokens: int = Field(0, description="Number of input tokens consumed")
    completion_tokens: int = Field(0, description="Number of output tokens generated")
    latency_ms: float = Field(0.0, description="Total request time in milliseconds")
