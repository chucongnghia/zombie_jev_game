import json
from types import SimpleNamespace

from pygame import Vector2
import pytest

from ai import Action, AIController, AIMetrics, Decision, FallbackController, GameStateBuilder, MockJevController


def make_world():
    return SimpleNamespace(
        player=SimpleNamespace(hp=40, max_hp=100, ammo=3, max_ammo=10, reserve_ammo=20,
                               medkits=1, cooldown=0, reload_remaining=0, pos=Vector2(0, 0)),
        zombies=[SimpleNamespace(pos=Vector2(60, 80)), SimpleNamespace(pos=Vector2(150, 0)),
                 SimpleNamespace(pos=Vector2(300, 0))],
        pickups=[SimpleNamespace(kind="medkit", pos=Vector2(30, 40)),
                 SimpleNamespace(kind="ammo", pos=Vector2(200, 0)),
                 SimpleNamespace(kind="other", pos=Vector2(0, 0))],
        survival_time=12.5, kills=4, wave=2,
    )


def test_action_contract_and_decision_export():
    assert len(Action) == 7
    decision = Decision(Action.HEAL, .7, {"HEAL": .7, "HOLD_POSITION": .3}, "jev", 12)
    assert decision.validate() is decision
    exported = decision.to_dict()
    assert exported["action"] == "HEAL"
    assert json.loads(json.dumps(exported, allow_nan=False)) == exported
    exported["probabilities"]["HEAL"] = 0
    assert decision.probabilities["HEAL"] == .7


@pytest.mark.parametrize("overrides", [
    {"action": "HEAL"}, {"action": 1}, {"confidence": float("nan")},
    {"confidence": float("inf")}, {"confidence": -0.1}, {"confidence": 1.1},
    {"confidence": True}, {"confidence": "0.5"}, {"probabilities": []},
    {"probabilities": {"INVALID": 1}}, {"probabilities": {1: 1}},
    {"probabilities": {"HEAL": float("nan")}}, {"probabilities": {"HEAL": float("inf")}},
    {"probabilities": {"HEAL": -1}}, {"probabilities": {"HEAL": True}},
    {"probabilities": {"HEAL": .2}}, {"latency_ms": -1},
    {"latency_ms": float("nan")}, {"latency_ms": True}, {"source": ""},
    {"source": None}, {"error": {"secret": "not permitted"}},
])
def test_invalid_decisions_rejected(overrides):
    values = {"action": Action.HOLD_POSITION}
    values.update(overrides)
    with pytest.raises(ValueError):
        Decision(**values)


def test_rounded_probabilities_preserved_without_normalization():
    probabilities = {"HEAL": .50, "HOLD_POSITION": .49}
    decision = Decision(Action.HEAL, .50, probabilities, "jev")
    assert decision.to_dict()["probabilities"] == probabilities
    assert decision.confidence == .50


def test_validate_rechecks_mutated_decision():
    decision = Decision(Action.HEAL)
    decision.confidence = float("nan")
    with pytest.raises(ValueError):
        decision.validate()


def test_state_builder_compact_json_and_distances():
    state = GameStateBuilder.build(make_world())
    assert state["player"] == {"hp_percent": 40.0, "ammo": 3, "max_ammo": 10,
                               "reserve_ammo": 20, "medkits": 1,
                               "weapon_ready": True, "reloading": False}
    assert state["threat"] == {"zombie_count": 3, "nearest_zombie_distance": 100.0,
                               "zombies_within_100": 1, "zombies_within_200": 2}
    assert state["resources"] == {"nearest_medkit_distance": 50.0, "nearest_ammo_distance": 200.0}
    assert state["context"] == {"survival_time": 12.5, "kills": 4, "wave": 2}
    assert json.loads(json.dumps(state, allow_nan=False)) == state


def test_absent_entities_and_readiness():
    world = make_world()
    world.zombies = []
    world.pickups = []
    world.player.reload_remaining = 1
    state = GameStateBuilder().build(world)
    assert state["threat"]["nearest_zombie_distance"] is None
    assert state["resources"]["nearest_ammo_distance"] is None
    assert state["resources"]["nearest_medkit_distance"] is None
    assert state["player"]["reloading"] and not state["player"]["weapon_ready"]
    world.player.reload_remaining = 0
    world.player.cooldown = .1
    assert not GameStateBuilder.build(world)["player"]["weapon_ready"]
    world.player.max_hp = 0
    assert GameStateBuilder.build(world)["player"]["hp_percent"] == 0


@pytest.mark.parametrize("updates,nearest,action", [
    ({}, 20, Action.MOVE_AWAY),
    ({}, 100, Action.HEAL),
    ({"hp_percent": 100, "ammo": 0}, 200, Action.RELOAD),
    ({"hp_percent": 100, "ammo": 0}, 100, Action.MOVE_AWAY),
    ({"hp_percent": 100, "ammo": 0, "reserve_ammo": 0}, 200, Action.MOVE_TO_AMMO),
    ({"medkits": 0}, 200, Action.MOVE_TO_MEDKIT),
    ({"hp_percent": 100}, 200, Action.SHOOT_NEAREST),
    ({"hp_percent": 100, "reloading": True}, 200, Action.MOVE_AWAY),
    ({"hp_percent": 100, "ammo": 10}, None, Action.HOLD_POSITION),
])
def test_fallback_safety_has_no_fabricated_confidence(updates, nearest, action):
    state = GameStateBuilder.build(make_world())
    state["player"].update(updates)
    state["threat"]["nearest_zombie_distance"] = nearest
    decision = FallbackController().decide(state)
    assert decision.action == action
    assert decision.source == "fallback"
    assert decision.confidence is None and decision.probabilities == {}
    assert decision.latency_ms is None


def test_fallback_tolerates_malformed_state():
    decision = FallbackController().decide({"player": None})
    assert decision.action == Action.HOLD_POSITION
    assert decision.error == "invalid_state"


def test_mock_synthetic_normalized_reproducible_and_protocol():
    state = GameStateBuilder.build(make_world())
    first = MockJevController(7)
    second = MockJevController(7)
    assert isinstance(first, AIController)
    for _ in range(3):
        decision = first.decide(state)
        assert decision.to_dict() == second.decide(state).to_dict()
        assert decision.source == "mock"
        assert set(decision.probabilities) == {action.value for action in Action}
        assert sum(decision.probabilities.values()) == pytest.approx(1)
        assert decision.confidence == decision.probabilities[decision.action.value]
        assert decision.action == FallbackController().decide(state).action


def test_mock_rejects_missing_snapshot_keys():
    with pytest.raises(KeyError):
        MockJevController().decide({})


def test_metrics_live_and_benchmark_use_same_api():
    for recorder in (AIMetrics(), AIMetrics()):
        empty = recorder.summary()
        assert empty["total_decisions"] == 0
        assert empty["average_confidence"] is None
        assert empty["fallback_rate"] == 0
        assert empty["lowest_confidence_decision"] is None
        recorder.record(Decision(Action.HEAL, .8, {}, "jev", 10))
        recorder.record(Decision(Action.HEAL, .4, {}, "jev", 30))
        recorder.record(Decision(Action.RELOAD, .6, {}, "mock", 999))
        recorder.record(Decision(Action.MOVE_AWAY, source="fallback", error="timeout"))
        summary = recorder.summary()
        assert summary["total_decisions"] == 4 and summary["jev_decisions"] == 2
        assert summary["average_confidence"] == pytest.approx(.6)
        assert summary["average_jev_latency"] == 20
        assert summary["api_errors"] == 1 and summary["fallback_count"] == 1
        assert summary["fallback_rate"] == .25
        assert summary["most_used_action"] == "HEAL"
        assert summary["highest_confidence_action"] == {"action": "HEAL", "confidence": .8, "source": "jev"}
        assert summary["lowest_confidence_decision"]["confidence"] == .4
        summary["lowest_confidence_decision"]["confidence"] = 0
        assert recorder.summary()["lowest_confidence_decision"]["confidence"] == .4
