import pytest

pytestmark = [pytest.mark.phi, pytest.mark.qwen_1_5b]


class TestGeneralize:
    def test_strips_casual_tone(self, context_adjuster_service):
        result = context_adjuster_service.generalize(
            "Yo, so basically gravity is like the Earth just pulling stuff down, ya know?"
        )
        assert len(result) > 0
        assert "gravity" in result.lower() or "force" in result.lower()

    def test_neutral_input_passes_through(self, context_adjuster_service):
        neutral = "Photosynthesis is the process by which plants convert light energy into chemical energy."
        result = context_adjuster_service.generalize(neutral)
        assert len(result) > 0
        assert "photosynthesis" in result.lower()

    def test_returns_nonempty(self, context_adjuster_service):
        result = context_adjuster_service.generalize("The capital of France is Paris!")
        assert isinstance(result, str)
        assert len(result.strip()) > 0


class TestAdjust:
    def test_matches_casual_tone(self, context_adjuster_service):
        result = context_adjuster_service.adjust(
            original_query="explain gravity like I'm 5",
            general_answer="Gravity is a fundamental force of attraction between objects with mass.",
        )
        assert len(result) > 0

    def test_matches_formal_tone(self, context_adjuster_service):
        result = context_adjuster_service.adjust(
            original_query="Provide a detailed analysis of photosynthesis",
            general_answer="Photosynthesis is how plants make food from sunlight.",
        )
        assert len(result) > 0

    def test_returns_nonempty(self, context_adjuster_service):
        result = context_adjuster_service.adjust(
            original_query="what is gravity",
            general_answer="Gravity is a force.",
        )
        assert isinstance(result, str)
        assert len(result.strip()) > 0
