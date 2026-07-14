import time

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.db.session import get_session
from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext
from app.routers.admin.credentials import _credential_service, _resolve_authorized_workspace
from app.schemas.chat import ExternalLLMRequest
from app.schemas.test_provider import TestProviderRequest, TestProviderResponse
from app.services.credential_service import SUPPORTED_PROVIDERS, CredentialService
from app.services.external_llm import ExternalLLMService
from app.services.llm_providers import LIVE_PROVIDERS, redact_api_key
from app.services.provider_inference import provider_for_model
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError, ExternalLLMTimeoutError

router = APIRouter()
_external_llm = ExternalLLMService()
_PROVIDER_TEST_PROMPT = "Reply with exactly: OK"
_PROVIDER_TEST_COOLDOWN_SECONDS = 60.0
_provider_test_last_success: dict[tuple[str, str, str], float] = {}


def _load_workspace_api_key(workspace_slug: str, ctx: ManagementAuthContext, provider: str) -> str | None:
    workspace_id = _resolve_authorized_workspace(workspace_slug, ctx)
    service: CredentialService = _credential_service()
    with get_session() as session:
        return service.get_decrypted_key(session, workspace_id, provider)


def _rate_limit_key(workspace_slug: str, provider: str, ctx: ManagementAuthContext) -> tuple[str, str, str]:
    if ctx.is_system:
        actor = "system"
    else:
        actor = f"user:{ctx.local_user_id or ctx.supabase_user_id or ctx.email or 'unknown'}"
    return (workspace_slug, provider, actor)


def _check_provider_test_cooldown(workspace_slug: str, provider: str, ctx: ManagementAuthContext) -> None:
    key = _rate_limit_key(workspace_slug, provider, ctx)
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


def _record_provider_test_success(workspace_slug: str, provider: str, ctx: ManagementAuthContext) -> None:
    _provider_test_last_success[_rate_limit_key(workspace_slug, provider, ctx)] = time.monotonic()


@router.post("/workspaces/{workspace_slug}/test-provider", response_model=TestProviderResponse)
async def test_provider(
    workspace_slug: str,
    body: TestProviderRequest,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    try:
        provider = provider_for_model(body.model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if provider in SUPPORTED_PROVIDERS and provider not in LIVE_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"Provider '{provider}' is not yet wired.")

    api_key = await run_in_threadpool(_load_workspace_api_key, workspace_slug, ctx, provider)
    if api_key is None:
        raise HTTPException(status_code=402, detail=f"No {provider} API key configured for this workspace.")

    _check_provider_test_cooldown(workspace_slug, provider, ctx)

    request = ExternalLLMRequest(
        query=_PROVIDER_TEST_PROMPT,
        history=[],
        system_prompt="You are a helpful assistant for connectivity testing.",
        model=body.model,
        max_tokens=8,
        temperature=0.0,
    )
    try:
        response = await _external_llm.generate_response(request, provider=provider, api_key=api_key)
    except ExternalLLMAuthError as exc:
        detail = redact_api_key(exc, api_key)
        raise HTTPException(status_code=401, detail=f"API key was rejected by {provider}: {detail}") from exc
    except ExternalLLMTimeoutError as exc:
        detail = redact_api_key(exc, api_key)
        raise HTTPException(status_code=504, detail=f"Provider timed out: {detail}") from exc
    except ExternalLLMError as exc:
        detail = redact_api_key(exc, api_key)
        raise HTTPException(status_code=502, detail=f"Provider request failed: {detail}") from exc

    if response.text.strip().upper() != "OK":
        raise HTTPException(status_code=502, detail="Provider test returned an unexpected response.")

    _record_provider_test_success(workspace_slug, provider, ctx)

    return TestProviderResponse(
        ok=True,
        model_used=response.model_used,
        provider=provider,
        latency_ms=response.latency_ms,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
    )
