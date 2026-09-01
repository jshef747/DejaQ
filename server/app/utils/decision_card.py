"""One decision card per chat-completion request, for the 'requests' terminal log mode.

Presentation only: every field here is set from a value the pipeline already
computed (run_chat_pipeline in routers/openai_compat.py) — this module adds no
routing/threshold logic of its own, just a single place to format it.

A card is a handful of ordered lines ("stage -> what happened") plus loud
error lines and one outcome line. A stage that never ran adds no line — no
"validator: n/a" filler. render() is the only thing that turns it into text;
start.sh's "requests" tail matches the `CARD_MARKER` prefix so the card
replaces the old interleaved per-stage grep, while 'all' mode and the log
files keep seeing every original logger.info call unchanged.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

# Prefix start.sh greps for in "requests" log mode. Keep in sync with the
# grep pattern there if either changes.
CARD_MARKER = "DECISION_CARD"

# Logging emits one record per line, but a card is naturally multi-line and
# must survive a `grep -o` unscathed to reach start.sh's terminal — so the
# card's internal newlines are encoded as this control char and expanded
# back to real newlines by start.sh (`tr '\x01' '\n'`) after extraction.
_LINE_SEP = "\x01"

_counter = itertools.count(1)

_DIM = "\033[2m"
_RED = "\033[31;1m"
_RESET = "\033[0m"


def _c(enabled: bool, code: str, text: str) -> str:
    return f"{code}{text}{_RESET}" if enabled else text


@dataclass
class DecisionCard:
    """Accumulates one request's stage lines; render() emits the whole card."""

    question: str
    qnum: int = field(default_factory=lambda: next(_counter))
    _lines: list[tuple[str, str]] = field(default_factory=list)
    _errors: list[str] = field(default_factory=list)
    outcome: str = ""

    def add(self, label: str, text: str) -> None:
        self._lines.append((label, text))

    def error(self, text: str) -> None:
        self._errors.append(text)

    def render(self, *, color: bool = True) -> str:
        sep = "-" * 4
        head = f"{sep} Q#{self.qnum}  \"{self.question}\""
        body_lines = [
            f"   {_c(color, _DIM, f'{label:<10}')} -> {text}"
            for label, text in self._lines
        ]
        err_lines = [
            f"   {_c(color, _RED, '!! ERROR')}  {e}" for e in self._errors
        ]
        tail = f"{sep} {self.outcome}" if self.outcome else ""
        parts = [head, *body_lines, *err_lines]
        if tail:
            parts.append(tail)
        return f"{CARD_MARKER} " + _LINE_SEP.join(parts)


_STAGE_LABELS = {
    "enrich": "enrich",
    "normalize": "normalize",
    "cache": "cache",
    "validate": "validate",
    "adjust": "adjust",
    "classify": "classify",
    "rag": "rag",
    "hard_content_judge": "judge",
    "image_ocr": "ocr",
    "image_fp": "fingerprint",
    "file_extract": "file",
    "filter": "filter",
    "store": "store",
    "generate": "llm",
}


def timing_breakdown(steps: dict[str, int]) -> str:
    """Render trace.steps (name -> ms) as 'embed 0.1 · cache 0.2 · llm 2.0'."""
    parts = [
        f"{_STAGE_LABELS.get(name, name)} {ms / 1000:.1f}"
        for name, ms in steps.items()
    ]
    return " · ".join(parts)
