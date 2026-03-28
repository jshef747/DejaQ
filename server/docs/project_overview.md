# DejaQ - Project Overview

## The Problem
Organizations face high operational costs and latency when using LLMs in business environments. The standard model involves paying a flat monthly fee ($20-30 per employee) regardless of usage volume or query complexity. Simple queries cost the same as complex ones, and there is no mechanism to leverage previously answered questions to speed up future interactions.

## Our Solution
DejaQ is a **Middleware Architecture** designed to manage interactions intelligently between users and LLMs, balancing performance with significant cost savings. The solution relies on three primary mechanisms:

### 1. Microservices & RabbitMQ
The system is decoupled into independent microservices (API Gateway, Classifier, Local Inference, External Handler) that communicate asynchronously via **RabbitMQ**. This ensures scalability, fault-tolerance, and high concurrency without blocking the user interface.

### 2. Feedback-Based Semantic Caching
An organizational memory mechanism that analyzes user context. High-quality answers (verified by user ratings) are stored in **ChromaDB**. Future queries with semantic similarity to stored data receive an immediate response from the cache, eliminating the need to query an LLM entirely.

### 3. Hybrid Model Routing
A lightweight **NVIDIA prompt-task-and-complexity-classifier** determines query difficulty in milliseconds. Simple queries are answered locally (zero API cost). Only complex queries requiring high-level reasoning are routed to expensive commercial models.

## Architecture Flow
1. **User Interface** - Employee sends a query through the custom Chat Site (React.js).
2. **Gateway (FastAPI/WebSocket)** - Validates schema (Pydantic), manages real-time connections.
3. **Normalizer (Qwen 2.5 0.5B)** - Canonicalizes the query into a standardized format to maximize cache hit ratio.
4. **Semantic Cache (ChromaDB + BERT)** - Checks if a semantically similar question already has a verified answer.
   - **Cache HIT** - Returns the cached answer immediately.
   - **Cache MISS** - Proceeds to classification.
5. **Difficulty Classifier (NVIDIA)** - Classifies the query as "Easy" or "Hard".
6. **Generation:**
   - **Easy** - Local LLM (Llama 3) handles it at zero API cost.
   - **Hard** - External API (Gemini/GPT) handles complex reasoning.
7. **Context Adjuster (Qwen 2.5 0.5B)** - Post-processes the response for the user's context.
8. **Response** - Answer + metadata streamed back to the client via WebSocket.
9. **Feedback Loop** - User rates the response (Good/Bad). Positive ratings trigger indexing into ChromaDB, building the organizational memory.

## Expected Users
Organizations and business teams (sales, marketing, engineering) that require frequent LLM access but want to reduce overhead costs. The system adapts to various organizational contexts, creating a shared "organizational memory" per department.

## Alternative Approaches Considered

### Model Distillation (Teacher-Student)
Uses a large "Teacher" model (GPT-4) to generate training data for a smaller "Student" model, eventually removing external API dependency.
- **Pros:** Lowest long-term cost, eliminates external dependency.
- **Cons:** Significant upfront training effort, less flexible for new topics.

### LLM Cascading (Sequential Logic)
Sends every query to a cheap model first, then uses a scoring function to decide if escalation to a larger model is needed.
- **Pros:** Simple to implement, no classifier training.
- **Cons:** Higher latency for complex queries (waits for cheap model to fail first).

**DejaQ's classifier-first approach** avoids both of these downsides by predicting difficulty *before* answering.