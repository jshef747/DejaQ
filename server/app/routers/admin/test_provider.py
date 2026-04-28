from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.db.session import get_session
from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext
from app.routers.admin.credentials import _credential_service, _resolve_authorized_org
from app.schemas.chat import ExternalLLMRequest
from app.schemas.test_provider import TestProviderRequest, TestProviderResponse
from app.services.credential_service import SUPPORTED_PROVIDERS, CredentialService
from app.services.external_llm import ExternalLLMService
from app.services.llm_providers import LIVE_PROVIDERS, redact_api_key
from app.services.provider_inference import provider_for_model
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError, ExternalLLMTimeoutError

router = APIRouter()
_external_llm = ExternalLLMService()


def _load_org_api_key(org_slug: str, ctx: ManagementAuthContext, provider: str) -> str | None:
    org_id = _resolve_authorized_org(org_slug, ctx)
    service: CredentialService = _credential_service()
    with get_session() as session:
        return service.get_decrypted_key(session, org_id, provider)


@router.post("/orgs/{org_slug}/test-provider", response_model=TestProviderResponse)
async def test_provider(
    org_slug: str,
    body: TestProviderRequest,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    try:
        provider = provider_for_model(body.model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if provider in SUPPORTED_PROVIDERS and provider not in LIVE_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"Provider '{provider}' is not yet wired.")

    api_key = await run_in_threadpool(_load_org_api_key, org_slug, ctx, provider)
    if api_key is None:
        raise HTTPException(status_code=402, detail=f"No {provider} API key configured for this organization.")

    request = ExternalLLMRequest(
        query=body.prompt,
        history=[],
        system_prompt="You are a helpful assistant for connectivity testing.",
        model=body.model,
        max_tokens=256,
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

    return TestProviderResponse(
        text=response.text,
        model_used=response.model_used,
        provider=provider,
        latency_ms=response.latency_ms,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
    )
