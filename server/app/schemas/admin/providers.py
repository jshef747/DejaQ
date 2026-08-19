from pydantic import BaseModel


class ProviderModelResponse(BaseModel):
    id: str
    label: str
    input_kinds: list[str]


class ProviderResponse(BaseModel):
    key: str
    live: bool
    client_shape: str | None
    models: list[ProviderModelResponse]


class ProvidersListResponse(BaseModel):
    providers: list[ProviderResponse]
