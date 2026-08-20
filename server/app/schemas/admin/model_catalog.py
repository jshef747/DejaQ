from pydantic import BaseModel


class CatalogProviderResponse(BaseModel):
    key: str
    model_count: int


class CatalogProvidersListResponse(BaseModel):
    providers: list[CatalogProviderResponse]


class CatalogModelResponse(BaseModel):
    id: str
    deprecation_date: str | None


class CatalogProviderModelsResponse(BaseModel):
    provider: str
    models: list[CatalogModelResponse]
