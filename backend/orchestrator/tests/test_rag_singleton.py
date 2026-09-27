"""
Tests for the RAGService process-wide singleton.

The reset hook is deliberately NOT autouse across the whole suite —
doing so would re-trigger the SentenceTransformer model load once per
test, which is the exact cost the singleton exists to avoid. This file
opts into the reset locally via an autouse fixture that is scoped to
this module only.

Multi-worker caveat: these tests verify single-process behavior. Under
Uvicorn --workers N, each worker constructs its own singleton, which
is expected and tested nowhere here.
"""
import threading

import pytest

from src.services import rag_service as rag_module
from src.services.rag_service import (
    RAGService,
    get_rag_service,
    _reset_rag_singleton,
)


@pytest.fixture(autouse=True)
def _clean_singleton():
    """
    Reset the singleton before and after each test in this file, so
    these tests are deterministic regardless of what ran earlier.
    """
    _reset_rag_singleton()
    yield
    _reset_rag_singleton()


def test_get_rag_service_returns_same_instance():
    a = get_rag_service()
    b = get_rag_service()
    assert a is b
    assert isinstance(a, RAGService)


def test_reset_constructs_fresh_instance():
    first = get_rag_service()
    _reset_rag_singleton()
    second = get_rag_service()
    assert first is not second


def test_reset_when_never_constructed_is_safe():
    """Reset on an already-None singleton must not raise."""
    _reset_rag_singleton()
    _reset_rag_singleton()  # second call, still None
    # No assertion — the point is "does not raise".


def test_get_rag_service_is_thread_safe():
    """
    Hammer get_rag_service() from many threads after a reset. All
    callers must receive the same instance; the double-checked lock
    must not produce two RAGService objects.

    Model load happens once for whichever thread wins the lock; the
    others block briefly and then read the already-built instance.
    """
    _reset_rag_singleton()

    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()  # maximize overlap
        results.append(get_rag_service())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    first = results[0]
    assert all(r is first for r in results), (
        "get_rag_service() returned different instances across threads"
    )


def test_incident_service_uses_singleton(monkeypatch):
    """
    IncidentService.__init__ must call get_rag_service(), not
    RAGService() directly.
    """
    from src.services.incident_service import IncidentService

    _reset_rag_singleton()

    with monkeypatch.context() as m:
        # LLMService is still eagerly constructed; stub it out so we
        # don't build the LLM provider chain in a singleton test.
        m.setattr(
            "src.services.incident_service.LLMService",
            lambda: object(),
        )
        svc_a = IncidentService()
        svc_b = IncidentService()

    assert svc_a.rag is svc_b.rag, (
        "Two IncidentService instances got different RAG instances — "
        "the singleton is not being used."
    )


def test_get_rag_service_does_not_construct_when_already_set(monkeypatch):
    """
    The second call must not construct a new RAGService. Spy on the
    constructor and assert it is called exactly once across three calls.
    """
    _reset_rag_singleton()

    constructor_calls = {"n": 0}
    real_cls = rag_module.RAGService

    class CountingRAG(real_cls):
        def __init__(self):
            constructor_calls["n"] += 1
            super().__init__()

    monkeypatch.setattr(rag_module, "RAGService", CountingRAG)

    get_rag_service()
    get_rag_service()
    get_rag_service()

    assert constructor_calls["n"] == 1
