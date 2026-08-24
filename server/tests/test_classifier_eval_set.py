"""Fixed regression set for the LaBSE routing classifier head.

tests/data/classifier_eval_set.jsonl is a small, hand-picked, held-out set
(not part of app/services/model_artifacts/classifier_corpus.jsonl) of
unambiguous hard and easy questions in English and Hebrew. It exists so a
future edit to the training corpus is measured against a fixed bar instead
of eyeballed: any edit that makes a known-hard question stop routing
external, or makes a known-easy question start routing external, fails
this test.
"""
import json
import os

import pytest

pytestmark = [pytest.mark.labse, pytest.mark.deberta]

EVAL_SET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "classifier_eval_set.jsonl")


def _load_eval_set():
    items = []
    with open(EVAL_SET_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


EVAL_ITEMS = _load_eval_set()
HARD_ITEMS = [it for it in EVAL_ITEMS if it["label"] == "hard"]
EASY_ITEMS = [it for it in EVAL_ITEMS if it["label"] == "easy"]


def test_eval_set_has_expected_shape():
    assert len(HARD_ITEMS) == 22
    assert len(EASY_ITEMS) >= 1


@pytest.mark.parametrize("item", HARD_ITEMS, ids=[it["id"] for it in HARD_ITEMS])
def test_known_hard_question_routes_external(labse_classifier_service, item):
    result = labse_classifier_service.predict_complexity(item["text"])
    assert result["complexity"] == "hard", (
        f"{item['id']} ({item['lang']}) regressed to easy (score={result['score']:.3f}): {item['text']!r}"
    )


@pytest.mark.parametrize("item", EASY_ITEMS, ids=[it["id"] for it in EASY_ITEMS])
def test_known_easy_question_does_not_overfire(labse_classifier_service, item):
    result = labse_classifier_service.predict_complexity(item["text"])
    assert result["complexity"] == "easy", (
        f"{item['id']} ({item['lang']}) over-fired to hard (score={result['score']:.3f}): {item['text']!r}"
    )
