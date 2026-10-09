"""Physics, tactical execution, logs, benchmark and rendered-mode regression tests."""
import json
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame
import pytest
from ai.models import Action, Decision
from ai.state_builder import GameStateBuilder
from game import config as C
from game.world import World
from game.entities.zombie import Zombie
from game.entities.pickup import Pickup, Bullet
from game.systems.action_executor import ActionExecutor
from game.systems.collision import is_free, move_circle
from game.systems.combat import shoot
from game.session import Session


def step(world, seconds):
    for _ in range(round(seconds * 60)):
        world.tick(1 / 60)


def test_combat_reload_heal_and_waves():
    world = World()
    world.zombies.append(Zombie(pygame.Vector2(560, 350)))
    assert shoot(world, world.zombies[0].pos).startswith("Fired")
    step(world, 0.4)
    shoot(world, world.zombies[0].pos)
    step(world, 0.4)
    assert world.kills == 1 and world.score == 100
    world.player.ammo = 0
    reserve = world.player.reserve_ammo
    world.player.reload()
    assert world.player.ammo == 0
    step(world, 1.1)
    assert world.player.ammo == 10 and world.player.reserve_ammo == reserve - 10
    world.player.hp = 35
    assert world.player.heal() == "Healed +40 HP"
    assert world.player.hp == 75 and world.player.medkits == 0
    world.survival_time = 26
    world.tick(1 / 60)
    assert world.wave == 2 and world.zombies


def test_zombie_attack_is_rate_limited_and_can_kill():
    world = World()
    world.zombies.append(Zombie(world.player.pos.copy()))
    world.tick(1 / 60)
    assert world.player.hp == 90
    world.tick(1 / 60)
    assert world.player.hp == 90
    world.player.hp = 10
    step(world, 1)
    assert not world.alive
    survived = world.survival_time
    world.tick(1)
    assert world.survival_time == survived


def test_movement_and_all_action_executions():
    world = World()
    executor = ActionExecutor()
    world.zombies.append(Zombie(pygame.Vector2(560, 350)))
    old_distance = world.nearest_zombie().distance_to_player(world.player)
    executor.execute(world, Action.MOVE_AWAY, 0.1)
    assert world.nearest_zombie().distance_to_player(world.player) > old_distance
    for action, kind in [(Action.MOVE_TO_AMMO, "ammo"), (Action.MOVE_TO_MEDKIT, "medkit")]:
        old_distance = world.nearest_pickup(kind).pos.distance_to(world.player.pos)
        executor.execute(world, action, 0.1)
        assert world.nearest_pickup(kind).pos.distance_to(world.player.pos) < old_distance
    assert executor.execute(world, Action.SHOOT_NEAREST, 0.01).startswith("Fired")
    executor.begin()
    executor.execute(world, Action.RELOAD, 0.01)
    assert world.player.reload_remaining > 0
    world.player.hp = 20
    world.player.medkits = 3
    executor.begin()
    executor.execute(world, Action.HEAL, 0.01)
    executor.execute(world, Action.HEAL, 1)
    assert world.player.medkits == 2  # HEAL is one-shot per tactical decision.
    old = world.player.pos.copy()
    executor.execute(world, Action.HOLD_POSITION, 0.1)
    assert world.player.pos == old


def test_wall_collision_and_bullet_occlusion():
    world = World()
    world.walls = [pygame.Rect(530, 320, 20, 60)]
    world.zombies.append(Zombie(pygame.Vector2(580, 350), speed=0))
    shoot(world, world.zombies[0].pos)
    step(world, 0.4)
    assert world.zombies[0].hp == 30
    assert not world.bullets
    pos = pygame.Vector2(515, 350)
    moved = move_circle(pos, pygame.Vector2(1, 0), 100, 0.1, C.PLAYER_RADIUS, world.walls)
    assert is_free(moved, C.PLAYER_RADIUS, world.walls)
    assert not is_free(pygame.Vector2(535, 350), C.PLAYER_RADIUS, world.walls)


def test_bullet_cannot_hit_beyond_remaining_range():
    from game.systems.combat import tick_bullets
    world = World()
    world.walls = []
    world.player.pos = pygame.Vector2(100, 350)
    world.zombies = [Zombie(pygame.Vector2(726, 350), speed=0)]
    shoot(world, world.zombies[0].pos)
    for _ in range(20):
        tick_bullets(world, 0.05)
    assert world.hits == 0 and world.zombies[0].hp == 30
    assert not world.bullets


def test_bullet_hits_nearest_intersection_not_list_order():
    world = World()
    farther = Zombie(pygame.Vector2(545, 350), speed=0)
    nearer = Zombie(pygame.Vector2(520, 350), speed=0)
    world.zombies = [farther, nearer]
    world.bullets.append(Bullet(world.player.pos.copy(), pygame.Vector2(650, 0), 600))
    world.tick(0.1)
    assert nearer.hp == 10 and farther.hp == 30


@pytest.mark.parametrize("start,target", [((500, 200), (700, 200)), ((500, 350), (800, 180))])
def test_navigator_collects_reachable_pickup_behind_wall(start, target):
    world = World()
    world.player.pos = pygame.Vector2(start)
    world.pickups = [Pickup(pygame.Vector2(target), "ammo")]
    executor = ActionExecutor()
    for _ in range(900):
        executor.execute(world, Action.MOVE_TO_AMMO, 1 / 60)
        # Disable spawning to isolate navigation from hostile interactions.
        world.spawner.spawn_remaining = world.spawner.resource_remaining = 100
        world.tick(1 / 60)
        if not world.pickups:
            break
    assert world.collected == 1


def test_pickups_and_empty_reserve():
    world = World()
    world.pickups = [Pickup(world.player.pos.copy(), "ammo"), Pickup(world.player.pos.copy(), "medkit")]
    reserve, medkits = world.player.reserve_ammo, world.player.medkits
    world.tick(1 / 60)
    assert world.player.reserve_ammo == reserve + 20
    assert world.player.medkits == medkits + 1
    assert world.collected == 2 and not world.pickups
    world.player.ammo = world.player.reserve_ammo = 0
    assert world.player.reload().startswith("No reserve")
    assert world.player.reload_remaining == 0


def test_jsonl_includes_state_decision_and_action_outcome(tmp_path):
    world = World()
    session = Session("mock", tmp_path)
    state = GameStateBuilder().build(world)
    session.record(Decision(Action.MOVE_TO_AMMO, 0.7, {Action.MOVE_TO_AMMO.value: 1}, "mock", 2), state, world)
    ActionExecutor().execute(world, Action.MOVE_TO_AMMO, 0.1)
    world.tick(0.1)
    session.finish(world, "test")
    record = json.loads((tmp_path / "decisions.jsonl").read_text())
    assert record["state"] == state and record["action"] == "MOVE_TO_AMMO"
    assert record["outcome"]["distance_moved"] > 0
    assert record["source"] == "mock" and record["run_id"]
    assert json.loads((tmp_path / "runs.jsonl").read_text())["total_decisions"] == 1


def test_benchmark_fast_and_deterministic(tmp_path):
    from game.benchmark import benchmark
    settings = C.Settings(log_dir=tmp_path)
    first = benchmark(settings, ["mock", "fallback"], 1, 10)
    second = benchmark(settings, ["mock", "fallback"], 1, 10)
    for mode in first:
        assert first[mode]["average_survival_time"] == second[mode]["average_survival_time"]
        assert first[mode]["average_kills"] == second[mode]["average_kills"]
        assert first[mode]["runs"][0]["total_decisions"] > 0
    assert (tmp_path / "benchmark.json").exists()


def test_rendered_game_mock_missing_key_modes_restart(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    from game.game import Game
    game = Game(C.Settings(log_dir=tmp_path))
    report = game.run(max_seconds=0.08, screenshot=tmp_path / "mock.png")
    assert report["total_decisions"] >= 1
    assert (tmp_path / "mock.png").stat().st_size > 1000
    game = Game(C.Settings(mode="jev", log_dir=tmp_path))
    report = game.run(max_seconds=0.08)
    assert report["fallback_count"] >= 1 and report["api_errors"] >= 1
    game = Game(C.Settings(log_dir=tmp_path))
    try:
        game.change_mode("manual")
        assert game.session.mode == "manual"
        game.change_mode("mock")
        old_generation = game.generation
        game.world.player.hp = 0
        game.renderer.draw(game.world, game.session)
        game.restart()
        assert game.world.alive and game.generation > old_generation
        game.renderer.show_state = True
        game.session.last_state = GameStateBuilder().build(game.world)
        game.renderer.draw(game.world, game.session)
    finally:
        game.worker.close()
        game.session.finish(game.world, "test")
        pygame.quit()


@pytest.mark.parametrize("transition", ["mode_switch", "restart"])
def test_stale_pending_network_never_freezes_new_mode_or_run(tmp_path, transition):
    import threading
    import time
    from game.game import Game
    started, release = threading.Event(), threading.Event()

    class BlockedRemote:
        def decide(self, state):
            started.set()
            release.wait(2)
            return Decision(Action.SHOOT_NEAREST, None, {}, "jev", 1)

    game = Game(C.Settings(mode="jev", timeout=0.01, log_dir=tmp_path))
    game.controllers["jev"] = BlockedRemote()
    now = time.monotonic()
    try:
        game.tactical(now, 1 / 60)
        assert started.wait(1)
        if transition == "mode_switch":
            game.change_mode("mock")
        else:
            game.restart()
        game.tactical(now + 0.02, 1 / 60)
        assert game.worker.busy
        assert game.session.metrics.summary()["total_decisions"] == 1
        assert game.session.decision.source == ("mock" if transition == "mode_switch" else "fallback")
        game.tactical(now + 1, 1 / 60)
        assert game.session.metrics.summary()["total_decisions"] == 2
        assert game.worker.busy
    finally:
        release.set()
        deadline = time.monotonic() + 1
        while game.worker.busy and time.monotonic() < deadline:
            threading.Event().wait(0.001)
        game.worker.close()
        game.session.finish(game.world, "test")
        pygame.quit()
