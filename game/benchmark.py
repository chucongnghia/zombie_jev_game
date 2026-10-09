"""Fast fixed-step offline comparison; live Jev uses real-time paced worker calls."""
import json
import time
from statistics import fmean
from game.config import Settings, ROOT
from game.world import World
from game.session import Session
from game.systems.action_executor import ActionExecutor
from ai.state_builder import GameStateBuilder
from ai.mock_jev import MockJevController
from ai.fallback_controller import FallbackController


def benchmark(settings: Settings, modes: list[str], runs: int, seconds: float) -> dict:
    summaries = {}
    for mode in modes:
        reports = []
        for index in range(runs):
            seed = settings.seed + index
            if mode == "jev":
                # Same real-time scheduler as interactive play; fast sim would distort latency.
                from dataclasses import replace
                from game.game import Game
                report = Game(replace(settings, mode=mode, seed=seed)).run(max_seconds=seconds)
                report["time_limit_reached"] = report["survival_time"] >= seconds - 0.1
            else:
                world = World(seed)
                controller = MockJevController(seed) if mode == "mock" else FallbackController()
                session = Session(mode, settings.log_dir)
                builder = GameStateBuilder()
                executor = ActionExecutor()
                next_decision = 0.0
                while world.alive and world.survival_time < seconds:
                    if world.survival_time >= next_decision:
                        state = builder.build(world)
                        start = time.monotonic()
                        decision = controller.decide(state)
                        decision.latency_ms = (time.monotonic() - start) * 1000
                        session.record(decision, state, world)
                        executor.begin()
                        next_decision = world.survival_time + settings.decision_interval
                    world.last_effect = executor.execute(world, session.decision.action, 1 / 60)
                    world.tick(1 / 60)
                session.finish(world, "time_limit" if world.alive else "game_over")
                report = session.summary(world)
                report["time_limit_reached"] = world.alive
            reports.append(report)
        confidence = [r["average_confidence"] for r in reports if r["average_confidence"] is not None]
        latency = [r["average_jev_latency"] for r in reports if r["average_jev_latency"] is not None]
        summaries[mode] = {"runs": reports, "average_survival_time": fmean(r["survival_time"] for r in reports),
                           "average_kills": fmean(r["kills"] for r in reports),
                           "average_confidence": fmean(confidence) if confidence else None,
                           "average_jev_latency": fmean(latency) if latency else None,
                           "fallback_rate": fmean(r["fallback_rate"] for r in reports),
                           "time_limited_runs": sum(r["time_limit_reached"] for r in reports)}
    target = settings.log_dir / "benchmark.json"
    target.write_text(json.dumps(summaries, indent=2, allow_nan=False), encoding="utf-8")
    return summaries
