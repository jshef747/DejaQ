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

import pytest

from app.services.model_backends import CompletionChunk
from tests.test_openai_compat_smoke import _AUTH, _patch_for_truncation


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


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
