import logging
import sys


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

        result = super().format(record)
        record.name = name  # Restore original
        return result


LOG_FORMAT = "%(asctime)s | %(levelname)-5s | %(name)-20s | %(message)s"
DATE_FORMAT = "%H:%M:%S"


def setup_logging():
    """
    Configures the root logger. Call this once in main.py.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(DejaQFormatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT))

    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
    )