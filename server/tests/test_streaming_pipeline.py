"""The streaming contract: tokens leave as the model produces them, and the
response headers leave before the first one.

Before this, `_stream_generator` replayed an already-finished answer as SSE
frames: a client saw nothing until generation was complete, and the headers -
which the chat app reads to name the model it is waiting on - arrived with the
last of the text rather than ahead of the first of it. Both halves are asserted
here against the real router, because either one alone still looks like
streaming from the outside.
"""
import asyncio
import json

import httpx
import pytest

from app.services.model_backends import (
    CompletionChunk,
    CompletionRequest,
    ModelNotFoundError,
    OllamaBackend,
)
from tests.test_openai_compat_smoke import _AUTH, _patch_for_truncation


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )
    monkeypatch.setattr(_KEY_CACHE, "namespace", lambda *a, **kw: "test-namespace")


class PiecewiseRouter:
    """Emits a known sequence of pieces and records when it was first pulled."""

    model_name = "gemma_local"

    def __init__(self, pieces=("Paris ", "is the ", "capital.")) -> None:
        self.pieces = list(pieces)
        self.started = False

    async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
        self.started = True
        return "".join(self.pieces), 12.0, "stop"

    async def stream_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
        self.started = True
        for piece in self.pieces:
            yield CompletionChunk(text=piece)
        yield CompletionChunk(done_reason="stop")


def _content_deltas(body: str) -> list[str]:
    out = []
    for line in body.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        delta = json.loads(line[len("data: "):])["choices"][0]["delta"]
        if delta.get("content"):
            out.append(delta["content"])
    return out


def test_stream_forwards_the_models_own_pieces(monkeypatch):
    """The deltas are the model's chunks, not the finished answer re-split.

    The old code word-split a completed string, so this exact assertion is
    what tells a real stream from a replayed one.
    """
    router = PiecewiseRouter()
    client = _patch_for_truncation(monkeypatch, router)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert _content_deltas(response.text) == ["Paris ", "is the ", "capital."]


def test_headers_are_sent_before_generation_starts(monkeypatch):
    """The response head must not wait on the answer.

    Driven at the ASGI level on purpose: TestClient runs the whole app to
    completion before it hands back a response, so it cannot observe the one
    thing this asserts - that `http.response.start` is emitted while the
    router has not been called yet. A buffered implementation cannot produce
    headers this early.
    """
    router = PiecewiseRouter()
    _patch_for_truncation(monkeypatch, router)

    from app.main import app

    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "What is the capital of France?"}],
        "stream": True,
    }).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"authorization", _AUTH["Authorization"].encode()),
            (b"x-dejaq-department", _AUTH["X-DejaQ-Department"].encode()),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }

    sent: list[tuple[str, bool]] = []

    pending = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        # One body message, then a disconnect: BaseHTTPMiddleware keeps polling.
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        # Record what the model had produced at the moment each ASGI message left.
        sent.append((message["type"], router.started))

    asyncio.run(app(scope, receive, send))

    assert sent, "the app sent nothing"
    kind, started_when_head_was_sent = sent[0]
    assert kind == "http.response.start"
    assert started_when_head_was_sent is False, "generation ran before the headers were sent"
    assert router.started is True, "generation never ran"


def test_non_streaming_requests_still_use_the_buffered_call(monkeypatch):
    """stream=false must not quietly change which router call it makes."""

    class BufferedOnlyRouter(PiecewiseRouter):
        async def stream_local_response(self, *args, **kwargs):
            raise AssertionError("stream=false must not take the streaming path")
            yield  # pragma: no cover - makes this an async generator

    client = _patch_for_truncation(monkeypatch, BufferedOnlyRouter())

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Paris is the capital."


def test_streamed_truncation_still_reaches_the_final_chunk(monkeypatch):
    """finish_reason only settles once the stream drains, so the terminal SSE
    frame has to read it afterwards - the guard that refuses to cache a
    cut-off answer keys off the same value."""

    class TruncatedPiecewiseRouter(PiecewiseRouter):
        async def stream_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
            self.started = True
            yield CompletionChunk(text="Paris is the capital of Fra")
            yield CompletionChunk(done_reason="length")

    client = _patch_for_truncation(monkeypatch, TruncatedPiecewiseRouter())

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "max_tokens": 8,
            "stream": True,
        },
    )

    assert response.status_code == 200
    finish_reasons = [
        json.loads(line[len("data: "):])["choices"][0]["finish_reason"]
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert finish_reasons[-1] == "length"


def _patch_for_external(monkeypatch, external, credential=None):
    """Minimum wiring for a hard-routed cache miss answered by `external`."""
    from app.routers import openai_compat
    from tests.test_openai_compat_smoke import (
        HardClassifier,
        StubEnricher,
        StubMemory,
        StubNormalizer,
        no_stored_credential,
        stored_credential,
    )
    from fastapi.testclient import TestClient
    from app.main import app

    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", HardClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", external)
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(
        openai_compat,
        "get_workspace_provider_key",
        stored_credential(credential, providers=("anthropic",)) if credential else no_stored_credential,
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="claude-sonnet-4-6",
            routing_threshold=0.75,
        ),
    )
    return TestClient(app, headers=_AUTH)


class StreamingExternalLLM:
    """Cloud client that streams, and reports usage only on its final chunk."""

    def __init__(self) -> None:
        self.streamed = False

    async def generate_response(self, request, provider=None, api_key=None):
        raise AssertionError("a streaming request must take stream_response")

    async def stream_response(self, request, provider=None, api_key=None):
        from app.schemas.chat import ExternalLLMResponse, ExternalStreamChunk

        self.streamed = True
        for piece in ("The ", "cloud ", "answer."):
            yield ExternalStreamChunk(text=piece)
        yield ExternalStreamChunk(final=ExternalLLMResponse(
            text="The cloud answer.",
            model_used="claude-sonnet-4-6",
            prompt_tokens=44,
            completion_tokens=300,
            latency_ms=10.0,
        ))


def test_external_route_streams_too(monkeypatch):
    """The cloud path is not allowed to stay buffered while the local one streams."""
    external = StreamingExternalLLM()
    client = _patch_for_external(monkeypatch, external, credential="sk-ant-live")

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Prove the Riemann hypothesis."}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert external.streamed is True
    assert _content_deltas(response.text) == ["The ", "cloud ", "answer."]
    assert response.headers["x-dejaq-tier"] == "external"
    assert response.headers["x-dejaq-model-used"] == "claude-sonnet-4-6"


def test_missing_credential_is_still_402_on_a_streaming_request(monkeypatch):
    """Credential resolution has to happen before the headers are flushed.

    Resolved after that point it could only be reported as a 200 carrying an
    apology, because the response head has already left.
    """
    client = _patch_for_external(monkeypatch, StreamingExternalLLM(), credential=None)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Prove the Riemann hypothesis."}],
            "stream": True,
        },
    )

    assert response.status_code == 402
    assert "API key" in response.json()["detail"]


# ── The NDJSON parser underneath: OllamaBackend.stream / _stream_lines ──
#
# Everything above drives the pipeline through a stub router, so none of it
# reaches the backend that actually talks to Ollama. These feed it real
# response bytes instead.


def _ndjson_backend(chunks: list[bytes]) -> tuple[OllamaBackend, httpx.AsyncClient]:
    async def body():
        for chunk in chunks:
            yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama.test")
    return OllamaBackend(base_url="http://ollama.test", timeout_seconds=5.0, client=client), client


def _request(model_name: str = "gemma_local") -> CompletionRequest:
    return CompletionRequest(
        model_name=model_name,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=32,
        temperature=0.0,
    )


def _drain(backend: OllamaBackend, client: httpx.AsyncClient, model_name: str = "gemma_local"):
    async def run():
        try:
            return [chunk async for chunk in backend.stream(_request(model_name))]
        finally:
            await client.aclose()

    return asyncio.run(run())


def test_stream_reassembles_a_json_object_split_across_network_reads():
    """Ollama's lines do not arrive aligned to socket reads."""
    backend, client = _ndjson_backend([
        b'{"message":{"content":"Hel"},"done":false}\n{"message":{"content":"lo"},"do',
        b'ne":false}\n{"message":{"content":""},"done":true,"done_reason":"stop"}\n',
    ])

    chunks = _drain(backend, client)

    assert [c.text for c in chunks if c.text] == ["Hel", "lo"]
    assert chunks[-1].done_reason == "stop"


def test_stream_terminal_chunk_carries_done_reason_length():
    """The truncation signal only exists on the last line - the text itself
    reads as a clean prefix, which is what the store guard relies on."""
    backend, client = _ndjson_backend([
        b'{"message":{"content":"cut off mid-"},"done":false}\n',
        b'{"message":{"content":""},"done":true,"done_reason":"length"}\n',
    ])

    chunks = _drain(backend, client)

    assert chunks[-1].text == ""
    assert chunks[-1].done_reason == "length"


def test_stream_raises_on_an_error_line():
    backend, client = _ndjson_backend([
        b'{"message":{"content":"partial"},"done":false}\n',
        b'{"error":"llama runner process has terminated"}\n',
    ])

    with pytest.raises(ValueError, match="llama runner"):
        _drain(backend, client)


def test_stream_skips_a_non_json_line_rather_than_dying():
    backend, client = _ndjson_backend([
        b'not json at all\n{"message":{"content":"ok"},"done":true,"done_reason":"stop"}\n',
    ])

    chunks = _drain(backend, client)

    assert [c.text for c in chunks if c.text] == ["ok"]


def test_stream_raises_model_not_found_on_ollama_404():
    """The 404 lands on the response head, before any chunk - which is what
    makes the fallback in stream_with_default_fallback safe to retry."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'ghost:1b' not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama.test")
    backend = OllamaBackend(base_url="http://ollama.test", timeout_seconds=5.0, client=client)

    with pytest.raises(ModelNotFoundError) as exc_info:
        _drain(backend, client, model_name="ghost:1b")

    assert exc_info.value.model_name == "ghost:1b"
