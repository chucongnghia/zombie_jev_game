"""Run-local decisions, metrics, outcome accounting and JSONL persistence."""
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4
from ai.models import Action, Decision
from ai.metrics import AIMetrics


class Session:
    def __init__(self, mode: str, log_dir: Path):
        self.mode = mode
        self.run_id = uuid4().hex[:12]
        self.metrics = AIMetrics()
        self.decision = Decision(Action.HOLD_POSITION, None, {}, "waiting", None)
        self.last_state = {}
        self.history = deque(maxlen=8)
        self.last_outcome = "Waiting for decision"
        self.pending_record = None
        self.finished = False
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = log_dir
        self.stream = (log_dir / "decisions.jsonl").open("a", encoding="utf-8", buffering=1)

    @staticmethod
    def snapshot(world):
        return {"hp": world.player.hp, "ammo": world.player.ammo,
                "reserve_ammo": world.player.reserve_ammo, "medkits": world.player.medkits,
                "kills": world.kills, "shots": world.shots, "hits": world.hits,
                "collected": world.collected, "position": list(world.player.pos)}

    def finalize_action(self, world):
        if self.pending_record is None:
            return
        record, before = self.pending_record
        after = self.snapshot(world)
        outcome = {f"{key}_delta": after[key] - before[key] for key in before if key != "position"}
        outcome["distance_moved"] = round(world.player.pos.distance_to(before["position"]), 1)
        outcome["duration"] = round(world.survival_time - record["timestamp"], 3)
        outcome["last_effect"] = world.last_effect
        record["outcome"] = outcome
        self.stream.write(json.dumps(record, allow_nan=False) + "\n")
        self.last_outcome = (f"{record['action']}: HP {outcome['hp_delta']:+d}, "
                             f"kills {outcome['kills_delta']:+d}, moved {outcome['distance_moved']:.0f}px")
        self.pending_record = None

    def record(self, decision, state, world, decision_state=None):
        self.finalize_action(world)
        self.decision = decision
        self.last_state = state
        self.metrics.record(decision)
        record = {"run_id": self.run_id, "timestamp": round(world.survival_time, 3),
                  "mode": self.mode, "state": state, **decision.to_dict()}
        if decision_state is not None:
            record["fallback_state"] = decision_state
        self.history.appendleft(record)
        self.pending_record = (record, self.snapshot(world))

    def summary(self, world):
        return {"run_id": self.run_id, "mode": self.mode, "survival_time": round(world.survival_time, 3),
                "kills": world.kills, "score": world.score, "wave": world.wave,
                **self.metrics.summary()}

    def finish(self, world, reason="game_over"):
        if self.finished:
            return
        self.finalize_action(world)
        report = self.summary(world)
        report["reason"] = reason
        report["utc_time"] = datetime.now(timezone.utc).isoformat()
        with (self.log_dir / "runs.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(report, allow_nan=False) + "\n")
        self.stream.close()
        self.finished = True
