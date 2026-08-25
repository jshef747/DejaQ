from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services import classifier, labse_classifier

pytestmark = pytest.mark.labse


def test_uses_shared_device_selector():
    """The new loader must reuse classifier._select_device (which already
    prefers CUDA, then MPS, then CPU) rather than reimplementing its own -
    that's what carries the MPS fix to this loader too."""
    assert labse_classifier._select_device is classifier._select_device


def test_head_path_points_at_bundled_artifact():
    import os

    assert labse_classifier.HEAD_PATH.endswith(
        os.path.join("model_artifacts", "head_full_labse.joblib")
    )
    assert os.path.isfile(labse_classifier.HEAD_PATH)


class TestPredictComplexityThreshold:
    """Threshold behaviour in isolation, without loading the real backbone."""

    def _service_with_stubbed_head(self, score: float):
        svc = labse_classifier.LabseClassifierService.__new__(labse_classifier.LabseClassifierService)
        svc._embed = MagicMock(return_value=np.zeros((1, 768)))
        head = MagicMock()
        head.predict_proba.return_value = np.array([[1 - score, score]])
        svc._head = head
        return svc

    def test_score_at_or_above_threshold_is_hard(self):
        svc = self._service_with_stubbed_head(0.5)
        with patch.object(labse_classifier.config, "ROUTING_THRESHOLD", 0.5):
            result = svc.predict_complexity("anything")
        assert result["complexity"] == "hard"
        assert result["score"] == pytest.approx(0.5)
        assert result["task_type"] == "labse"

    def test_score_below_threshold_is_easy(self):
        svc = self._service_with_stubbed_head(0.49)
        with patch.object(labse_classifier.config, "ROUTING_THRESHOLD", 0.5):
            result = svc.predict_complexity("anything")
        assert result["complexity"] == "easy"


@pytest.mark.deberta
class TestPredictComplexityRealModel:
    """Real backbone + trained head - mirrors classifier.py's own
    corpus-derived sanity checks (test_classifier.py), plus the language the
    head was never trained on at all."""

    def test_returns_expected_keys(self, labse_classifier_service):
        result = labse_classifier_service.predict_complexity("What is the capital of France?")
        assert set(result) == {"complexity", "score", "task_type"}
        assert result["complexity"] in ("easy", "hard")
        assert 0.0 <= result["score"] <= 1.0

    def test_easy_english_scores_below_hard_english(self, labse_classifier_service):
        easy = labse_classifier_service.predict_complexity("What's the capital of France?")
        hard = labse_classifier_service.predict_complexity(
            "Prove that there are infinitely many prime numbers."
        )
        assert easy["score"] < hard["score"]
        assert easy["complexity"] == "easy"
        assert hard["complexity"] == "hard"

    def test_easy_hebrew_scores_below_hard_hebrew(self, labse_classifier_service):
        easy = labse_classifier_service.predict_complexity("מה בירת צרפת?")
        hard = labse_classifier_service.predict_complexity(
            "הוכח שיש אינסוף מספרים ראשוניים."
        )
        assert easy["score"] < hard["score"]
        assert easy["complexity"] == "easy"
        assert hard["complexity"] == "hard"

    def test_unseen_language_still_separates_easy_from_hard(self, labse_classifier_service):
        """German is not one of the seven corpus languages the head was
        fit on - this is the transfer property the report measured, not a
        held-out corpus item."""
        easy = labse_classifier_service.predict_complexity(
            "Was ist die Hauptstadt von Frankreich?"
        )
        hard = labse_classifier_service.predict_complexity(
            "Beweise, dass es unendlich viele Primzahlen gibt."
        )
        assert easy["score"] < hard["score"]
        assert easy["complexity"] == "easy"
        assert hard["complexity"] == "hard"
