import pytest

pytestmark = pytest.mark.deberta


class TestPredictComplexity:
    def test_returns_expected_keys(self, classifier_service):
        result = classifier_service.predict_complexity("What is the capital of France?")
        assert "complexity" in result
        assert "score" in result
        assert "task_type" in result

    def test_complexity_is_easy_or_hard(self, classifier_service):
        result = classifier_service.predict_complexity("Hello, how are you?")
        assert result["complexity"] in ("easy", "hard")

    def test_score_is_float_in_range(self, classifier_service):
        result = classifier_service.predict_complexity("What is gravity?")
        assert isinstance(result["score"], float)
        assert 0.0 <= result["score"] <= 1.0

    def test_task_type_is_nonempty(self, classifier_service):
        result = classifier_service.predict_complexity("Summarize this article")
        assert isinstance(result["task_type"], str)
        assert len(result["task_type"]) > 0

    def test_simple_query_leans_easy(self, classifier_service):
        result = classifier_service.predict_complexity("What is 2 + 2?")
        assert result["complexity"] == "easy"

    def test_complex_query_scores_higher(self, classifier_service):
        simple = classifier_service.predict_complexity("What is 2 + 2?")
        complex_ = classifier_service.predict_complexity(
            "Compare and contrast the economic policies of Keynesianism and monetarism, "
            "analyzing their historical effectiveness across at least three different countries "
            "and providing specific GDP data to support your arguments."
        )
        assert complex_["score"] > simple["score"]
