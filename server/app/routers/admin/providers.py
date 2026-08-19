from fastapi import APIRouter

from app.schemas.admin.providers import ProviderModelResponse, ProviderResponse, ProvidersListResponse
from app.services.provider_registry import PROVIDERS

router = APIRouter()


@router.get("/providers", response_model=ProvidersListResponse)
def list_providers():
    return ProvidersListResponse(
        providers=[
            ProviderResponse(
                key=spec.key,
                live=spec.live,
                client_shape=spec.client_shape.value if spec.client_shape else None,
                models=[
                    ProviderModelResponse(
                        id=model.id,
                        label=model.label,
                        input_kinds=sorted(kind.value for kind in model.input_kinds),
                    )
                    for model in spec.models
                ],
            )
            for spec in PROVIDERS.values()
        ]
    )
