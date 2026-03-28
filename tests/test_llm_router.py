import pytest

pytestmark = pytest.mark.llama


class TestGenerateResponse:
    def test_easy_returns_real_response(self, llm_router_service):
        result = llm_router_service.generate_response("What is the capital of France?", "easy")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_easy_with_history(self, llm_router_service):
        history = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
        ]
        result = llm_router_service.generate_response(
            "Tell me more about it", "easy", history=history
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_hard_returns_stub(self, llm_router_service):
        result = llm_router_service.generate_response("Explain quantum entanglement", "hard")
        assert "Simulated response for:" in result
