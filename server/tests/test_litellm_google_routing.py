"""L5: google routes through LiteLLM - the highest-scrutiny stage, verified
live by the migration spike to be the guarantee LiteLLM handles worst (a
real 403 PERMISSION_DENIED becomes litellm.BadRequestError - "your
parameters are wrong" - for what is a rejected credential).

The three tests below are the acceptance gate ported from
test_provider_clients_contract.py, now driven through the real routing
path (`ExternalLLMService` -> `external_llm._PROVIDER_CLIENTS["google"]`)
instead of monkeypatching the hand-written client's SDK seam directly. If
these three pass, the Gemini risk is closed.
"""
import asyncio

import pytest

from app.schemas.chat import ExternalLLMRequest
from app.services.external_llm import ExternalLLMService
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError
from tests._fake_llm_server import FakeLLMServer

pytestmark = pytest.mark.no_model


def _request(model: str = "gemini/gemini-2.5-flash", *, temperature: float | None = None) -> ExternalLLMRequest:
    return ExternalLLMRequest(
        query="Hello",
        history=[{"role": "assistant", "content": "Hi"}],
        system_prompt="Be useful.",
        model=model,
        max_tokens=64,
        temperature=temperature,
    )


def _call(server: FakeLLMServer, request: ExternalLLMRequest, monkeypatch):
    monkeypatch.setenv("GEMINI_API_BASE", server.base_url)
    return asyncio.run(ExternalLLMService().generate_response(request, "google", "sk-test-secret"))


def test_google_rejects_an_invalid_api_key_as_an_auth_error_not_a_bad_request(monkeypatch):
    """Gemini reports a bad key as 400 INVALID_ARGUMENT, not 401. Without the
    structured reason it lands in the generic 400 bucket, whose caller-facing
    message blames the model or its parameters instead of the credential."""
    body = {
        "error": {
            "code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT",
            "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}],
        }
    }
    with FakeLLMServer([(400, body)]) as server:
        with pytest.raises(ExternalLLMAuthError):
            _call(server, _request(), monkeypatch)


def test_google_permission_denied_is_an_auth_error_not_a_silent_apology(monkeypatch):
    """403 PERMISSION_DENIED (suspended, disabled, or referer-restricted key)
    matched no surfaced status, so it fell through to the generic HTTP 200
    apology - the invisible failure this contract exists to prevent."""
    body = {"error": {"code": 403, "message": "Permission denied", "status": "PERMISSION_DENIED"}}
    with FakeLLMServer([(403, body)]) as server:
        with pytest.raises(ExternalLLMAuthError):
            _call(server, _request(), monkeypatch)


def test_google_ordinary_bad_request_is_not_mistaken_for_an_auth_error(monkeypatch):
    """The control: a 400 INVALID_ARGUMENT about the request itself carries no
    API_KEY_INVALID reason and must stay a plain provider error."""
    body = {"error": {"code": 400, "message": "Unknown field 'temperature'.", "status": "INVALID_ARGUMENT"}}
    with FakeLLMServer([(400, body)]) as server:
        with pytest.raises(ExternalLLMError) as raised:
            _call(server, _request(), monkeypatch)
    assert not isinstance(raised.value, ExternalLLMAuthError)


def test_gemini_response_without_usage_metadata_is_still_an_error_upstream(monkeypatch):
    """ACCEPTED REGRESSION, captain decision 2026-08-20.

    DejaQ's google.py:138-139 coalesced missing token counts to 0 and returned
    the answer (added in c26ea6a / PR #32, for the shape Gemini returns on a
    blocked or empty-candidate response). LiteLLM raises inside its Gemini
    response transformer instead, before anything is returned, so that answer
    becomes an error DejaQ turns into the generic apology.

    This test asserts the CURRENT BAD BEHAVIOUR on purpose. When a LiteLLM
    version bump makes it FAIL, upstream has fixed the bug: delete this test
    and re-check whether the apology path can be narrowed again.

    Pinned: litellm==1.97.0. Same regression, now asserted through the real
    routed path (`ExternalLLMService` -> google) now that L5 wires it live -
    the transport-level twin of this test has covered the transport module
    itself since L1a.
    """
    body = {"candidates": [{"content": {"parts": [{"text": "hi"}], "role": "model"}, "finishReason": "STOP", "index": 0}]}
    with FakeLLMServer([(200, body)]) as server:
        with pytest.raises(ExternalLLMError):
            _call(server, _request(), monkeypatch)
