"""Offline mock: all confidence/probability values are explicitly synthetic.

These heuristic weights are demonstration data, never Jev measurements.
"""

import random
import threading

from .fallback_controller import _heuristic_action
from .models import Action, Decision


class MockJevController:
    """Seeded synthetic distribution with a local safety heuristic as its mode."""

    def __init__(self, seed: int = 0):
        self._random = random.Random(seed)
        self._lock = threading.Lock()

    def decide(self, state: dict) -> Decision:
        # Missing contract fields are deliberately not silently fabricated.
        required = {
            "player": ("hp_percent", "ammo", "max_ammo", "reserve_ammo", "medkits", "weapon_ready", "reloading"),
            "threat": ("zombie_count", "nearest_zombie_distance", "zombies_within_100", "zombies_within_200"),
            "resources": ("nearest_medkit_distance", "nearest_ammo_distance"),
            "context": ("survival_time", "kills", "wave"),
        }
        for section, keys in required.items():
            for key in keys:
                state[section][key]
        preferred = _heuristic_action(state)
        with self._lock:
            weights = {action.value: self._random.uniform(0.05, 0.15) for action in Action}
            weights[preferred.value] += 1.0
        total = sum(weights.values())
        probabilities = {key: weight / total for key, weight in weights.items()}
        return Decision(
            action=preferred,
            confidence=probabilities[preferred.value],
            probabilities=probabilities,
            source="mock",
            latency_ms=None,
        )
