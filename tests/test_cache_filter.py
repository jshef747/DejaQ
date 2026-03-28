import pytest

from app.services.cache_filter import should_cache

pytestmark = pytest.mark.no_model


class TestShortQueries:
    def test_single_word_rejected(self):
        result, reason = should_cache("hello", "hello")
        assert result is False
        assert "too short" in reason

    def test_two_words_rejected(self):
        result, reason = should_cache("tell me", "tell me")
        assert result is False
        assert "too short" in reason

    def test_three_words_accepted(self):
        result, _ = should_cache("what is gravity", "what is gravity")
        assert result is True


class TestFillerWords:
    @pytest.mark.parametrize("filler", [
        "ok", "okay", "yes", "no", "sure", "thanks", "thank you",
        "got it", "cool", "nice", "great", "hello", "hey", "hi",
        "bye", "yep", "nope", "alright", "right", "fine", "good",
        "lol", "haha", "wow",
    ])
    def test_filler_rejected(self, filler):
        result, reason = should_cache(filler, "some normalized text here")
        assert result is False
        assert "filler" in reason

    def test_filler_with_punctuation(self):
        result, reason = should_cache("thanks!", "some normalized text here")
        assert result is False
        assert "filler" in reason

    def test_filler_case_insensitive(self):
        result, reason = should_cache("THANKS", "some normalized text here")
        assert result is False
        assert "filler" in reason


class TestVagueEnrichedQueries:
    def test_short_enriched_rejected(self):
        result, reason = should_cache("it", "what is quantum physics explained")
        assert result is False
        assert "vague" in reason


class TestNormalQueriesPass:
    def test_question_passes(self):
        result, reason = should_cache(
            "What is the capital of France?",
            "capital of france",
        )
        assert result is True
        assert reason == "passed"

    def test_detailed_query_passes(self):
        result, reason = should_cache(
            "How does photosynthesis work in plants?",
            "how does photosynthesis work",
        )
        assert result is True
        assert reason == "passed"
