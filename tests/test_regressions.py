"""Failures found during independent review, retained as integration regressions."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import threading
import time
import pygame
import pytest
from ai.models import Action, Decision
from ai.decision_worker import DecisionWorker
from ai.state_builder import GameStateBuilder
from game.config import Settings
from game.game import Game
from game.world import World
from game.systems.action_executor import ActionExecutor


class BlockedRemote:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def decide(self, state):
        self.started.set()
        self.release.wait(2)
        return Decision(Action.HOLD_POSITION, None, {}, "jev", 1)

    def finish(self, worker):
        self.release.set()
        deadline = time.monotonic() + 1
        while worker.busy and time.monotonic() < deadline:
            threading.Event().wait(0.001)
        worker.close()


@pytest.mark.parametrize("mode", ["mock", "jev"])
def test_previous_closed_worker_gate_cannot_freeze_new_game(tmp_path, mode):
    old = DecisionWorker()
    remote = BlockedRemote()
    now = time.monotonic()
    assert old.submit(remote, GameStateBuilder.build(World()), now, 1)
    assert remote.started.wait(1)
    old.close()
    game = Game(Settings(mode=mode, log_dir=tmp_path))
    try:
        game.tactical(now + 0.1, 1 / 60)
        assert game.session.metrics.summary()["total_decisions"] == 1
        assert game.session.decision.source == ("mock" if mode == "mock" else "fallback")
        assert old.busy and not game.worker.busy
    finally:
        remote.finish(old)
        game.worker.close()
        game.session.finish(game.world, "test")
        pygame.quit()


def test_timeout_records_one_error_not_duplicate_same_frame(tmp_path):
    remote = BlockedRemote()
    game = Game(Settings(mode="jev", timeout=0.01, log_dir=tmp_path))
    game.controllers["jev"] = remote
    now = time.monotonic()
    try:
        game.tactical(now, 1 / 60)
        assert remote.started.wait(1)
        game.tactical(now + 1, 1 / 60)
        stats = game.session.metrics.summary()
        assert stats["total_decisions"] == stats["api_errors"] == 1
        assert game.session.decision.error == "timeout"
        assert game.worker.busy
        game.tactical(now + 1.1, 1 / 60)
        assert game.session.metrics.summary()["total_decisions"] == 1
        game.tactical(now + 2, 1 / 60)
        assert game.session.metrics.summary()["total_decisions"] == 2
    finally:
        remote.finish(game.worker)
        game.session.finish(game.world, "test")
        pygame.quit()


def test_failed_one_shot_actions_never_report_success():
    world, executor = World(), ActionExecutor()
    world.player.ammo = world.player.reserve_ammo = 0
    first = executor.execute(world, Action.RELOAD, 1 / 60)
    second = executor.execute(world, Action.RELOAD, 1 / 60)
    assert first == second == "No reserve ammo: collect a box"
    executor.begin()
    world.player.medkits = 0
    world.player.hp = 20
    assert executor.execute(world, Action.HEAL, 1 / 60) == "No medkits"
    assert executor.execute(world, Action.HEAL, 1 / 60) == "No medkits"


def test_sdk_cleanup_exception_cannot_crash_game_exit(tmp_path):
    game = Game(Settings(log_dir=tmp_path))

    class BadCleanup:
        def close(self):
            raise RuntimeError("secret-value")

    game.controllers["jev"] = BadCleanup()
    report = game.run(max_seconds=0.02)
    assert report["survival_time"] > 0
    assert not pygame.get_init()
