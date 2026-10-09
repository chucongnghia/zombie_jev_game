"""Controller contract, independent of Pygame and any remote adapter."""

from typing import Protocol, runtime_checkable

from .models import Decision


@runtime_checkable
class AIController(Protocol):
    def decide(self, state: dict) -> Decision:
        """Choose one action from a detached, JSON-serializable game state."""
        ...
