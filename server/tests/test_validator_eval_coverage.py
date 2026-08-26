"""The validator role cannot be swapped to a model the harness never measured.

On 2026-08-21 the validator default moved to `granite4_1_3b`. There was no
`granite4_1_3b` config in `evals/validator/configs/`, so the project's own
harness could not measure the model that shipped, and nothing failed. When it
was finally measured it scored 88.7% against the previous model's 93.7% on the
300-pair corpus, and 73.2% against 85.7% on referential follow-up fragments.

Two holes let that through, and this file closes both:

1. **No config for the shipped model.** `test_shipped_validator_model_has_an_eval_config`
   fails the moment `VALIDATOR_MODEL_NAME` names a model with no config, so a
   swap has to bring its measurement with it.
2. **No corpus for the class that broke.** The 300-pair set contains no
   referential follow-up fragments ("what's the difference?", "how so?") - the
   shape a real second turn takes, and the one the validator is handed raw
   because the pipeline passes `user_query`, not the enriched question. That
   set ranked the three candidates 100% / 93.7% / 88.7% while the follow-up
   corpus ranks them 73.2% / 85.7% / 73.2%: it does not predict this class.
   The remaining tests keep `pairs_follow_up_fragment.json` present, balanced
   and in the loader's record shape.

This is a coverage test, not an accuracy test - it calls no model and needs no
Ollama. Accuracy lives in the harness:

    cd evals/validator
    ../../server/.venv/bin/python -m harness.runner \
        --configs granite4_1_3b,gemma_e2b,gemma_e4b --all-datasets
"""

import importlib.util
import json
from pathlib import Path

import pytest

from app.config import VALIDATOR_MODEL_NAME

EVALS_DIR = Path(__file__).resolve().parents[2] / "evals" / "validator"
CONFIGS_DIR = EVALS_DIR / "configs"
FOLLOW_UP_SET = EVALS_DIR / "dataset" / "pairs_follow_up_fragment.json"

# The seven keys harness/runner.py::run_config reads off every pair.
REQUIRED_PAIR_KEYS = {
    "id",
    "category",
    "cached_query",
    "cached_answer",
    "new_query",
    "expected_verdict",
    "rationale",
}


def _load_config(path: Path) -> dict:
    """Import a config module by path - `configs` is not on this project's path."""
    spec = importlib.util.spec_from_file_location(f"_eval_config_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CONFIG


def _measurable_configs() -> dict[str, dict]:
    """Configs that run a real model through the shipped ValidatorService.

    Keyed by the logical model name they measure (the `MODEL_RUNTIME_SPECS`
    key), which is what `VALIDATOR_MODEL_NAME` holds.
    """
    out = {}
    for path in sorted(CONFIGS_DIR.glob("*.py")):
        if path.stem == "__init__":
            continue
        # The pre-Ollama GGUF configs carry their own drifted copy of the
        # system prompt and are disabled; they measure something else.
        if path.stem in ("qwen_1_5b", "qwen_0_5b", "phi_3_5_mini", "qwen_1_5b_prefilter"):
            continue
        config = _load_config(path)
        if config.get("ollama_model"):
            out[config["ollama_model"]] = config
    return out


def test_shipped_validator_model_has_an_eval_config():
    """The model actually serving validation must be one the harness can run."""
    measurable = _measurable_configs()
    assert VALIDATOR_MODEL_NAME in measurable, (
        f"VALIDATOR_MODEL_NAME is {VALIDATOR_MODEL_NAME!r} but evals/validator/configs/ "
        f"can only measure {sorted(measurable)}. Add a config for it before shipping the "
        f"swap - this is exactly how granite4_1_3b shipped unmeasured on 2026-08-21."
    )


def test_the_model_the_validator_was_swapped_away_from_stays_measurable():
    """Keep the outgoing model runnable so the next swap has a baseline.

    granite4_1_3b is not the default any more; deleting its config would make
    the comparison that justified replacing it unreproducible.
    """
    assert "granite4_1_3b" in _measurable_configs()


@pytest.mark.parametrize("logical_name", ["gemma_e2b", "granite4_1_3b", "gemma_local"])
def test_candidate_configs_name_a_real_runtime_spec(logical_name):
    """A config's `ollama_model` is a logical role name, not an Ollama tag."""
    from app.services.model_backends import MODEL_RUNTIME_SPECS

    assert logical_name in _measurable_configs()
    assert logical_name in MODEL_RUNTIME_SPECS


def test_follow_up_fragment_corpus_is_present_and_balanced():
    assert FOLLOW_UP_SET.exists(), (
        "pairs_follow_up_fragment.json is gone. It is the only corpus covering "
        "referential follow-up fragments, the class the 300-pair set does not predict."
    )
    pairs = json.loads(FOLLOW_UP_SET.read_text(encoding="utf-8"))
    assert len(pairs) >= 100
    valid = [p for p in pairs if p["expected_verdict"] == "VALID"]
    invalid = [p for p in pairs if p["expected_verdict"] == "INVALID"]
    # Balanced on purpose: the shipped failure was one-directional (false
    # rejections), and an unbalanced set hides one direction behind the other.
    assert len(valid) == len(invalid) == len(pairs) // 2


def test_follow_up_fragment_pairs_load_in_the_harness_record_shape():
    pairs = json.loads(FOLLOW_UP_SET.read_text(encoding="utf-8"))
    ids = set()
    for pair in pairs:
        missing = REQUIRED_PAIR_KEYS - pair.keys()
        assert not missing, f"{pair.get('id')} is missing {sorted(missing)}"
        assert pair["category"] == "follow_up_fragment"
        assert pair["expected_verdict"] in ("VALID", "INVALID")
        assert pair["new_query"].strip()
        assert pair["cached_answer"].strip()
        ids.add(pair["id"])
    assert len(ids) == len(pairs), "duplicate pair ids"


def test_corpus_keeps_contentless_fragments_the_shipped_model_failed_on():
    """The 42 contentless fragments are the population that ranks the models.

    granite accepted 12 of them, gemma_e2b 28. Trimming this class out of the
    corpus would silently restore the blind spot the corpus exists to remove.
    """
    pairs = json.loads(FOLLOW_UP_SET.read_text(encoding="utf-8"))
    contentless = [p for p in pairs if p.get("fragment_type") == "contentless"]
    servable = [p for p in contentless if p["expected_verdict"] == "VALID"]
    assert len(servable) >= 40
