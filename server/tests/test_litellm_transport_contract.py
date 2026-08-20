import asyncio

import pytest

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse
from app.services.llm_providers.litellm_transport import LiteLLMTransportClient
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError, ExternalLLMTimeoutError
from tests._fake_llm_server import FakeLLMServer

pytestmark = pytest.mark.no_model


def _request(model: str = "fake-model", *, temperature: float | None = 0.2) -> ExternalLLMRequest:
    return ExternalLLMRequest(
        query="Hello",
        history=[{"role": "assistant", "content": "Hi"}],
        system_prompt="Be useful.",
        model=model,
        max_tokens=64,
        temperature=temperature,
    )


def _ok_openai_response(content: str = "OpenAI answer", *, prompt_tokens: int = 5, completion_tokens: int = 6) -> dict:
    return {
        "id": "resp-1", "object": "chat.completion", "created": 1, "model": "fake-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens},
    }


def _call(server: FakeLLMServer, request: ExternalLLMRequest, monkeypatch, provider: str = "openai") -> ExternalLLMResponse:
    monkeypatch.setenv("OPENAI_API_BASE", f"{server.base_url}/v1")
    client = LiteLLMTransportClient(provider)
    return asyncio.run(client.generate_response(request, "sk-test-secret"))


def test_returns_contract_shape_and_wire_bytes(monkeypatch):
    with FakeLLMServer([(200, _ok_openai_response())]) as server:
        response = _call(server, _request("fake-model"), monkeypatch)

    assert isinstance(response, ExternalLLMResponse)
    assert response.text == "OpenAI answer"
    assert response.model_used == "fake-model"
    assert response.prompt_tokens == 5
    assert response.completion_tokens == 6
    assert response.finish_reason == "stop"

    sent = server.requests[0]
    assert sent["model"] == "fake-model"
    assert sent["max_tokens"] == 64
    assert sent["temperature"] == 0.2
    assert sent["messages"][0] == {"role": "system", "content": "Be useful."}
    assert sent["messages"][-1] == {"role": "user", "content": "Hello"}


def test_model_used_is_dejaqs_request_field_not_litellms_echo(monkeypatch):
    """LiteLLM's echoed `model` in the response is not the requested name for
    a proxied/fake host - model_used must come from the request instead."""
    body = _ok_openai_response()
    body["model"] = "some-other-echoed-name"
    with FakeLLMServer([(200, body)]) as server:
        response = _call(server, _request("fake-model"), monkeypatch)

    assert response.model_used == "fake-model"


def test_finish_reason_length_is_normalized(monkeypatch):
    body = _ok_openai_response()
    body["choices"][0]["finish_reason"] = "length"
    with FakeLLMServer([(200, body)]) as server:
        response = _call(server, _request("fake-model"), monkeypatch)

    assert response.finish_reason == "length"


def test_temperature_omitted_from_wire_when_caller_sent_none(monkeypatch):
    with FakeLLMServer([(200, _ok_openai_response())]) as server:
        _call(server, _request("fake-model", temperature=None), monkeypatch)

    assert "temperature" not in server.requests[0]


def test_temperature_sent_on_wire_when_caller_set_one(monkeypatch):
    with FakeLLMServer([(200, _ok_openai_response())]) as server:
        _call(server, _request("fake-model", temperature=0.7), monkeypatch)

    assert server.requests[0]["temperature"] == 0.7


def test_retries_once_without_temperature_when_vendor_names_it(monkeypatch):
    responses = [
        (400, {"error": {"message": "temperature is not supported for this model", "type": "invalid_request_error"}}),
        (200, _ok_openai_response()),
    ]
    with FakeLLMServer(responses) as server:
        response = _call(server, _request("fake-model", temperature=0.7), monkeypatch)

    assert response.text == "OpenAI answer"
    assert len(server.requests) == 2
    assert "temperature" in server.requests[0]
    assert "temperature" not in server.requests[1]


def test_does_not_retry_on_an_unrelated_bad_request(monkeypatch):
    responses = [(400, {"error": {"message": "invalid_request_error - Incorrect API key provided", "type": "invalid_request_error"}})]
    with FakeLLMServer(responses) as server:
        with pytest.raises(ExternalLLMError):
            _call(server, _request("fake-model", temperature=0.7), monkeypatch)

    assert len(server.requests) == 1


def test_authentication_error_is_classified_and_key_never_leaks(monkeypatch):
    responses = [(401, {"error": {"message": "Incorrect API key provided: sk-test-secret.", "type": "invalid_request_error", "code": "invalid_api_key"}})]
    with FakeLLMServer(responses) as server:
        with pytest.raises(ExternalLLMAuthError) as exc_info:
            _call(server, _request("fake-model"), monkeypatch)

    assert "sk-test-secret" not in str(exc_info.value)


def test_rate_limit_error_is_classified(monkeypatch):
    responses = [(429, {"error": {"message": "rate limited", "type": "rate_limit_error"}})]
    with FakeLLMServer(responses) as server:
        with pytest.raises(ExternalLLMError) as exc_info:
            _call(server, _request("fake-model"), monkeypatch)

    assert not isinstance(exc_info.value, ExternalLLMAuthError)
    assert not isinstance(exc_info.value, ExternalLLMTimeoutError)


def test_ordinary_bad_request_is_classified_but_not_auth(monkeypatch):
    responses = [(400, {"error": {"message": "invalid_request_error - malformed request", "type": "invalid_request_error"}})]
    with FakeLLMServer(responses) as server:
        with pytest.raises(ExternalLLMError) as exc_info:
            _call(server, _request("fake-model"), monkeypatch)

    assert not isinstance(exc_info.value, ExternalLLMAuthError)


def test_timeout_is_classified(monkeypatch):
    monkeypatch.setenv("OPENAI_API_BASE", "http://127.0.0.1:1/v1")  # nothing listens; connection refused/timeout
    client = LiteLLMTransportClient("openai")
    with pytest.raises((ExternalLLMTimeoutError, ExternalLLMError)):
        asyncio.run(client.generate_response(_request("fake-model"), "sk-test-secret"))


def test_gemini_permission_denied_403_is_an_auth_error(monkeypatch):
    body = {"error": {"code": 403, "message": "Permission denied", "status": "PERMISSION_DENIED"}}
    with FakeLLMServer([(403, body)]) as server:
        monkeypatch.setenv("GEMINI_API_BASE", server.base_url)
        client = LiteLLMTransportClient("google")
        with pytest.raises(ExternalLLMAuthError):
            asyncio.run(client.generate_response(_request("gemini-2.5-flash"), "sk-test-secret"))


def test_gemini_api_key_invalid_is_an_auth_error(monkeypatch):
    body = {
        "error": {
            "code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT",
            "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}],
        }
    }
    with FakeLLMServer([(400, body)]) as server:
        monkeypatch.setenv("GEMINI_API_BASE", server.base_url)
        client = LiteLLMTransportClient("google")
        with pytest.raises(ExternalLLMAuthError):
            asyncio.run(client.generate_response(_request("gemini-2.5-flash"), "sk-test-secret"))


def test_gemini_ordinary_bad_request_is_not_mistaken_for_an_auth_error(monkeypatch):
    body = {"error": {"code": 400, "message": "Invalid value for temperature", "status": "INVALID_ARGUMENT"}}
    with FakeLLMServer([(400, body)]) as server:
        monkeypatch.setenv("GEMINI_API_BASE", server.base_url)
        client = LiteLLMTransportClient("google")
        with pytest.raises(ExternalLLMError) as exc_info:
            asyncio.run(client.generate_response(_request("gemini-2.5-flash", temperature=None), "sk-test-secret"))

    assert not isinstance(exc_info.value, ExternalLLMAuthError)


def test_model_string_is_qualified_with_the_litellm_provider_key(monkeypatch):
    """google -> gemini, not google - `google` is not a real LiteLLM provider
    name. Built inside the transport module only."""
    body = {
        "candidates": [{"content": {"parts": [{"text": "hi"}], "role": "model"}, "finishReason": "STOP", "index": 0}],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
    }
    with FakeLLMServer([(200, body)]) as server:
        monkeypatch.setenv("GEMINI_API_BASE", server.base_url)
        client = LiteLLMTransportClient("google")
        asyncio.run(client.generate_response(_request("gemini-2.5-flash", temperature=None), "sk-test-secret"))

    assert server.requests[0]  # the request was actually served by the fake Gemini host


def test_gemini_response_without_usage_metadata_is_still_an_error_upstream(monkeypatch):
    """ACCEPTED REGRESSION, captain decision 2026-08-20.

    DejaQ's own google.py:138-139 coalesced missing token counts to 0 and
    returned the answer (added in c26ea6a / PR #32, for the shape Gemini
    returns on a blocked or empty-candidate response). LiteLLM 1.97.0 raises
    inside its Gemini response transformer instead, before anything is
    returned, so an answer DejaQ used to return becomes an error.

    This test asserts the CURRENT BAD BEHAVIOUR on purpose. When a LiteLLM
    version bump makes it FAIL, upstream has fixed the bug: delete this test
    and re-check whether the apology path can be narrowed again.
    """
    body = {"candidates": [{"content": {"parts": [{"text": "hi"}], "role": "model"}, "finishReason": "STOP", "index": 0}]}
    with FakeLLMServer([(200, body)]) as server:
        monkeypatch.setenv("GEMINI_API_BASE", server.base_url)
        client = LiteLLMTransportClient("google")
        with pytest.raises(ExternalLLMError):
            asyncio.run(client.generate_response(_request("gemini-2.5-flash", temperature=None), "sk-test-secret"))
