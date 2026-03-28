from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Any

class ChatRequest(BaseModel):
    user_id: str = Field(..., description="The ID of the user sending the message")
    message: str = Field(..., description="The content of the message being sent")
    department_id: str = Field(..., description="The department the message is related to")
    conversation_id: Optional[str] = Field(None, description="ID of the conversation for multi-turn chat")

class ChatResponse(BaseModel):
    sender: str = Field(..., description="Who sent this message (user/system/bot)")
    message: str = Field(..., description="The content of the response")
    normalized_query: Optional[str] = Field(None, description="The normalized version of the user's query")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field("ok", description="Status of the processing")
    cache_hit: Optional[bool] = Field(None, description="Whether the response came from cache")
    conversation_id: Optional[str] = Field(None, description="ID of the conversation for multi-turn chat")
    enriched_query: Optional[str] = Field(None, description="The context-enriched version of the query (shown when enrichment changed the query)")
    cached: Optional[bool] = Field(None, description="Whether this response will be stored in cache")
    complexity: Optional[str] = Field(None, description="Query complexity: easy or hard")
    complexity_score: Optional[float] = Field(None, description="Complexity score 0-1")
    task_type: Optional[str] = Field(None, description="Detected task type")
    cache_entry_id: Optional[str] = Field(None, description="ID of the cache entry for feedback submission")
    model_used: Optional[str] = Field(None, description="Model that generated the response (local or external)")
    latency_ms: Optional[float] = Field(None, description="Time in milliseconds to generate the LLM response")


class ExternalLLMRequest(BaseModel):
    query: str = Field(..., description="The user's query to send to the external LLM")
    history: list[dict] = Field(default_factory=list, description="Multi-turn conversation messages")
    system_prompt: str = Field(
        "You are a helpful assistant. Answer the user's query concisely and accurately.",
        description="System prompt guiding the external model's behavior",
    )
    model: str = Field("gpt-4o", description="External model name to use")
    max_tokens: int = Field(1024, description="Maximum tokens to generate")
    temperature: float = Field(0.7, description="Sampling temperature")


class ExternalLLMResponse(BaseModel):
    text: str = Field(..., description="The generated response text")
    model_used: str = Field(..., description="Actual model that produced the response")
    prompt_tokens: int = Field(0, description="Number of input tokens consumed")
    completion_tokens: int = Field(0, description="Number of output tokens generated")
    latency_ms: float = Field(0.0, description="Total request time in milliseconds")