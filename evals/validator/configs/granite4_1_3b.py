"""Validator candidate: Granite 4.1 3B (`granite4.1:3b`).

Shipped as the validator default from 2026-08-21 until this config existed.
Its absence from `configs/` is the direct reason the swap to it was never
measured by this harness; it stays here so any future swap is comparable
against what it replaced. Runs the production `ValidatorService` - see
`harness.runner.run_ollama_config`.
"""

CONFIG = {
    "name": "granite4_1_3b",
    "enabled": True,
    "use_prefilter": False,
    "heuristic_only": False,
    "ollama_model": "granite4_1_3b",
}
