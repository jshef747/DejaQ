# Quickstart: External LLM Routing

To enable routing of "hard" queries to an external LLM (e.g., OpenAI GPT-4o), follow these setup steps.

## 1. Environment Configuration

Add the following variables to your environment (e.g., `.env` file or export them):

```bash
# Required: Your OpenAI API key
export OPENAI_API_KEY="sk-..."

# Optional: The external model to use for "hard" prompts (Default: gpt-4o)
export DEJAQ_EXTERNAL_MODEL="gpt-4o"

# Optional: Custom API base (for vLLM/Ollama/Other providers)
# export DEJAQ_EXTERNAL_API_BASE="https://api.openai.com/v1"
```

## 2. Dependency Installation

Install the new `openai` library:

```bash
uv add openai
uv sync
```

## 3. Verify Integration

Restart the server and Celery worker. Submit a complex query to the `/chat` endpoint. You can verify routing in the logs:

```text
INFO:dejaq.services.llm_router: Routing "hard" query to ExternalLLMService
INFO:dejaq.services.external_llm: External API request successful (Latency: 1250.00 ms)
```

## 4. Testing

To test the external routing logic specifically without real API calls, you can use the mock suite (planned):

```bash
uv run pytest tests/test_external_llm.py
```
