"""Baseline: byte-for-byte copy of the current production normalizer prompt.

Source: server/app/services/normalizer.py (lines 21-44)
Source: server/app/services/model_loader.py (load_qwen)
"""

CONFIG = {
    "name": "baseline_qwen_0_5b",
    "description": "Current production normalizer: Qwen 2.5 0.5B + technical few-shots",
    "enabled": False,
    "loader": {
        "repo_id": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "filename": "*q4_k_m.gguf",
        "n_ctx": 4096,
    },
    "inference": {
        "max_tokens": 64,
        "temperature": 0.0,
    },
    "system_prompt": (
        "You are a query normalizer. Given a user message, output ONLY a compact "
        "canonical search query. Rules: (1) Capture the core problem type and "
        "domain, not specific numbers or exact phrasing. (2) Use consistent "
        "standard vocabulary — prefer 'debug' over 'troubleshoot'/'diagnose', "
        "'slow query' over 'query performance drop', 'database' over "
        "'postgres/mysql/db'. (3) Different phrasings of the same problem must "
        "produce the same output. (4) Remove filler words and tone. Never "
        "answer. Never explain. Just output the query."
    ),
    "few_shots": [
        (
            "hey can you explain quantum mechanics like I'm 5",
            "explain quantum mechanics simply",
        ),
        (
            "yo what's the capital of france lol",
            "capital of france",
        ),
        (
            "I was wondering if you could tell me how photosynthesis works in detail please",
            "how does photosynthesis work",
        ),
        (
            "You have a Postgres table with 500M rows. A query that used to take 200ms now takes 45 seconds after a recent data migration. The table has indexes. How do you fix it?",
            "debug slow query after data migration large indexed database table",
        ),
        (
            "Our database query performance dropped dramatically after we moved data — it went from near-instant to almost a minute on a large table that has proper indexing. How do I troubleshoot this?",
            "debug slow query after data migration large indexed database table",
        ),
        (
            "Walk me through how you'd debug a memory leak in a Python service that only manifests after 48 hours of production traffic, given you can't reproduce it locally.",
            "debug memory leak python service delayed onset not reproducible locally",
        ),
        (
            "Design a distributed rate limiter that works across multiple API gateway instances without a single point of failure. What consistency guarantees can you realistically achieve?",
            "distributed rate limiter multiple api gateway instances no single point of failure consistency guarantees",
        ),
        (
            "You're running a real-time ML inference service at 50k RPS. Your P99 latency suddenly spikes from 12ms to 800ms every 4 hours like clockwork. Walk me through your entire investigation process.",
            "debug periodic latency spikes real-time ml inference service high rps investigation",
        ),
    ],
}
