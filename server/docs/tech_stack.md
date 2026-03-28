# DejaQ - Tech Stack & Architecture

## System Architecture: Event-Driven Middleware
The system is engineered as a high-performance, asynchronous middleware that orchestrates real-time traffic between users, local inference workers, and external APIs. The API gateway is decoupled from computational models to maintain low latency and reliability.

## Backend Components

### 1. Orchestrator & Gateway: FastAPI (WebSockets & PostgreSQL)
- **Real-Time Delivery:** Manages persistent WebSocket connections to stream model outputs and status updates (e.g., "Classifying," "Searching Memory") back to the user.
- **Database Integration:** Connects to PostgreSQL for JWT-based authentication, session validation, and feedback logging.
- **Non-Blocking Routing:** Offloads intensive model tasks to the queue while simultaneously updating the relational database with transaction logs.

### 2. Distributed Task Engine: Celery & RabbitMQ
- **Role:** Background execution layer for the Difficulty Classifier, Local LLM, and External LLM workers.
- **Reliability (RabbitMQ):** Message broker ensuring no query, feedback signal, or log data is lost, even during high traffic or server restarts.
- **Performance:** Offloads high-latency operations (BERT embedding generation, LLM inference) to dedicated workers, keeping WebSocket connections stable and responsive.

### 3. Feedback-Driven Semantic Cache: ChromaDB
- **Role:** Organizational Memory and semantic cache.
- **Implementation:** A dedicated Celery worker uses BERT (Base-Uncased) to generate 768-dimensional embeddings for high-accuracy similarity matching.
- **Integrity Gatekeeper:** Only indexes new data into ChromaDB after a positive user rating is recorded in PostgreSQL. This prevents cache pollution with unverified or low-quality outputs.

### 4. PostgreSQL
- **Role:** Authoritative database for all structured and persistent data.
- **Functionality:** Manages Chat History, Department-specific Analytics, and User Feedback metrics that trigger the learning loop.
- **Session Security:** Works with FastAPI for secure user sessions and dashboard analytics.

## Models Used

| Model | Role | Justification |
|-------|------|---------------|
| **BERT (Base-Uncased)** | Embedding model for Semantic Cache | Superior context and nuance understanding in short queries vs keyword search. 768-dim embeddings. |
| **Qwen 2.5-0.5B-Instruct (GGUF)** | Prompt Normalizer & Post-Answer Context Adjuster | Ultra-small (0.5B params), runs extremely fast locally in GGUF format. Canonicalizes queries to a standardized format before embedding, increasing cache hit ratio. Also adjusts context after LLM response. |
| **nvidia/prompt-task-and-complexity-classifier** | Difficulty Classifier | Lightweight, fine-tuned classifier that runs in milliseconds. Multi-dimensional output (reasoning, creativity scores) enables precise routing decisions. Can also classify task type to tune system prompts. |
| **Meta Llama 3 (GGUF)** | Local "Light" LLM | Best balance of speed and intelligence for "Easy" tasks (summarization, basic Q&A). Runs locally at zero API cost. |
| **GPT / Gemini (External API)** | Advanced "Heavy" LLM | Designated for "Hard" prompts requiring complex reasoning or multi-step logic. Only invoked when classifier detects high complexity. |

### External API Simulation Options (Development)
| Option | Platform | Benefit |
|--------|----------|---------|
| Realistic external simulation | Google AI Studio / Gemini (Free Tier) | Tests real Google API connectivity at zero cost |
| Self-hosted compatible API | Ollama | Run local models exposed as OpenAI-compatible API for routing/error handling tests |
| Diverse model testing | Hugging Face Inference API / Perplexity API | Access to various open-source models (Mistral, etc.) for async testing |

## Frontend Technology

### Core Framework: React.js
Single Page Application for seamless, responsive experience.

### Key UI Components
- **Chat Interface:** Supports React-Markdown for rendering AI-generated code and tables.
- **Feedback System:** Interactive "Thumbs Up/Down" buttons that trigger the Celery-backed indexing flow into ChromaDB.
- **Admin Dashboard:** Uses Recharts to visualize cost-saving data, cache hit ratios, and department analytics.

### Main Screens
- **Login Page:** Username, Password, Department ID fields with JWT authentication.
- **Chat Interface:** Sidebar with chat history, main chat area with feedback buttons, real-time status indicators.
- **Admin Dashboard:** Hourly traffic trends (DB Hits / Local Hits / External API), total queries, cache health (ChromaDB), team performance comparison by department.

## Coding Standards
1. **Logging:** NEVER use `print()`. Always use `app.utils.logger`.
2. **Typing:** Strong typing required. Use `Pydantic` for all data structures.
3. **Async:** All I/O operations (DB, Network) must be `async/await`.
4. **Structure:**
   - `app/routers` - API Endpoints
   - `app/services` - Business Logic (AI, Normalization, Classification)
   - `app/schemas` - Pydantic Models
   - `app/models` - Database Tables

## Known Constraints
- **Model Loading:** Models are heavy. Use the `ModelManager` singleton (`app.services.model_loader`) to avoid loading them twice.
- **Cross-Platform:** Strictly use `llama-cpp-python` for GGUF models. No `mlx-lm`. Must support Apple Silicon (Metal) and Windows (CUDA/CPU).
- **Package Manager:** `uv` only. Do not use `pip` directly.