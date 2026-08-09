"""The score-floor eviction beat task must never touch RAG (Rug) collections.

RAG chunks are admin-curated, carry no score, and live in "{workspace}__rag_kb"
collections precisely so they are not swept like the volatile Q→A cache. The beat
task iterates every Chroma collection, so it must skip the RAG ones by name.
"""
import pytest

from app.tasks import cache_tasks

pytestmark = pytest.mark.no_model


class _FakeMemory:
    def __init__(self, namespace, swept):
        self.namespace = namespace
        self._swept = swept

    def evict_below_floor(self, floor):
        self._swept.append(self.namespace)
        return 1


def test_eviction_skips_rag_namespaces(monkeypatch):
    swept: list[str] = []
    monkeypatch.setattr(cache_tasks, "get_memory_service", lambda ns: _FakeMemory(ns, swept))
    monkeypatch.setattr(cache_tasks, "_pool", {})
    monkeypatch.setattr(
        cache_tasks, "list_namespaces",
        # Note "acme__rag" here is a DEPARTMENT named "RAG" (a Q→A cache), which
        # must still be swept — only the true knowledge-base collections
        # ("__rag_kb") are skipped.
        lambda: ["acme__eng", "acme__rag_kb", "acme__rag", "acme--default", "beta__rag_kb"],
    )

    result = cache_tasks.evict_low_score_entries()

    # The two __rag_kb collections were left alone; every cache namespace — including
    # a department literally named "rag" — was swept.
    assert sorted(swept) == ["acme--default", "acme__eng", "acme__rag"]
    assert result == {"status": "ok", "deleted": 3}
