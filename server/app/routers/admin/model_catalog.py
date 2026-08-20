"""The LiteLLM-backed catalog surface (migration stage A1).

The only catalog surface now - the old `GET /admin/v1/providers`
(`provider_registry.py`'s shape) was deleted in A1c once the dashboard
picker (A1b) no longer called it. Models are fetched per provider, never
all at once - the full catalog with capability fields is 349 KB and must
never land in one page load (plan section 2.11).
"""

from fastapi import APIRouter, HTTPException

from app.schemas.admin.model_catalog import (
    CatalogModelResponse,
    CatalogProviderModelsResponse,
    CatalogProviderResponse,
    CatalogProvidersListResponse,
)
from app.services import model_catalog

router = APIRouter(prefix="/model-catalog")


@router.get("/providers", response_model=CatalogProvidersListResponse)
def list_catalog_providers():
    counts = model_catalog.provider_counts()
    return CatalogProvidersListResponse(
        providers=[
            CatalogProviderResponse(key=key, model_count=count) for key, count in sorted(counts.items())
        ]
    )


@router.get("/providers/{key}/models", response_model=CatalogProviderModelsResponse)
def list_catalog_provider_models(key: str):
    if key not in model_catalog.provider_counts():
        raise HTTPException(status_code=404, detail=f"Unknown provider '{key}'.")
    models = model_catalog.models_for_provider(key)
    return CatalogProviderModelsResponse(
        provider=key,
        models=[CatalogModelResponse(id=m.id, deprecation_date=m.deprecation_date) for m in models],
    )
