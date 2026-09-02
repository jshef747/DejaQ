"""Per-file-type attachment routing: the workspace's attachment_routing map
decides local vs. external per attachment type, replacing the old "attachments
always try local" rule.

Two layers:
  - Pure decision logic (services/attachment_routing.py) - fast, no server.
    This is where the UNRECOGNISED-type default (external) is pinned.
  - Pipeline wiring (openai_compat) - a file/image of a LOCAL-mapped type
    answers local; the same type moved to EXTERNAL answers external; an
    unrecognised extension answers external. Mirrors test_hard_content_routing's
    harness (judge mocked, no real Ollama).
"""
import base64

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.schemas.chat import ExternalLLMResponse
from app.services import attachment_routing
from tests.conftest import StreamingLocalRouterMixin
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubNormalizer,
    stored_credential,
)

pytestmark = pytest.mark.no_model

QUESTION = "what does this say?"
LOCAL_ANSWER = "answered locally"
SMALL_FILE = b"Total is 1 plus 2 plus 3. " * 5  # clears CACHE_FILE_MIN_CHARS, fits locally


# --- Pure decision logic ----------------------------------------------------

def test_default_map_routes_by_group():
    eff = attachment_routing.effective_map(None)
    # tabular -> external, images -> local, prose docs -> auto (judge)
    assert attachment_routing.route_for_attachment(eff, filename="q.csv", mime="text/csv", is_image=False) == "external"
    assert attachment_routing.route_for_attachment(eff, filename="r.pdf", mime=None, is_image=False) == "auto"
    assert attachment_routing.route_for_attachment(eff, filename="notes.txt", mime="text/plain", is_image=False) == "auto"
    assert attachment_routing.route_for_attachment(eff, filename=None, mime="image/png", is_image=True) == "local"


def test_unrecognised_type_routes_external():
    eff = attachment_routing.effective_map(None)
    # extension in neither defaults nor overrides
    assert attachment_routing.route_for_attachment(eff, filename="a.xyz", mime=None, is_image=False) == "external"
    # no signal at all (no extension, no usable MIME subtype)
    assert attachment_routing.route_for_attachment(eff, filename=None, mime="", is_image=False) == "external"


def test_override_moves_a_type_between_destinations():
    eff = attachment_routing.effective_map({"csv": "local", "pdf": "external"})
    assert attachment_routing.route_for_attachment(eff, filename="q.csv", mime=None, is_image=False) == "local"
    assert attachment_routing.route_for_attachment(eff, filename="r.pdf", mime=None, is_image=False) == "external"


def test_custom_type_is_honoured():
    eff = attachment_routing.effective_map({"flac": "local"})
    assert attachment_routing.route_for_attachment(eff, filename="song.flac", mime=None, is_image=False) == "local"


def test_overrides_prune_drops_defaults_keeps_diffs_and_custom():
    pruned = attachment_routing.overrides_from_full(
        attachment_routing.validate_full_map(
            {"pdf": "auto", "csv": "external", "md": "external", "flac": "external"}
        )
    )
    assert "pdf" not in pruned  # equal to default (auto) -> dropped
    assert "csv" not in pruned  # equal to default (external) -> dropped
    assert pruned == {"md": "external", "flac": "external"}


def test_validate_full_map_rejects_bad_key_and_route():
    with pytest.raises(ValueError):
        attachment_routing.validate_full_map({"bad ext": "local"})
    with pytest.raises(ValueError):
        attachment_routing.validate_full_map({"csv": "sideways"})


# --- Pipeline wiring --------------------------------------------------------

class StubRouter(StreamingLocalRouterMixin):
    def __init__(self, answer: str = LOCAL_ANSWER):
        self.answer = answer
        self.calls = 0

    async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None, images=None):
        self.calls += 1
        return self.answer, 12.0, "stop"


class CapturingExternalLLM:
    def __init__(self):
        self.request = None

    async def generate_response(self, request, provider=None, api_key=None):
        self.request = request
        return ExternalLLMResponse(
            text="answered externally", model_used=request.model,
            prompt_tokens=5, completion_tokens=6, latency_ms=10.0,
        )


class ExplodingExternalLLM:
    async def generate_response(self, request, provider=None, api_key=None):
        raise AssertionError("external route must not be used here")


class _NoHitMemory:
    def lookup_cache(self, clean_query: str):
        from app.services.memory_chromaDB import CacheLookupResult
        return CacheLookupResult(hit=False)

    def store_interaction(self, *a, **k):
        return "id"

    def increment_hit_count(self, doc_id: str):
        return None

    def count_file_entries(self, file_sha: str) -> int:
        return 0


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE
    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )
    monkeypatch.setattr(_KEY_CACHE, "namespace", lambda *a, **kw: "test-namespace")


def _judge_must_not_run(*a, **k):
    raise AssertionError("the hard-content judge must not run once the map routes external")


def _patch_pipeline(monkeypatch, router, *, external=None, external_model=None, attachment_routing_map=None, judge_over_text=None):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", router)
    monkeypatch.setattr(openai_compat, "_external_llm", external or ExplodingExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: _NoHitMemory())
    monkeypatch.setattr(
        openai_compat.ollama_catalog, "supports_vision", lambda model, force_refresh=False: True
    )
    _config_kwargs = {"external_model": external_model, "routing_threshold": 0.9}
    if attachment_routing_map is not None:
        _config_kwargs["attachment_routing"] = attachment_routing_map
    monkeypatch.setattr(
        openai_compat, "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(**_config_kwargs),
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    if external_model is not None:
        monkeypatch.setattr("app.config.CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
        monkeypatch.setattr(
            openai_compat, "get_workspace_provider_key",
            stored_credential("sk-ant-live", providers=("anthropic",)),
        )
    if judge_over_text is not None:
        monkeypatch.setattr(openai_compat, "_judge_hard_content_over_text", judge_over_text)


def _post_file(query, data, *, filename="doc.txt", mime="text/plain"):
    part = {
        "type": "input_file",
        "filename": filename,
        "file_data": f"data:{mime};base64," + base64.b64encode(data).decode(),
    }
    return TestClient(app, headers=_AUTH).post(
        "/v1/responses",
        json={"model": "gpt-4o", "input": [{"role": "user", "content": [{"type": "input_text", "text": query}, part]}], "stream": False},
    )


async def _judge_easy(*a, **k):
    return False


async def _judge_hard(*a, **k):
    return True


def test_auto_mapped_file_is_judged_and_answers_local_when_easy(monkeypatch):
    """A .txt (default 'auto') runs the content-difficulty judge; an easy
    verdict answers local."""
    router = StubRouter()
    _patch_pipeline(monkeypatch, router, judge_over_text=_judge_easy)
    resp = _post_file(QUESTION, SMALL_FILE, filename="notes.txt", mime="text/plain")
    assert resp.status_code == 200
    assert resp.json()["output_text"] == LOCAL_ANSWER
    assert router.calls == 1


def test_auto_mapped_file_answers_external_when_judged_hard(monkeypatch):
    """The same 'auto' .txt goes external when the judge says hard - the judge,
    not a hard bucket, decides."""
    router = StubRouter()
    external = CapturingExternalLLM()
    _patch_pipeline(
        monkeypatch, router, external=external, external_model="claude-sonnet-4-6",
        judge_over_text=_judge_hard,
    )
    resp = _post_file(QUESTION, SMALL_FILE, filename="notes.txt", mime="text/plain")
    assert resp.status_code == 200
    assert resp.json()["output_text"] == "answered externally"
    assert router.calls == 0


def test_local_mapped_type_skips_the_judge(monkeypatch):
    """A type pinned 'local' answers local WITHOUT calling the content judge -
    that is the whole difference between 'local' and 'auto'."""
    router = StubRouter()
    _patch_pipeline(
        monkeypatch, router,
        attachment_routing_map={**attachment_routing.effective_map(None), "txt": "local"},
        judge_over_text=_judge_must_not_run,
    )
    resp = _post_file(QUESTION, SMALL_FILE, filename="notes.txt", mime="text/plain")
    assert resp.status_code == 200
    assert resp.json()["output_text"] == LOCAL_ANSWER
    assert router.calls == 1


def test_external_mapped_type_answers_externally_without_judging(monkeypatch):
    """A .csv (default external) goes external on the map alone - the
    hard-content judge (an extra Ollama round trip) must not run."""
    router = StubRouter()
    external = CapturingExternalLLM()
    _patch_pipeline(
        monkeypatch, router, external=external, external_model="claude-sonnet-4-6",
        judge_over_text=_judge_must_not_run,
    )
    resp = _post_file(QUESTION, SMALL_FILE, filename="ledger.csv", mime="text/csv")
    assert resp.status_code == 200
    assert resp.json()["output_text"] == "answered externally"
    assert router.calls == 0
    assert external.request is not None


def test_same_type_moved_to_external_flips_the_route(monkeypatch):
    """The same .txt that answered local above answers external once the
    workspace maps txt -> external - proving the map, not the file, decides."""
    router = StubRouter()
    external = CapturingExternalLLM()
    _patch_pipeline(
        monkeypatch, router, external=external, external_model="claude-sonnet-4-6",
        attachment_routing_map={**attachment_routing.effective_map(None), "txt": "external"},
        judge_over_text=_judge_must_not_run,
    )
    resp = _post_file(QUESTION, SMALL_FILE, filename="notes.txt", mime="text/plain")
    assert resp.status_code == 200
    assert resp.json()["output_text"] == "answered externally"
    assert router.calls == 0


def test_unrecognised_extension_routes_external(monkeypatch):
    """An extension in neither the defaults nor the overrides is unrecognised
    and routes external (captain-confirmed default). `.log` is a valid UTF-8
    text file so it passes the attachment parser, then the map sends it out."""
    router = StubRouter()
    external = CapturingExternalLLM()
    _patch_pipeline(
        monkeypatch, router, external=external, external_model="claude-sonnet-4-6",
        judge_over_text=_judge_must_not_run,
    )
    resp = _post_file(QUESTION, SMALL_FILE, filename="server.log", mime="text/plain")
    assert resp.status_code == 200
    assert resp.json()["output_text"] == "answered externally"
    assert router.calls == 0


def test_auto_route_uses_the_configured_judge_prompt(monkeypatch):
    """An 'auto' file runs the judge with the workspace's configured
    judge_system_prompt (the judge is its own pipeline role now)."""
    captured = {}

    async def _recording_judge(llm_router, judge_text, system_prompt=None):
        captured["prompt"] = system_prompt
        return False  # easy -> local

    router = StubRouter()
    monkeypatch.setattr(openai_compat, "_judge_hard_content", _recording_judge)
    monkeypatch.setattr(
        openai_compat, "_read_effective_llm_config",
        lambda ws, wid: openai_compat.EffectiveLlmConfig(
            external_model=None, routing_threshold=0.9,
            judge_system_prompt="CUSTOM-JUDGE-PROMPT reply HARD or EASY",
        ),
    )
    # minimal pipeline stubs (mirrors _patch_pipeline without re-reading config)
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", router)
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: _NoHitMemory())
    monkeypatch.setattr(openai_compat.ollama_catalog, "supports_vision", lambda m, force_refresh=False: True)
    async def _noop_log(*a, **k):
        return None
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda e, c, **kw: (False, "t"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    resp = _post_file(QUESTION, SMALL_FILE, filename="notes.txt", mime="text/plain")
    assert resp.status_code == 200
    assert captured["prompt"] == "CUSTOM-JUDGE-PROMPT reply HARD or EASY"
    assert resp.json()["output_text"] == LOCAL_ANSWER
