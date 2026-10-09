import threading
import time

import pytest

from ai import Action, Decision, DecisionWorker, MockJevController


def snapshot():
    return {
        "player": {"hp_percent": 100, "ammo": 5, "max_ammo": 10, "reserve_ammo": 10,
                   "medkits": 0, "weapon_ready": True, "reloading": False},
        "threat": {"zombie_count": 1, "nearest_zombie_distance": 300,
                   "zombies_within_100": 0, "zombies_within_200": 0},
        "resources": {"nearest_medkit_distance": None, "nearest_ammo_distance": None},
        "context": {"survival_time": 3, "kills": 1, "wave": 1},
    }


class Immediate:
    def decide(self, state):
        return Decision(Action.SHOOT_NEAREST, source="mock")


class Blocking:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.daemon = None

    def decide(self, state):
        self.calls += 1
        self.daemon = threading.current_thread().daemon
        self.started.set()
        if not self.release.wait(3):
            raise RuntimeError("test controller not released")
        return Decision(Action.HEAL, source="mock")


def wait_idle(worker):
    deadline = time.monotonic() + 1
    while worker.busy and time.monotonic() < deadline:
        threading.Event().wait(.001)
    assert not worker.busy


def wait_result(worker):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        result = worker.poll(time.monotonic())
        if result is not None:
            return result
        threading.Event().wait(.001)
    pytest.fail("worker did not deliver a result")


def test_success_generation_and_snapshot_isolation():
    class Mutating:
        def decide(self, state):
            state["player"]["hp_percent"] = 1
            return Decision(Action.SHOOT_NEAREST, source="mock")

    worker = DecisionWorker()
    state = snapshot()
    assert worker.submit(Mutating(), state, time.monotonic(), 17)
    state["player"]["ammo"] = 0
    result = wait_result(worker)
    assert result.generation == 17
    assert result.state["player"]["ammo"] == 5
    assert result.state["player"]["hp_percent"] == 100
    assert state["player"]["hp_percent"] == 100
    assert result.decision.action == Action.SHOOT_NEAREST
    assert result.decision.latency_ms >= 0
    assert worker.poll(time.monotonic()) is None
    assert not worker.busy
    worker.close()


def test_timeout_once_stays_busy_no_overlap_and_discards_late_result():
    worker = DecisionWorker(timeout=.01)
    controller = Blocking()
    try:
        assert worker.submit(controller, snapshot(), time.monotonic(), 4)
        assert controller.started.wait(1)
        assert controller.daemon is True
        assert worker.busy
        threading.Event().wait(.02)
        result = worker.poll(time.monotonic())
        assert result.generation == 4
        assert result.decision.source == "fallback"
        assert result.decision.error == "timeout"
        assert result.decision.confidence is None
        assert worker.busy
        assert worker.poll(time.monotonic()) is None
        assert not worker.submit(controller, snapshot(), time.monotonic(), 5)
        assert controller.calls == 1
        controller.release.set()
        wait_idle(worker)
        assert worker.poll(time.monotonic()) is None
        assert worker.submit(Immediate(), snapshot(), time.monotonic(), 6)
        assert wait_result(worker).generation == 6
    finally:
        controller.release.set()
        wait_idle(worker)
        worker.close()


def test_close_is_nonblocking_global_gate_survives_mode_switch():
    old = DecisionWorker()
    new = DecisionWorker()
    controller = Blocking()
    try:
        assert old.submit(controller, snapshot(), time.monotonic(), 1)
        assert controller.started.wait(1)
        started = time.monotonic()
        old.close()
        assert time.monotonic() - started < .1
        assert old.busy
        assert not old.submit(Immediate(), snapshot(), time.monotonic(), 2)
        assert not new.submit(Immediate(), snapshot(), time.monotonic(), 2)
        controller.release.set()
        wait_idle(old)
        assert old.poll(time.monotonic()) is None
        assert new.submit(Immediate(), snapshot(), time.monotonic(), 2)
        assert wait_result(new).generation == 2
    finally:
        controller.release.set()
        wait_idle(old)
        old.close()
        new.close()


def test_global_gate_retained_after_timeout_in_another_worker():
    first = DecisionWorker(timeout=.01)
    second = DecisionWorker()
    controller = Blocking()
    try:
        assert first.submit(controller, snapshot(), time.monotonic(), 1)
        assert controller.started.wait(1)
        threading.Event().wait(.02)
        assert first.poll(time.monotonic()).decision.error == "timeout"
        assert not second.submit(Immediate(), snapshot(), time.monotonic(), 2)
        controller.release.set()
        wait_idle(first)
        assert second.submit(Immediate(), snapshot(), time.monotonic(), 2)
        wait_result(second)
    finally:
        controller.release.set()
        wait_idle(first)
        first.close()
        second.close()


def test_late_completion_before_poll_still_yields_timeout():
    worker = DecisionWorker(timeout=.01)
    controller = Blocking()
    try:
        assert worker.submit(controller, snapshot(), time.monotonic(), 1)
        assert controller.started.wait(1)
        threading.Event().wait(.02)
        controller.release.set()
        wait_idle(worker)
        assert worker.poll(time.monotonic()).decision.error == "timeout"
        assert worker.poll(time.monotonic()) is None
    finally:
        controller.release.set()
        wait_idle(worker)
        worker.close()


def test_timely_completion_is_not_timeout_when_poll_is_delayed():
    worker = DecisionWorker(timeout=.1)
    assert worker.submit(Immediate(), snapshot(), time.monotonic(), 1)
    wait_idle(worker)
    threading.Event().wait(.12)
    result = worker.poll(time.monotonic())
    assert result.decision.source == "mock" and result.decision.error is None
    worker.close()


@pytest.mark.parametrize("failure,expected", [
    (RuntimeError("secret-api-token=do-not-log"), "controller_error"),
    (KeyError("secret-api-token=do-not-log"), "missing_key"),
    (TimeoutError("secret-api-token=do-not-log"), "timeout"),
    (PermissionError("secret-api-token=do-not-log"), "authentication_error"),
    (ConnectionError("secret-api-token=do-not-log"), "network_error"),
    (ValueError("secret-api-token=do-not-log"), "invalid_response"),
])
def test_controller_exception_is_sanitized(failure, expected):
    class Broken:
        def decide(self, state):
            raise failure

    worker = DecisionWorker()
    assert worker.submit(Broken(), snapshot(), time.monotonic(), 9)
    result = wait_result(worker)
    assert result.decision.source == "fallback" and result.decision.error == expected
    assert "secret" not in repr(result.decision.to_dict())
    worker.close()


@pytest.mark.parametrize("candidate", [None, {"action": "HEAL"}, "bad"])
def test_malformed_return_yields_fallback(candidate):
    class Broken:
        def decide(self, state):
            return candidate

    worker = DecisionWorker()
    assert worker.submit(Broken(), snapshot(), time.monotonic(), 1)
    decision = wait_result(worker).decision
    assert decision.source == "fallback" and decision.error == "malformed_decision"
    worker.close()


def test_invalid_mutated_decision_yields_fallback():
    class Broken:
        def decide(self, state):
            decision = Decision(Action.HEAL)
            decision.probabilities = {"NOT_AN_ACTION": 1}
            return decision

    worker = DecisionWorker()
    assert worker.submit(Broken(), snapshot(), time.monotonic(), 1)
    assert wait_result(worker).decision.error == "malformed_decision"
    worker.close()


def test_missing_state_key_yields_fallback():
    worker = DecisionWorker()
    assert worker.submit(MockJevController(), {}, time.monotonic(), 1)
    result = wait_result(worker)
    assert result.decision.source == "fallback"
    assert result.decision.error == "missing_key"
    worker.close()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True, "5"])
def test_invalid_timeout_rejected(timeout):
    with pytest.raises(ValueError):
        DecisionWorker(timeout=timeout)
