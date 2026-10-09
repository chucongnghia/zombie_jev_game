"""One recorder API for live sessions and offline benchmarks."""

from collections import Counter
from copy import deepcopy
from statistics import fmean

from .models import Decision


class AIMetrics:
    """Record validated decisions; separate real Jev from synthetic mock data."""

    def __init__(self):
        self._decisions: list[dict] = []

    def record(self, decision: Decision) -> None:
        self._decisions.append(deepcopy(decision.to_dict()))

    def summary(self) -> dict:
        decisions = self._decisions
        total = len(decisions)
        jev = [decision for decision in decisions if decision["source"] == "jev"]
        confident = [decision for decision in decisions if decision["confidence"] is not None]
        latencies = [decision["latency_ms"] for decision in jev if decision["latency_ms"] is not None]
        fallback_count = sum(decision["source"] == "fallback" for decision in decisions)
        counts = Counter(decision["action"] for decision in decisions)
        highest = max(confident, key=lambda decision: decision["confidence"], default=None)
        lowest = min(confident, key=lambda decision: decision["confidence"], default=None)
        return {
            "total_decisions": total,
            "jev_decisions": len(jev),
            "average_confidence": fmean(decision["confidence"] for decision in confident) if confident else None,
            "average_jev_latency": fmean(latencies) if latencies else None,
            "api_errors": sum(decision["error"] is not None for decision in decisions),
            "fallback_count": fallback_count,
            "fallback_rate": fallback_count / total if total else 0.0,
            "most_used_action": counts.most_common(1)[0][0] if counts else None,
            "highest_confidence_action": (
                {"action": highest["action"], "confidence": highest["confidence"], "source": highest["source"]}
                if highest else None
            ),
            "lowest_confidence_decision": deepcopy(lowest),
        }


# Friendly alias for callers that name their benchmark recorder generically.
Metrics = AIMetrics
