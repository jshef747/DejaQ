"""Standalone end-to-end cache-hit pipeline latency benchmark.

Full cache-hit path:
  normalize → embed → ChromaDB lookup → validate (NEW) → context-adjust

Measures how much each step costs and what the validator ADDS.
Does NOT touch server code. Loads models directly via llama-cpp-python.
ChromaDB: connects to local instance if running; falls back to mock hit.

Usage:
    uv run python scripts/pipeline_latency.py
    uv run python scripts/pipeline_latency.py --runs 5 --chroma-host 127.0.0.1 --chroma-port 8001
"""

from __future__ import annotations

import argparse
import statistics
import time
from dataclasses import dataclass, field
from typing import Optional

# ── Test cases: (label, new_query, mock_cached_query, mock_cached_answer)
# Varying answer lengths to show validator cost vs token count.
TEST_CASES = [
    (
        "short / valid",
        "What is the capital of France?",
        "What is France's capital city?",
        "The capital of France is Paris. It is the most populous city in France.",
    ),
    (
        "short / invalid",
        "How many people live in the capital of France?",
        "What is the capital of France?",
        "The capital of France is Paris. It is the most populous city in France.",
    ),
    (
        "medium / valid",
        "How does photosynthesis work?",
        "What is photosynthesis?",
        (
            "Photosynthesis is the biological process by which plants, algae, and some "
            "bacteria convert light energy into chemical energy stored as glucose. "
            "The process occurs primarily in the chloroplasts of plant cells, using "
            "sunlight, water absorbed through roots, and carbon dioxide from the air. "
            "The light-dependent reactions capture solar energy and produce ATP and NADPH. "
            "The Calvin cycle uses these to fix CO2 into glucose. "
            "Oxygen is released as a byproduct."
        ),
    ),
    (
        "medium / invalid",
        "Where does photosynthesis take place in the cell?",
        "What is photosynthesis?",
        (
            "Photosynthesis is the biological process by which plants convert light energy "
            "into chemical energy stored as glucose, using sunlight, water, and carbon dioxide."
        ),
    ),
    (
        "long / valid",
        "yo explain TCP vs UDP like im 5",
        "Explain TCP vs UDP networking protocols",
        (
            "TCP (Transmission Control Protocol) and UDP (User Datagram Protocol) are the "
            "two primary transport-layer protocols in the TCP/IP networking model.\n\n"
            "TCP is a connection-oriented protocol that establishes a reliable, ordered, "
            "and error-checked delivery of data between applications. Before data is "
            "transmitted, TCP performs a three-way handshake to establish a connection. "
            "It guarantees that all packets arrive, in order, and that corrupted packets "
            "are retransmitted. This reliability comes at the cost of higher latency. "
            "TCP is used for web browsing (HTTP/S), email, and file transfer.\n\n"
            "UDP is a connectionless protocol that sends datagrams without establishing a "
            "connection or guaranteeing delivery. There is no handshake, no acknowledgement, "
            "and no retransmission of lost packets. This makes UDP much faster but unreliable. "
            "Applications that use UDP include video streaming, online gaming, VoIP, and DNS.\n\n"
            "Summary: TCP = reliable, ordered, slower. UDP = fast, best-effort, no guarantees."
        ),
    ),
    (
        "long / invalid",
        "What port does TCP use by default?",
        "Explain TCP vs UDP networking protocols",
        (
            "TCP (Transmission Control Protocol) and UDP (User Datagram Protocol) are the "
            "two primary transport-layer protocols. TCP is connection-oriented and reliable; "
            "UDP is connectionless and fast. TCP uses a three-way handshake before "
            "transmission. UDP sends datagrams without establishing a connection. "
            "TCP guarantees delivery and ordering; UDP does not. "
            "TCP is used for HTTP, email, FTP. UDP is used for streaming, gaming, VoIP."
        ),
    ),
    (
        "very-long / valid",
        "Can you summarize the tradeoffs of database connection pooling?",
        "What is database connection pooling and how does it work?",
        (
            "Database connection pooling is a technique used to improve the performance of "
            "applications that frequently interact with a database by reusing existing "
            "connections rather than creating new ones for each request.\n\n"
            "When an application needs to execute a database query, establishing a new "
            "connection is expensive: it involves a TCP handshake, authentication, "
            "session initialization on the database server, and memory allocation. "
            "For high-traffic applications handling thousands of concurrent requests, "
            "this overhead becomes a bottleneck. Connection pooling solves this by "
            "maintaining a pool of already-established connections that can be quickly "
            "handed to a requesting thread, used for a query, and returned to the pool.\n\n"
            "A pool has a minimum size (connections kept open even when idle) and a maximum "
            "size (the cap on concurrent connections). When the pool is exhausted, threads "
            "either wait or get an exception. Idle connections are periodically validated.\n\n"
            "Popular pool libraries: HikariCP (Java), pgBouncer (PostgreSQL), SQLAlchemy "
            "(Python). Each has config for pool size, timeout, max lifetime, and keepalive.\n\n"
            "Tradeoffs: pooling reduces overhead under load, but requires tuning — "
            "too-small pools cause contention; too-large pools exhaust database resources. "
            "Stale connections must be handled via keepalive or validation queries.\n\n"
            "In serverless environments (Lambda, Cloudflare Workers), traditional pools "
            "don't fit because each invocation may run in a separate process. "
            "Infrastructure-level poolers like AWS RDS Proxy address this."
        ),
    ),
    (
        "very-long / invalid",
        "What is the minimum pool size recommended for PostgreSQL production?",
        "What is database connection pooling and how does it work?",
        (
            "Database connection pooling reuses existing database connections rather than "
            "creating new ones per request. A pool maintains a set of open connections "
            "handed to threads on demand and returned after use. This reduces per-request "
            "overhead of TCP handshake, auth, and session setup. Popular tools include "
            "HikariCP, pgBouncer, and SQLAlchemy pool. Tradeoffs: reduces overhead under "
            "load, but requires careful size tuning and stale connection handling."
        ),
    ),

    # ── STRESS: long query + very long answer (worst-case context window)
    (
        "stress-1 / valid",
        # Long query: enriched standalone form of a multi-turn conversation
        (
            "In the context of building a distributed microservices system where multiple "
            "services communicate via REST APIs over HTTP, and considering that we are "
            "using PostgreSQL as our primary database with connection pooling via pgBouncer, "
            "and our services are deployed on Kubernetes with horizontal pod autoscaling, "
            "what are the key tradeoffs between synchronous REST communication and "
            "asynchronous message-queue-based communication (such as Kafka or RabbitMQ) "
            "for inter-service data consistency, latency, and fault tolerance?"
        ),
        "REST vs message queue communication in microservices",
        # Very long answer (~500 tokens)
        (
            "The choice between synchronous REST and asynchronous message-queue communication "
            "in a microservices architecture involves fundamental tradeoffs across latency, "
            "consistency, complexity, and fault tolerance.\n\n"
            "Synchronous REST (HTTP/gRPC) is the simpler mental model: a service sends a "
            "request and waits for a response. This makes request-response flows easy to "
            "reason about, errors are immediately visible to the caller, and you get "
            "strong consistency within a single request boundary. However, it creates "
            "temporal coupling — the calling service must wait for the downstream service "
            "to be available and responsive. Under high load, slow downstream services "
            "cause upstream services to block threads, leading to latency amplification "
            "and potential cascading failures. Circuit breakers, timeouts, and retries "
            "partially mitigate this, but they add operational complexity.\n\n"
            "Asynchronous message queues (Kafka, RabbitMQ, SQS) decouple producers from "
            "consumers in time. A service publishes an event and continues immediately; "
            "downstream services consume at their own pace. This provides natural "
            "backpressure handling, better fault isolation (a slow consumer doesn't block "
            "the producer), and enables event-driven architectures with replay and audit "
            "log capabilities. Kafka's durable log is particularly powerful for event "
            "sourcing and rebuilding state. The tradeoff is eventual consistency — "
            "distributed transactions across services become choreography-based sagas "
            "rather than ACID commits, which are harder to implement correctly and debug.\n\n"
            "For your specific setup (PostgreSQL + pgBouncer + Kubernetes HPA): "
            "synchronous REST works well for user-facing request paths where you need "
            "immediate responses and can tolerate tight coupling. For background processing, "
            "data pipelines, and cross-service notifications where eventual consistency "
            "is acceptable, a message queue reduces coupling and scales better with HPA "
            "since consumers can scale independently from producers.\n\n"
            "A hybrid approach is common: REST for queries and user-facing writes, "
            "message queues for events that propagate state changes across service boundaries. "
            "The Outbox pattern bridges them — write to PostgreSQL and an outbox table "
            "atomically, then a relay process publishes to the queue, ensuring at-least-once "
            "delivery without distributed transactions."
        ),
    ),
    (
        "stress-2 / invalid",
        # Long query: detailed multi-part question
        (
            "Given a Python FastAPI application that uses SQLAlchemy with async sessions, "
            "Alembic for migrations, and Redis for caching, where we are experiencing "
            "N+1 query problems and high memory usage during peak load on our EC2 instances, "
            "and we've already added database indexes on the most queried columns, "
            "what specific SQLAlchemy query optimization techniques, connection pool "
            "configuration parameters, and async session management patterns should we "
            "implement to reduce both query count and memory footprint under 1000 "
            "concurrent requests?"
        ),
        "SQLAlchemy performance optimization basics",
        # Long answer (~400 tokens) — doesn't answer the specific question fully
        (
            "SQLAlchemy is a powerful Python ORM and SQL toolkit that provides both "
            "a high-level ORM interface and a lower-level Core expression language.\n\n"
            "For query optimization, the most common techniques include:\n\n"
            "1. Eager loading with joinedload() or selectinload() to avoid N+1 queries. "
            "Instead of accessing related objects lazily (triggering a query per row), "
            "you tell SQLAlchemy to load them in the initial query or in a second batched query. "
            "selectinload() is generally preferred for one-to-many relationships as it "
            "uses a SELECT IN query rather than a JOIN, which avoids row multiplication.\n\n"
            "2. Using query.options() to control loading strategies per query rather "
            "than setting them globally on the relationship definition. This lets you "
            "optimize loading for each specific use case.\n\n"
            "3. The with_loader_criteria() function allows global filtering of lazy loads.\n\n"
            "4. For bulk operations, using insert(), update(), and delete() at the Core "
            "level rather than the ORM level avoids the overhead of loading objects into memory.\n\n"
            "5. Connection pooling in SQLAlchemy is handled by the engine's pool. "
            "Key parameters include pool_size (default 5), max_overflow (default 10), "
            "pool_timeout (default 30s), and pool_recycle (important for MySQL). "
            "For async applications, AsyncEngine uses a NullPool or AsyncAdaptedQueuePool.\n\n"
            "6. Async sessions (AsyncSession) must be used carefully — avoid mixing "
            "sync and async patterns, use async_scoped_session for per-request scoping, "
            "and always close sessions explicitly or use them as context managers.\n\n"
            "However, specific configuration values for 1000 concurrent requests depend "
            "on your EC2 instance size, database server capacity, and workload characteristics."
        ),
    ),
    (
        "stress-3 / valid",
        # Very long query: full system context + specific question (~300 tokens)
        (
            "Our team is building a real-time collaborative document editing platform "
            "similar to Google Docs. The backend is Node.js with WebSocket connections "
            "managed by Socket.io. We store document state in Redis for real-time sync "
            "and persist to PostgreSQL asynchronously. We use operational transforms (OT) "
            "to merge concurrent edits. The frontend is React with a custom rich-text "
            "editor built on ProseMirror. We currently have about 500 concurrent users "
            "per document room at peak. We're experiencing occasional merge conflicts "
            "that corrupt document state when network latency spikes above 200ms, and "
            "our OT algorithm doesn't correctly handle the case where three or more "
            "clients submit conflicting operations within the same 50ms window. "
            "We've been reading about CRDTs (Conflict-free Replicated Data Types) as "
            "an alternative to OT. In this context, what are the specific algorithmic "
            "advantages and disadvantages of CRDTs versus operational transforms for "
            "collaborative text editing, and which approach scales better to 500+ "
            "concurrent editors with high network jitter?"
        ),
        "CRDTs vs operational transforms for collaborative editing",
        # Very long answer (~600 tokens)
        (
            "CRDTs (Conflict-free Replicated Data Types) and Operational Transforms (OT) "
            "are the two dominant approaches for achieving consistency in collaborative "
            "real-time editing systems, and they differ fundamentally in their consistency "
            "model and scalability properties.\n\n"
            "Operational Transforms work by transforming an operation against all concurrent "
            "operations that have been applied since the operation was generated. The "
            "transform function takes two concurrent operations and produces a new version "
            "of each that accounts for the other. The classic OT algorithm (Jupiter, "
            "dOPT) requires a central server to serialize operations and applies "
            "transformations in a total order. This server-centric model is why Google "
            "Docs, Etherpad, and Quill use OT — the server enforces a canonical ordering. "
            "The challenge with OT is that the transform function is difficult to "
            "implement correctly, especially for rich-text operations involving embedded "
            "objects, formatting spans, and annotations. Three-way concurrent conflicts "
            "are particularly hard — the transformation must be confluent (applying "
            "transforms in any order produces the same result), a property that many "
            "OT implementations violate under edge cases, which is exactly your bug.\n\n"
            "CRDTs take a different approach: they define data structures whose merge "
            "operation is commutative, associative, and idempotent by construction. "
            "This means any two replicas can be merged in any order and always converge "
            "to the same state — no transform function required. For text editing, "
            "sequence CRDTs like LSEQ, Logoot, RGA (Replicated Growable Array), and "
            "the modern Yjs/Automerge libraries assign unique, stable identifiers to "
            "each character position. Concurrent insertions at the same logical position "
            "are deterministically ordered by the identifier, so conflicts resolve "
            "automatically without a server arbitrating order.\n\n"
            "For your specific situation (500 concurrent editors, 200ms+ jitter, "
            "3-way OT bugs): CRDTs are the stronger choice. Yjs in particular has "
            "been battle-tested in production at scale, integrates with ProseMirror "
            "via y-prosemirror, works with WebSocket (y-websocket) or WebRTC, and "
            "handles the 3+ concurrent client case correctly by design since merge is "
            "commutative. The Yjs CRDT (Y.Text) uses a variant of RGA that is "
            "memory-efficient and supports undo/redo, rich-text attributes, and "
            "embedded objects.\n\n"
            "Tradeoffs to consider: CRDTs use more memory per document (each character "
            "has metadata), tombstones for deleted characters accumulate over time "
            "(requiring periodic garbage collection), and the initial convergence on "
            "reconnect sends the full CRDT state rather than a delta. OT with a "
            "well-implemented transform function can be more bandwidth-efficient for "
            "simple plain-text documents. But for your rich-text ProseMirror use case "
            "with jitter-induced 3-way conflicts, the CRDT approach eliminates an entire "
            "class of correctness bugs that are genuinely hard to fix in OT."
        ),
    ),
]


CHROMA_COLLECTION = "dejaq_default"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
SIMILARITY_THRESHOLD = 0.15

# Validator prompt (Gemma E2B)
VALIDATOR_SYSTEM = (
    "You decide if a CACHED ANSWER can correctly answer a NEW QUESTION.\n"
    "Reply with exactly one word: VALID or INVALID.\n"
    "VALID = the cached answer already contains EVERY specific fact the new question asks for.\n"
    "INVALID = the cached answer is missing any requested fact, is about a different entity, or is off-topic.\n"
    "Two rules:\n"
    "- MULTIPLE FACTS: If the new question asks for two or more facts (e.g. 'A and B'), "
    "the answer must contain ALL of them. A partial answer is INVALID.\n"
    "- TONE: Ignore tone, formality, and language style. Casual or slang phrasing that "
    "asks for the same information is VALID if the answer contains it.\n"
    "When in doubt, choose INVALID."
)
VALIDATOR_FEW_SHOTS = [
    (
        "CACHED QUESTION: What is the capital of France?\n"
        "CACHED ANSWER: The capital of France is Paris.\n"
        "NEW QUESTION: What is France's capital city?",
        "VALID",
    ),
    (
        "CACHED QUESTION: What is gravity?\n"
        "CACHED ANSWER: Gravity is a fundamental force that attracts objects with mass toward each other.\n"
        "NEW QUESTION: bro what even is gravity and why do things fall",
        "VALID",
    ),
    (
        "CACHED QUESTION: What is the capital of New Zealand?\n"
        "CACHED ANSWER: Wellington is the capital city of New Zealand.\n"
        "NEW QUESTION: How many people live in the capital of New Zealand?",
        "INVALID",
    ),
    (
        "CACHED QUESTION: What is the capital of New Zealand?\n"
        "CACHED ANSWER: Wellington is the capital of New Zealand.\n"
        "NEW QUESTION: What is the capital and largest city of New Zealand?",
        "INVALID",
    ),
]

# Context adjuster prompt (Qwen 1.5B) — mirrored from server/app/services/context_adjuster.py
ADJUSTER_SYSTEM = (
    "Rewrite the ANSWER to match the tone of the QUESTION. "
    "Keep all facts. Output only the rewritten answer."
)
ADJUSTER_FEW_SHOTS = [
    (
        "QUESTION: explain gravity like I'm 5\n"
        "ANSWER: Gravity is a fundamental force of attraction between objects with mass.",
        "Imagine you have a ball. When you throw it up, it comes back down! "
        "That's because the Earth is really big and pulls everything toward it. "
        "That pulling is called gravity!",
    ),
    (
        "QUESTION: yo whats the capital of france\n"
        "ANSWER: The capital of France is Paris.",
        "It's Paris!",
    ),
    (
        "QUESTION: provide a detailed analysis of photosynthesis\n"
        "ANSWER: Photosynthesis is how plants make food from sunlight.",
        "Photosynthesis is the biochemical process by which plants, algae, and certain "
        "bacteria convert light energy into chemical energy. During this process, carbon "
        "dioxide and water are transformed into glucose and oxygen through light-dependent "
        "and light-independent reactions within the chloroplasts.",
    ),
]


@dataclass
class StepTiming:
    normalize_ms: float = 0.0
    embed_ms: float = 0.0
    chroma_ms: float = 0.0
    validate_ms: float = 0.0
    adjust_ms: float = 0.0
    chroma_hit: bool = False
    verdict: str = ""

    @property
    def total_ms(self) -> float:
        return self.normalize_ms + self.embed_ms + self.chroma_ms + self.validate_ms + self.adjust_ms

    @property
    def baseline_ms(self) -> float:
        """Pipeline without validator: norm + embed + chroma + adjust."""
        return self.normalize_ms + self.embed_ms + self.chroma_ms + self.adjust_ms

    @property
    def validator_delta_ms(self) -> float:
        return self.validate_ms


@dataclass
class CaseResult:
    label: str
    cached_answer_tokens: int
    ctx_pct: float = 0.0
    runs: list[StepTiming] = field(default_factory=list)

    def p(self, attr: str, pct: float) -> float:
        vals = sorted(getattr(r, attr) for r in self.runs)
        idx = max(0, int(len(vals) * pct / 100) - 1)
        return vals[idx]

    def mean(self, attr: str) -> float:
        return statistics.mean(getattr(r, attr) for r in self.runs)


def _normalize(query: str) -> str:
    import re
    OPINION = re.compile(
        r"\b(best|greatest|ultimate|finest|top.rated|highly.recommend|most.recommend"
        r"|favorite|favourite|worst|most.popular|number.one|#1)\b",
        re.IGNORECASE,
    )
    if OPINION.search(query):
        return query.lower().strip()  # opinion: would normally call LLM; use passthrough here
    return query.lower().strip()


def _load_embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBED_MODEL)


def _embed(embedder, text: str) -> list[float]:
    return embedder.encode([text], normalize_embeddings=True)[0].tolist()


def _try_chroma(host: str, port: int, embedding: list[float], mock: tuple) -> tuple:
    try:
        import chromadb
        client = chromadb.HttpClient(host=host, port=port)
        col = client.get_collection(CHROMA_COLLECTION)
        count = col.count()
        if count == 0:
            return (*mock, False)
        results = col.query(
            query_embeddings=[embedding],
            n_results=min(5, count),
            include=["documents", "metadatas", "distances"],
        )
        for i, d in enumerate(results["distances"][0]):
            if d <= SIMILARITY_THRESHOLD:
                meta = results["metadatas"][0][i]
                return (
                    results["documents"][0][i],
                    meta.get("generalized_answer", ""),
                    True,
                )
        return (*mock, False)
    except Exception:
        return (*mock, False)


def _chat(llm, system: str, few_shots: list, user_content: str, max_tokens: int, temperature: float) -> str:
    messages = [{"role": "system", "content": system}]
    for u, a in few_shots:
        messages.append({"role": "user", "content": u})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": user_content})
    out = llm.create_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=1.0,
        stop=["\n"] if max_tokens <= 8 else [],
    )
    return out["choices"][0]["message"]["content"].strip()


def _count_tokens(llm, text: str) -> int:
    try:
        return len(llm.tokenize(text.encode()))
    except Exception:
        return len(text.split())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--chroma-host", default="127.0.0.1")
    p.add_argument("--chroma-port", type=int, default=8001)
    return p.parse_args()


def main():
    args = parse_args()

    print("=" * 72)
    print("DejaQ cache-hit pipeline latency benchmark")
    print("Full path: normalize → embed → chroma → VALIDATE → adjust")
    print(f"Runs per case: {args.runs}")
    print("=" * 72)

    # Load shared infrastructure
    print("\nLoading embedder (BAAI/bge-small-en-v1.5)...")
    embedder = _load_embedder()
    print("  Done.")

    print("Loading Gemma E2B validator...")
    from llama_cpp import Llama
    validator = Llama.from_pretrained(
        repo_id="unsloth/gemma-4-E2B-it-GGUF",
        filename="*Q4_K_M.gguf",
        n_ctx=2048,
        verbose=False,
    )
    print("  Done.")

    print("Loading Qwen 1.5B context adjuster...")
    adjuster = Llama.from_pretrained(
        repo_id="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        filename="*q4_k_m.gguf",
        n_ctx=4096,
        verbose=False,
    )
    print("  Done.\n")

    results: list[CaseResult] = []

    for label, new_query, mock_cq, mock_ca in TEST_CASES:
        print(f"{'─'*60}")
        print(f"Case: {label!r}")
        print(f"  Q: {new_query[:72]}")
        print(f"  A: {mock_ca[:60]}{'...' if len(mock_ca) > 60 else ''}")
        ca_tokens = _count_tokens(validator, mock_ca)
        nq_tokens = _count_tokens(validator, new_query)
        # Estimate total context: system(~120) + 4 few-shots(~240) + content
        content_tokens = _count_tokens(validator, mock_cq) + ca_tokens + nq_tokens
        total_ctx_estimate = 360 + content_tokens
        ctx_pct = total_ctx_estimate / 2048 * 100
        print(f"  Answer: ~{ca_tokens} tok  Query: ~{nq_tokens} tok  Context: ~{total_ctx_estimate}/2048 ({ctx_pct:.0f}%)")

        case = CaseResult(label=label, cached_answer_tokens=ca_tokens, ctx_pct=ctx_pct)

        for run_i in range(args.runs):
            t = StepTiming()

            # 1. Normalize
            t0 = time.perf_counter()
            normalized = _normalize(new_query)
            t.normalize_ms = (time.perf_counter() - t0) * 1000

            # 2. Embed
            t0 = time.perf_counter()
            emb = _embed(embedder, normalized)
            t.embed_ms = (time.perf_counter() - t0) * 1000

            # 3. ChromaDB
            t0 = time.perf_counter()
            cq, ca, hit = _try_chroma(
                args.chroma_host, args.chroma_port,
                emb, (mock_cq, mock_ca),
            )
            t.chroma_ms = (time.perf_counter() - t0) * 1000
            t.chroma_hit = hit

            # 4. Validate (NEW)
            t0 = time.perf_counter()
            verdict = _chat(
                validator, VALIDATOR_SYSTEM, VALIDATOR_FEW_SHOTS,
                f"CACHED QUESTION: {cq}\nCACHED ANSWER: {ca}\nNEW QUESTION: {new_query}",
                max_tokens=8, temperature=0.0,
            )
            t.validate_ms = (time.perf_counter() - t0) * 1000
            t.verdict = verdict.upper()[:7]

            # 5. Context adjust (only if VALID — simulate skipping on INVALID)
            if t.verdict.startswith("VALID"):
                t0 = time.perf_counter()
                _chat(
                    adjuster, ADJUSTER_SYSTEM, ADJUSTER_FEW_SHOTS,
                    f"QUESTION: {new_query}\nANSWER: {ca}",
                    max_tokens=512, temperature=0.3,
                )
                t.adjust_ms = (time.perf_counter() - t0) * 1000
            else:
                t.adjust_ms = 0.0  # INVALID = cache miss, no adjustment needed

            case.runs.append(t)
            src = "chroma" if hit else "mock"
            print(
                f"  run {run_i+1}: "
                f"norm={t.normalize_ms:.1f}  "
                f"embed={t.embed_ms:.0f}  "
                f"chroma={t.chroma_ms:.0f}({src})  "
                f"validate={t.validate_ms:.0f}  "
                f"adjust={t.adjust_ms:.0f}  "
                f"total={t.total_ms:.0f}ms  [{t.verdict}]"
            )

        results.append(case)

    # ── Summary
    print(f"\n{'='*72}")
    print("SUMMARY — p50 (ms) per step")
    print(f"{'='*72}")
    print(f"  {'Case':<24} {'Ctx%':>5}  {'Norm':>5} {'Embed':>6} {'Chroma':>7} {'Valid':>7} {'Adjust':>7} {'Total':>7}  {'Δvalid':>7}")
    print("  " + "─" * 72)
    for r in results:
        p = lambda attr: r.p(attr, 50)
        delta_valid = p("validate_ms")
        print(
            f"  {r.label:<24} {r.ctx_pct:>4.0f}%  "
            f"{p('normalize_ms'):>5.1f} "
            f"{p('embed_ms'):>6.0f} "
            f"{p('chroma_ms'):>7.0f} "
            f"{p('validate_ms'):>7.0f} "
            f"{p('adjust_ms'):>7.0f} "
            f"{p('total_ms'):>7.0f}  "
            f"{delta_valid:>+7.0f}"
        )

    print(f"\n{'─'*72}")
    print("p95 (ms)")
    print(f"  {'Case':<24} {'Ctx%':>5}  {'Embed':>6} {'Chroma':>7} {'Valid':>7} {'Adjust':>7} {'Total':>7}")
    print("  " + "─" * 72)
    for r in results:
        p = lambda attr: r.p(attr, 95)
        print(
            f"  {r.label:<24} {r.ctx_pct:>4.0f}%  "
            f"{p('embed_ms'):>6.0f} "
            f"{p('chroma_ms'):>7.0f} "
            f"{p('validate_ms'):>7.0f} "
            f"{p('adjust_ms'):>7.0f} "
            f"{p('total_ms'):>7.0f}"
        )

    # Key numbers
    valid_cases   = [r for r in results if "valid" in r.label and "invalid" not in r.label]
    invalid_cases = [r for r in results if "invalid" in r.label]

    print(f"\n{'='*72}")
    print("KEY NUMBERS")
    print("─" * 72)

    if valid_cases:
        avg_validate = statistics.mean(r.p("validate_ms", 50) for r in valid_cases)
        avg_adjust   = statistics.mean(r.p("adjust_ms", 50) for r in valid_cases)
        avg_baseline = statistics.mean(r.p("baseline_ms", 50) for r in valid_cases)
        avg_total    = statistics.mean(r.p("total_ms", 50) for r in valid_cases)
        print(f"  VALID cache hits (user gets cached answer):")
        print(f"    Baseline (embed+chroma+adjust) p50 : {avg_baseline:.0f}ms")
        print(f"    + Validator overhead            p50 : +{avg_validate:.0f}ms")
        print(f"    Total with validator            p50 : {avg_total:.0f}ms")

    if invalid_cases:
        avg_validate_inv = statistics.mean(r.p("validate_ms", 50) for r in invalid_cases)
        print(f"  INVALID cache hits (validator rejects → treated as miss):")
        print(f"    Validator cost before rejection p50 : +{avg_validate_inv:.0f}ms")
        print(f"    No adjust step (saved)              : ~{avg_adjust:.0f}ms saved")

    print("=" * 72)


if __name__ == "__main__":
    main()
