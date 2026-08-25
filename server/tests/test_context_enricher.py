import asyncio

import pytest

pytestmark = pytest.mark.qwen


class TestEnrich:
    def test_no_history_returns_original(self, context_enricher_service):
        result = asyncio.run(context_enricher_service.enrich("What is gravity?", []))
        assert result == "What is gravity?"

    def test_resolves_pronouns_with_history(self, context_enricher_service):
        history = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a high-level programming language."},
        ]
        result = asyncio.run(context_enricher_service.enrich("Tell me more about its features", history))
        assert len(result) > 0
        assert "python" in result.lower() or "feature" in result.lower()

    def test_standalone_query_stays_relevant(self, context_enricher_service):
        history = [
            {"role": "user", "content": "What is gravity?"},
            {"role": "assistant", "content": "Gravity is a fundamental force."},
        ]
        result = asyncio.run(context_enricher_service.enrich("What is the capital of France?", history))
        assert "france" in result.lower() or "capital" in result.lower()

    def test_hebrew_followup_rewrite_stays_hebrew(self, context_enricher_service):
        """Regression for the cross-conversation cache collision (dejaq-acceptance-retest
        report): the enricher used to have no instruction against translating its
        standalone rewrite, so a Hebrew follow-up could come out English - see
        DEFAULT_SYSTEM_PROMPT's "never translate it" sentence."""
        history = [
            {"role": "user", "content": "מה מתכון טוב למרק עדשים?"},
            {"role": "assistant", "content": "הנה מתכון פשוט למרק עדשים עם ירקות ותבלינים."},
        ]
        result = asyncio.run(context_enricher_service.enrich("כמה זמן זה צריך להתבשל בערך?", history))
        hebrew_letters = sum(1 for c in result if "֐" <= c <= "׿")
        assert hebrew_letters > 0, f"rewrite dropped Hebrew entirely: {result!r}"
