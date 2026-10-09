"""Nonblocking decision execution with a process-wide single-request gate.

Timeouts do not cancel Python threads or remote calls. They deliver one local
fallback while retaining the gate until the physical controller call returns.
All timestamps supplied by the game must come from time.monotonic(), never its
paused or scaled simulation clock. close() is intentionally nonblocking.
"""

from copy import deepcopy
from dataclasses import dataclass
import math
import threading
import time

from .controller import AIController
from .fallback_controller import FallbackController
from .models import Decision


_PHYSICAL_REQUEST_GATE = threading.Lock()


@dataclass
class WorkerResult:
    decision: Decision
    state: dict
    generation: int


@dataclass
class _Request:
    state: dict
    generation: int
    submitted_at: float
    decision: Decision | None = None
    completed_at: float | None = None
    timed_out: bool = False


class DecisionWorker:
    def __init__(self, timeout: float = 5):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self.timeout = float(timeout)
        self._lock = threading.Lock()
        self._request: _Request | None = None
        self._closed = False
        self._fallback = FallbackController()

    @property
    def busy(self) -> bool:
        """Whether this worker still has a physically running request."""
        with self._lock:
            return self._request is not None and self._request.completed_at is None

    def submit(self, controller: AIController, state: dict, now: float, generation: int) -> bool:
        """Accept a detached snapshot, or reject while any worker is in flight."""
        if not math.isfinite(now):
            raise ValueError("now must be a finite monotonic timestamp")
        with self._lock:
            if self._closed or self._request is not None:
                return False
            if not _PHYSICAL_REQUEST_GATE.acquire(blocking=False):
                return False
            try:
                request = _Request(deepcopy(state), generation, now)
                controller_state = deepcopy(request.state)
                self._request = request
                thread = threading.Thread(
                    target=self._run,
                    args=(controller, request, controller_state),
                    name="zombie-ai-decision",
                    daemon=True,
                )
                thread.start()
            except BaseException:
                self._request = None
                _PHYSICAL_REQUEST_GATE.release()
                raise
        return True

    def _fallback_decision(self, state: dict, error: str, elapsed: float) -> Decision:
        decision = self._fallback.decide(state)
        decision.error = error
        decision.latency_ms = max(0.0, elapsed * 1000)
        return decision.validate()

    def _run(self, controller: AIController, request: _Request, state: dict) -> None:
        started = time.monotonic()
        try:
            try:
                candidate = controller.decide(state)
            except KeyError:
                decision = self._fallback_decision(request.state, "missing_key", time.monotonic() - started)
            except TimeoutError:
                decision = self._fallback_decision(request.state, "timeout", time.monotonic() - started)
            except PermissionError:
                decision = self._fallback_decision(request.state, "authentication_error", time.monotonic() - started)
            except ConnectionError:
                decision = self._fallback_decision(request.state, "network_error", time.monotonic() - started)
            except ValueError:
                decision = self._fallback_decision(request.state, "invalid_response", time.monotonic() - started)
            except BaseException:
                # Never include exception messages, request bodies or credentials.
                decision = self._fallback_decision(request.state, "controller_error", time.monotonic() - started)
            else:
                try:
                    if not isinstance(candidate, Decision):
                        raise ValueError("not a Decision")
                    decision = deepcopy(candidate).validate()
                    if decision.latency_ms is None:
                        decision.latency_ms = (time.monotonic() - started) * 1000
                except BaseException:
                    decision = self._fallback_decision(request.state, "malformed_decision", time.monotonic() - started)
        finally:
            with self._lock:
                request.completed_at = time.monotonic()
                # The physical call has ended even if its answer is no longer usable.
                _PHYSICAL_REQUEST_GATE.release()
                if self._closed or request.timed_out:
                    if self._request is request:
                        self._request = None
                else:
                    request.decision = decision

    def poll(self, now: float) -> WorkerResult | None:
        """Return a completion or one immediate timeout fallback; never block."""
        if not math.isfinite(now):
            raise ValueError("now must be a finite monotonic timestamp")
        with self._lock:
            request = self._request
            if request is None or self._closed or request.timed_out:
                return None
            deadline = request.submitted_at + self.timeout
            expired = (
                now >= deadline if request.completed_at is None
                else request.completed_at > deadline
            )
            if expired:
                request.timed_out = True
                decision = self._fallback_decision(request.state, "timeout", now - request.submitted_at)
                if request.completed_at is not None:
                    self._request = None
                return WorkerResult(decision, deepcopy(request.state), request.generation)
            if request.completed_at is not None:
                self._request = None
                return WorkerResult(request.decision, deepcopy(request.state), request.generation)
            return None

    def close(self) -> None:
        """Discard results without joining or releasing a still-running call."""
        with self._lock:
            self._closed = True
            if self._request is not None and self._request.completed_at is not None:
                self._request = None
