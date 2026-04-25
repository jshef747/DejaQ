import logging
import sys
from contextvars import ContextVar, Token

from app.config import LOG_LEVEL, LOG_SHOW_CONTENT


_request_id: ContextVar[str | None] = ContextVar("dejaq_request_id", default=None)


def set_request_id(request_id: str) -> Token[str | None]:
    return _request_id.set(request_id)


def clear_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def get_request_id() -> str | None:
    return _request_id.get()


def content_snippet(text: str, limit: int = 80) -> str | None:
    if not LOG_SHOW_CONTENT:
        return None
    snippet = " ".join(text.split())
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit] + "..."


def hide_content(text: str, limit: int = 80) -> str:
    return content_snippet(text, limit=limit) or "[hidden]"


class DejaQFormatter(logging.Formatter):
    """Shortens dejaq logger names for cleaner output."""

    def format(self, record):
        # 'dejaq.services.normalizer' -> 'normalizer'
        # 'dejaq.router.chat' -> 'router.chat'
        # 'dejaq.tasks.cache' -> 'tasks.cache'
        name = record.name
        if name.startswith("dejaq.services."):
            record.name = name[len("dejaq.services."):]
        elif name.startswith("dejaq."):
            record.name = name[len("dejaq."):]

        original_msg = record.msg
        original_args = record.args
        request_id = get_request_id()
        if request_id:
            record.msg = f"req={request_id} {record.getMessage()}"
            record.args = ()

        result = super().format(record)
        record.name = name  # Restore original
        record.msg = original_msg
        record.args = original_args
        return result


LOG_FORMAT = "%(asctime)s | %(levelname)-5s | %(name)-20s | %(message)s"
DATE_FORMAT = "%H:%M:%S"


def setup_logging():
    """
    Configures the root logger. Call this once in main.py.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(DejaQFormatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT))

    level = getattr(logging, LOG_LEVEL, logging.INFO)

    logging.basicConfig(level=level, handlers=[handler])
