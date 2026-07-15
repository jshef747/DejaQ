"""Model-free tests for ValidatorService verdict parsing (fake backend)."""

import asyncio

import pytest

from app.services.validator import ValidatorService

pytestmark = pytest.mark.no_model


class _Backend:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def complete(self, request) -> str:
        return self.reply


def _validate(reply: str):
    svc = ValidatorService(backend=_Backend(reply), model_name="fake")
    return asyncio.run(svc.validate("new question", "cached question", "cached answer"))


def test_valid_verdict():
    accepted, raw = _validate("VALID")
    assert accepted is True
    assert raw == "VALID"


def test_invalid_verdict():
    accepted, raw = _validate("INVALID")
    assert accepted is False
    assert raw == "INVALID"


def test_valid_with_trailing_tokens():
    accepted, _ = _validate("VALID — it covers the question")
    assert accepted is True


def test_unparseable_fails_safe_to_invalid():
    accepted, _ = _validate("maybe, could be")
    assert accepted is False


def test_empty_fails_safe_to_invalid():
    accepted, _ = _validate("")
    assert accepted is False
