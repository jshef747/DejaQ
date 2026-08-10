from fastapi import APIRouter, Query

from app.services import ollama_catalog

router = APIRouter()


@router.get("/available-models")
def available_models(refresh: bool = Query(False, description="Bypass the cache and re-query Ollama now")):
    # 200 always, even when Ollama is unreachable: that is an expected,
    # named state of this one resource (Ollama), not a broken admin API -
    # the dashboard picker reads `error` and disables editing with the
    # reason shown, rather than treating this like a 5xx server fault.
    try:
        models = ollama_catalog.list_available_models(force_refresh=refresh)
    except ollama_catalog.OllamaUnreachableError as exc:
        return {"models": [], "error": str(exc)}
    return {"models": models, "error": None}
