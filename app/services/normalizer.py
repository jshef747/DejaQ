import logging
import time

from app.services.model_loader import ModelManager

logger = logging.getLogger("dejaq.services.normalizer")



class NormalizerService:

    def __init__(self):
        self.llm = ModelManager.load_qwen()


    def normalize(self, raw_query) -> str:
        logger.debug(f"Normalizing query: {raw_query}")

        start = time.time()

        output = self.llm.create_chat_completion(
            messages=[
                {"role": "system", "content": "You are a query normalizer. Given a user message, output ONLY a compact canonical search query. Rules: (1) Capture the core problem type and domain, not specific numbers or exact phrasing. (2) Use consistent standard vocabulary — prefer 'debug' over 'troubleshoot'/'diagnose', 'slow query' over 'query performance drop', 'database' over 'postgres/mysql/db'. (3) Different phrasings of the same problem must produce the same output. (4) Remove filler words and tone. Never answer. Never explain. Just output the query."},
                {"role": "user", "content": "INPUT: hey can you explain quantum mechanics like I'm 5\nQUERY:"},
                {"role": "assistant", "content": "explain quantum mechanics simply"},
                {"role": "user", "content": "INPUT: yo what's the capital of france lol\nQUERY:"},
                {"role": "assistant", "content": "capital of france"},
                {"role": "user", "content": "INPUT: I was wondering if you could tell me how photosynthesis works in detail please\nQUERY:"},
                {"role": "assistant", "content": "how does photosynthesis work"},
                {"role": "user", "content": "INPUT: You have a Postgres table with 500M rows. A query that used to take 200ms now takes 45 seconds after a recent data migration. The table has indexes. How do you fix it?\nQUERY:"},
                {"role": "assistant", "content": "debug slow query after data migration large indexed database table"},
                {"role": "user", "content": "INPUT: Our database query performance dropped dramatically after we moved data — it went from near-instant to almost a minute on a large table that has proper indexing. How do I troubleshoot this?\nQUERY:"},
                {"role": "assistant", "content": "debug slow query after data migration large indexed database table"},
                {"role": "user", "content": "INPUT: Walk me through how you'd debug a memory leak in a Python service that only manifests after 48 hours of production traffic, given you can't reproduce it locally.\nQUERY:"},
                {"role": "assistant", "content": "debug memory leak python service delayed onset not reproducible locally"},
                {"role": "user", "content": "INPUT: Design a distributed rate limiter that works across multiple API gateway instances without a single point of failure. What consistency guarantees can you realistically achieve?\nQUERY:"},
                {"role": "assistant", "content": "distributed rate limiter multiple api gateway instances no single point of failure consistency guarantees"},
                {"role": "user", "content": "INPUT: You're running a real-time ML inference service at 50k RPS. Your P99 latency suddenly spikes from 12ms to 800ms every 4 hours like clockwork. Walk me through your entire investigation process.\nQUERY:"},
                {"role": "assistant", "content": "debug periodic latency spikes real-time ml inference service high rps investigation"},
                {"role": "user", "content": f"INPUT: {raw_query}\nQUERY:"},
            ],
            max_tokens=64,
            temperature=0.0
        )

        cleaned_query = output["choices"][0]["message"]["content"].strip()
        latency = (time.time() - start) * 1000
        logger.info(f"Normalization completed in {latency:.2f} ms. Raw: '{raw_query}' -> Normalized: '{cleaned_query}'")
        return cleaned_query
