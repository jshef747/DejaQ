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
    wire-level assertions.
    """

    def __init__(self, responses: list[tuple[int, dict]]) -> None:
        self.responses = responses
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
