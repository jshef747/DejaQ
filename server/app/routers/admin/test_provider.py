import logging
import time

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.db.session import get_session
from app.routers.admin.credentials import _credential_service, _resolve_workspace_id
from app.schemas.chat import ExternalLLMRequest
from app.schemas.test_provider import TestProviderRequest, TestProviderResponse
from app.services.credential_service import SUPPORTED_PROVIDERS, CredentialService
from app.services.external_llm import ExternalLLMService
from app.services.llm_config_service import resolve_provider_for_model
from app.services.llm_providers import LIVE_PROVIDERS, redact_api_key
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError, ExternalLLMTimeoutError

logger = logging.getLogger("dejaq.routers.admin.test_provider")

router = APIRouter()
_external_llm = ExternalLLMService()
# Nothing checks the text against this anymore (see the removed exact-match
# assertion below) - a minimal neutral prompt is cheaper and does not tempt a
# reasoning model into spending its budget reasoning about matching a format.
_PROVIDER_TEST_PROMPT = "Say hello."
_PROVIDER_TEST_COOLDOWN_SECONDS = 60.0
_provider_test_last_success: dict[tuple[str, str], float] = {}


def _load_workspace_api_key(workspace_slug: str, provider: str) -> str | None:
    workspace_id = _resolve_workspace_id(workspace_slug)
    service: CredentialService = _credential_service()
    with get_session() as session:
        return service.get_decrypted_key(session, workspace_id, provider)


def _check_provider_test_cooldown(workspace_slug: str, provider: str) -> None:
    key = (workspace_slug, provider)
    now = time.monotonic()
    last_success = _provider_test_last_success.get(key)
    if last_success is None:
        return
    wait_seconds = _PROVIDER_TEST_COOLDOWN_SECONDS - (now - last_success)
    if wait_seconds > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Provider test recently succeeded; wait {int(wait_seconds) + 1}s before trying again.",
        )


def _record_provider_test_success(workspace_slug: str, provider: str) -> None:
    _provider_test_last_success[(workspace_slug, provider)] = time.monotonic()


@router.post("/workspaces/{workspace_slug}/test-provider", response_model=TestProviderResponse)
async def test_provider(
    workspace_slug: str,
    body: TestProviderRequest,
):
    # No stored config row applies here - body.model is a candidate the admin
    # may not have saved yet. Resolved via the legacy exact table for a bare
    # legacy id, or LiteLLM's own qualified-name resolution otherwise - no
    # name-prefix guess either way (see llm_config_service.resolve_provider_for_model).
    provider = resolve_provider_for_model(body.model)
    if provider is None:
        raise HTTPException(
            status_code=422, detail=f"Unknown provider for model '{body.model}'."
        )

    if provider in SUPPORTED_PROVIDERS and provider not in LIVE_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"Provider '{provider}' is not yet wired.")

    api_key = await run_in_threadpool(_load_workspace_api_key, workspace_slug, provider)
    if api_key is None:
        raise HTTPException(status_code=402, detail=f"No {provider} API key configured for this workspace.")

    _check_provider_test_cooldown(workspace_slug, provider)

    request = ExternalLLMRequest(
        query=_PROVIDER_TEST_PROMPT,
        history=[],
        system_prompt="You are a helpful assistant for connectivity testing.",
        model=body.model,
        # 8 was fine while the catalog was 36 curated (non-reasoning) models.
        # A reasoning model spends this budget on hidden reasoning tokens
        # before it emits any visible text, so 8 came back empty even on a
        # fully successful call. 64 gives a reasoning model realistic room to
        # finish a one-line reply while staying far below a real-answer
        # budget - this runs on a button press, on the workspace's own key.
        max_tokens=64,
    )
    try:
        response = await _external_llm.generate_response(request, provider=provider, api_key=api_key)
    except ExternalLLMAuthError as exc:
        # 502, not 401: on /admin/v1/* a 401 means the dashboard's own session
        # failed, and dashboard/lib/api.ts throws "session may have expired"
        # before it ever reads the body - so a rejected provider key reported
        # as 401 loses its message on the one button that exists to show it.
        logger.warning(
            "Provider test rejected by %s: %s", provider, redact_api_key(exc, api_key)
        )
        raise HTTPException(
            status_code=502,
            detail=(
                f"The {provider} credential configured for this workspace was rejected. "
                "Check the API key in the workspace's provider settings."
            ),
        ) from exc
    except ExternalLLMTimeoutError as exc:
        detail = redact_api_key(exc, api_key)
        raise HTTPException(status_code=504, detail=f"Provider timed out: {detail}") from exc
    except ExternalLLMError as exc:
        detail = redact_api_key(exc, api_key)
        raise HTTPException(status_code=502, detail=f"Provider request failed: {detail}") from exc

    # This button answers "can this key reach this model", not "does the
    # model follow instructions" - a response arriving at all (no exception
    # above) proves that, whatever the model chose to say. An empty
    # `response.text` still counts: a reasoning model can spend the whole
    # budget on hidden reasoning tokens and return no visible text while the
    # call itself succeeded, and that is a model-behavior quirk, not a
    # connectivity failure.
    _record_provider_test_success(workspace_slug, provider)

    return TestProviderResponse(
        ok=True,
        model_used=response.model_used,
        provider=provider,
        latency_ms=response.latency_ms,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
    )
