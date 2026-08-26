"""Validator candidate: Gemma 4 E2B (`gemma4:e2b`) - the shipped default.

Runs through the production `ValidatorService` against live Ollama, so the
prompt, few-shots and inference options are whatever `server/app/services/
validator.py` currently uses. See `harness.runner.run_ollama_config`.
"""

CONFIG = {
    "name": "gemma_e2b",
    "enabled": True,
    "use_prefilter": False,
    "heuristic_only": False,
    # Logical role name in server/app/services/model_backends.py MODEL_RUNTIME_SPECS.
    "ollama_model": "gemma_e2b",
}
