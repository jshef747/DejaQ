import pytest

pytestmark = pytest.mark.qwen


class TestNormalize:
    def test_strips_casual_tone_quantum(self, normalizer_service):
        result = normalizer_service.normalize("hey can you explain quantum mechanics like I'm 5")
        assert "quantum" in result.lower()
        assert len(result) > 0

    def test_strips_casual_tone_france(self, normalizer_service):
        result = normalizer_service.normalize("yo what's the capital of france lol")
        assert "france" in result.lower()

    def test_preserves_photosynthesis(self, normalizer_service):
        result = normalizer_service.normalize(
            "I was wondering if you could tell me how photosynthesis works in detail please"
        )
        assert "photosynthesis" in result.lower()

    def test_returns_nonempty(self, normalizer_service):
        result = normalizer_service.normalize("what is gravity")
        assert isinstance(result, str)
        assert len(result.strip()) > 0

    def test_clean_query_passes_through(self, normalizer_service):
        result = normalizer_service.normalize("capital of Japan")
        assert "japan" in result.lower() or "capital" in result.lower()
