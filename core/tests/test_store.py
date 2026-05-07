from __future__ import annotations

from otel_a2a_relay_core.store import TaskStore


def test_put_and_get_returns_copy() -> None:
    s = TaskStore()
    s.put({"id": "t1", "status": {"state": "completed"}})
    got = s.get("t1")
    assert got is not None
    got["status"]["state"] = "mutated"
    again = s.get("t1")
    assert again is not None
    assert again["status"]["state"] == "completed"


def test_get_missing_returns_none() -> None:
    s = TaskStore()
    assert s.get("nope") is None


def test_update_state_overwrites_status() -> None:
    s = TaskStore()
    s.put({"id": "t1", "status": {"state": "completed", "timestamp": "x"}})
    updated = s.update_state("t1", "canceled")
    assert updated is not None
    assert updated["status"]["state"] == "canceled"
    assert updated["status"]["timestamp"] == "x"


def test_put_without_id_is_dropped() -> None:
    s = TaskStore()
    s.put({"status": {"state": "completed"}})
    assert s.all() == []


def test_all_returns_independent_copies() -> None:
    s = TaskStore()
    s.put({"id": "a", "x": 1})
    s.put({"id": "b", "x": 2})
    listed = s.all()
    listed[0]["x"] = 999
    assert sorted(t["x"] for t in s.all()) == [1, 2]


def test_lru_eviction_at_cap() -> None:
    s = TaskStore(max_tasks=3)
    for i in range(5):
        s.put({"id": f"t{i}"})
    ids = [t["id"] for t in s.all()]
    assert ids == ["t2", "t3", "t4"]


def test_update_state_returns_none_when_missing() -> None:
    s = TaskStore()
    assert s.update_state("nope", "completed") is None


def test_reput_refreshes_lru_order() -> None:
    s = TaskStore(max_tasks=3)
    s.put({"id": "a"})
    s.put({"id": "b"})
    s.put({"id": "c"})
    s.put({"id": "a"})  # refreshes a to most-recent
    s.put({"id": "d"})  # evicts b (now oldest)
    ids = [t["id"] for t in s.all()]
    assert ids == ["c", "a", "d"]
