import logging

from app.utils.logger import (
    DejaQFormatter,
    clear_request_id,
    hide_content,
    set_request_id,
)


def _format_message(message: str, *, request_id: str | None = None) -> str:
    record = logging.LogRecord(
        name="dejaq.router.openai_compat",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    token = set_request_id(request_id) if request_id is not None else None
    try:
        return DejaQFormatter("%(levelname)s | %(name)s | %(message)s").format(record)
    finally:
        if token is not None:
            clear_request_id(token)


def test_formatter_omits_request_field_without_context():
    formatted = _format_message("done cache=miss")

    assert "req=" not in formatted
    assert "openai_compat" in formatted


def test_formatter_includes_request_context_when_set():
    formatted = _format_message("done cache=hit", request_id="chatcmpl-abc12345")

    assert "req=chatcmpl-abc12345 done cache=hit" in formatted


def test_hide_content_masks_text_by_default(monkeypatch):
    monkeypatch.setattr("app.utils.logger.LOG_SHOW_CONTENT", False)

    assert hide_content("What is my private prompt?") == "[hidden]"


def test_hide_content_can_return_truncated_snippet(monkeypatch):
    monkeypatch.setattr("app.utils.logger.LOG_SHOW_CONTENT", True)

    assert hide_content("abcdefghijklmnopqrstuvwxyz", limit=10) == "abcdefghij..."
