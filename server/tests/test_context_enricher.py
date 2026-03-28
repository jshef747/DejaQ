import pytest

pytestmark = pytest.mark.qwen


class TestEnrich:
    def test_no_history_returns_original(self, context_enricher_service):
        result = context_enricher_service.enrich("What is gravity?", [])
        assert result == "What is gravity?"

    def test_resolves_pronouns_with_history(self, context_enricher_service):
        history = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a high-level programming language."},
        ]
        result = context_enricher_service.enrich("Tell me more about its features", history)
        assert len(result) > 0
        assert "python" in result.lower() or "feature" in result.lower()

    def test_standalone_query_stays_relevant(self, context_enricher_service):
        history = [
            {"role": "user", "content": "What is gravity?"},
            {"role": "assistant", "content": "Gravity is a fundamental force."},
        ]
        result = context_enricher_service.enrich("What is the capital of France?", history)
        assert "france" in result.lower() or "capital" in result.lower()
