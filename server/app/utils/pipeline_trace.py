from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class PipelineTrace:
    steps: dict[str, int] = field(default_factory=dict)

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.steps[name] = int((time.perf_counter() - start) * 1000)

    def set_step(self, name: str, latency_ms: int) -> None:
        self.steps[name] = latency_ms

    def summary(self) -> str:
        return " ".join(f"{name}:{latency}ms" for name, latency in self.steps.items())
