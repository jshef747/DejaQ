# DejaQ - Current Status

## Completed
- Basic FastAPI WebSocket server set up.
- Pydantic Schemas defined (`ChatRequest` with `department_id`).
- **Normalizer Service:** Implemented using Qwen 2.5 (0.5B) for query canonicalization.
- **Router Service:** Implemented using Llama 3.2 (1B) for local inference.
- **Client:** Simple HTML/JS `index.html` for testing.
- **Hardware:** `llama-cpp-python` configured for Mac (Metal) and Windows (CUDA/CPU).

## In Progress
1. **Difficulty Classifier:** Integrate `nvidia/prompt-task-and-complexity-classifier` to route queries as "Easy" vs "Hard". Use multi-dimensional output (reasoning, creativity scores) for precise routing.
2. **Database Integration:** `users` and `departments` tables sketched but not fully integrated. PostgreSQL with JWT-based authentication needed.
3. **Semantic Cache:** ChromaDB + BERT (Base-Uncased) for 768-dim embedding similarity matching. Only verified (positively rated) answers get indexed.

## Planned
4. **Celery & RabbitMQ:** Decouple model inference into background Celery workers with RabbitMQ as message broker for async task distribution.
5. **External API Integration:** Connect to Gemini (Google AI Studio free tier) or GPT for "Hard" queries. Ollama as a self-hosted alternative for testing.
6. **Feedback Loop:** User rating system (Thumbs Up/Down) that triggers Celery-backed indexing into ChromaDB organizational memory.
7. **Post-Answer Context Adjuster:** Use Qwen 2.5 (0.5B) to adjust responses for user context after generation.
8. **Frontend (React.js):**
   - Chat interface with React-Markdown rendering and chat history sidebar.
   - Feedback buttons integrated with backend indexing flow.
   - Admin Dashboard with Recharts: hourly traffic trends, cache health, team performance comparison, cost-saving metrics.
   - Login page with Username/Password/Department ID and JWT auth.
9. **WebSocket Status Streaming:** Stream pipeline status updates to the client in real-time (e.g., "Normalizing," "Searching Memory," "Classifying," "Generating").