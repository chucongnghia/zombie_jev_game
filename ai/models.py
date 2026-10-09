"""Validated, JSON-friendly decisions shared by every AI implementation."""

from dataclasses import dataclass, field
from enum import Enum
import math
from numbers import Real
from typing import Any


class Action(str, Enum):
    MOVE_AWAY = "MOVE_AWAY"
    MOVE_TO_MEDKIT = "MOVE_TO_MEDKIT"
    MOVE_TO_AMMO = "MOVE_TO_AMMO"
    SHOOT_NEAREST = "SHOOT_NEAREST"
    RELOAD = "RELOAD"
    HEAL = "HEAL"
    HOLD_POSITION = "HOLD_POSITION"


def _finite_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


@dataclass
class Decision:
    action: Action
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    source: str = "fallback"
    latency_ms: float | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> "Decision":
        """Reject malformed values; empty probabilities mean unavailable, not zero."""
        if not isinstance(self.action, Action):
            raise ValueError("action must be an Action")
        if self.confidence is not None and (
            not _finite_number(self.confidence) or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be finite and in [0, 1]")
        if not isinstance(self.probabilities, dict):
            raise ValueError("probabilities must be a dictionary")
        valid_keys = {action.value for action in Action}
        for key, probability in self.probabilities.items():
            if not isinstance(key, str) or key not in valid_keys:
                raise ValueError("invalid probability action key")
            if not _finite_number(probability) or not 0 <= probability <= 1:
                raise ValueError("probabilities must be finite and in [0, 1]")
        if self.probabilities and not math.isclose(
            sum(self.probabilities.values()), 1.0, rel_tol=0.0, abs_tol=0.02
        ):
            raise ValueError("nonempty probabilities must sum to one within 0.02 rounding tolerance")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a nonempty string")
        if self.latency_ms is not None and (
            not _finite_number(self.latency_ms) or self.latency_ms < 0
        ):
            raise ValueError("latency_ms must be finite and nonnegative")
        if self.error is not None and not isinstance(self.error, str):
            raise ValueError("error must be a string or None")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "action": self.action.value,
            "confidence": self.confidence,
            "probabilities": dict(self.probabilities),
            "source": self.source,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }
