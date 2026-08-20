"""A local HTTP server standing in for a provider endpoint in LiteLLM
transport tests. Deliberately not SDK monkeypatching: it asserts on the
bytes LiteLLM actually sends over the wire, which is what makes the suite
survive a future change of transport (migration plan §4, exit seam 8).
"""

import http.server
import json
import threading


class FakeLLMServer:
    """Serves a scripted sequence of (status, json-body) responses.

    Each request pops the next scripted response (repeating the last one
    once exhausted) and records the parsed request body in `.requests` for
    wire-level assertions. The request path is recorded in `.paths` too -
    Gemini's API puts the model in the URL, not the JSON body.
    """

    def __init__(self, responses: list[tuple[int, dict]]) -> None:
        self.responses = responses
        self.requests: list[dict] = []
        self.paths: list[str] = []
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _make_handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                outer.requests.append(json.loads(body) if body else {})
                outer.paths.append(self.path)
                index = min(len(outer.requests) - 1, len(outer.responses) - 1)
                status, payload = outer.responses[index]
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def log_message(self, *args: object) -> None:  # noqa: ARG002 - silence stdlib access logs
                pass

        return Handler

    @property
    def base_url(self) -> str:
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}"

    def __enter__(self) -> "FakeLLMServer":
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()


class FakeSSEServer:
    """Serves one scripted OpenAI-shaped SSE completion stream.

    Emits one delta chunk per entry in `chunk_texts`, a terminal
    finish_reason=stop chunk, an optional usage-only chunk, then [DONE].
    """

    def __init__(self, chunk_texts: list[str], final_usage: dict | None = None) -> None:
        self.chunk_texts = chunk_texts
        self.final_usage = final_usage
        self.requests: list[dict] = []
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _make_handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                outer.requests.append(json.loads(body) if body else {})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for i, text in enumerate(outer.chunk_texts):
                        delta = {"content": text} if i else {"role": "assistant", "content": text}
                        chunk = {
                            "id": "1", "object": "chat.completion.chunk", "created": 1, "model": "fake-model",
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                        }
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                        self.wfile.flush()
                    finish_chunk = {
                        "id": "1", "object": "chat.completion.chunk", "created": 1, "model": "fake-model",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                    self.wfile.write(f"data: {json.dumps(finish_chunk)}\n\n".encode())
                    if outer.final_usage is not None:
                        usage_chunk = {
                            "id": "1", "object": "chat.completion.chunk", "created": 1, "model": "fake-model",
                            "choices": [], "usage": outer.final_usage,
                        }
                        self.wfile.write(f"data: {json.dumps(usage_chunk)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the consumer abandoned the stream - expected in the leak test

            def log_message(self, *args: object) -> None:  # noqa: ARG002 - silence stdlib access logs
                pass

        return Handler

    @property
    def base_url(self) -> str:
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}"

    def __enter__(self) -> "FakeSSEServer":
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()
