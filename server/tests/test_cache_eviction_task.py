"""Which namespaces the score-floor eviction beat task actually sweeps.

`_pool` is a per-process cache of MemoryService instances, filled lazily as a
worker serves traffic. Iterating it meant the beat task swept only what this
worker had already touched since it started: nothing at all after a restart, and
never a department whose traffic went to a different worker. The entries a score
floor exists to delete are exactly the ones nobody is asking for, so the pool is
the one list guaranteed not to contain them.
"""
import pytest

from app.tasks import cache_tasks

pytestmark = pytest.mark.no_model


class _FakeMemory:
    def __init__(self, namespace: str, swept: list[str]):
        self.namespace = namespace
        self._swept = swept

    def evict_below_floor(self, floor: float) -> int:
        self._swept.append(self.namespace)
        return 1


def _patch_memory(monkeypatch, swept: list[str]):
    monkeypatch.setattr(
        cache_tasks, "get_memory_service", lambda ns: _FakeMemory(ns, swept)
    )


def test_eviction_sweeps_namespaces_this_worker_has_never_touched(monkeypatch):
    swept: list[str] = []
    _patch_memory(monkeypatch, swept)
    # A freshly restarted worker: it has served nothing yet.
    monkeypatch.setattr(cache_tasks, "_pool", {})
    monkeypatch.setattr(
        cache_tasks, "list_namespaces", lambda: ["acme__eng", "acme__sales", "acme--default"]
    )

    result = cache_tasks.evict_low_score_entries()

    assert sorted(swept) == ["acme--default", "acme__eng", "acme__sales"]
    assert result == {"status": "ok", "deleted": 3}


def test_eviction_falls_back_to_the_local_pool_when_chroma_cannot_be_listed(monkeypatch):
    """Sweeping less than everything beats sweeping nothing, but it is a failure
    and says so in the log."""
    swept: list[str] = []
    _patch_memory(monkeypatch, swept)
    monkeypatch.setattr(cache_tasks, "_pool", {"acme__eng": object()})

    def _boom():
        raise ConnectionError("chroma is down")

    monkeypatch.setattr(cache_tasks, "list_namespaces", _boom)

    result = cache_tasks.evict_low_score_entries()

    assert swept == ["acme__eng"]
    assert result == {"status": "ok", "deleted": 1}


def test_one_unreachable_namespace_does_not_stop_the_sweep(monkeypatch):
    swept: list[str] = []

    def _service(ns):
        if ns == "broken":
            raise RuntimeError("collection gone")
        return _FakeMemory(ns, swept)

    monkeypatch.setattr(cache_tasks, "get_memory_service", _service)
    monkeypatch.setattr(cache_tasks, "_pool", {})
    monkeypatch.setattr(cache_tasks, "list_namespaces", lambda: ["broken", "acme__eng"])

    result = cache_tasks.evict_low_score_entries()

    assert swept == ["acme__eng"]
    assert result == {"status": "ok", "deleted": 1}
