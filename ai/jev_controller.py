"""Official TypeSafe SDK adapter; call only from the decision worker.

SDK 0.7.2: POST https://api.typesafe.ai/v1/systemone, not a chat endpoint.
HTTP timeout is per operation, not a hard overall deadline. Retries are disabled.
The Choice confidence is kept exactly; it is NOT the selected probability.
"""

import importlib
import json
import math
from collections.abc import Mapping
from numbers import Real
import os
import time

from .decision_definition import ACTION_CRITERIA, INSTRUCTIONS
from .models import Action, Decision


class JevController:
    def __init__(self, timeout: float = 5.0, model: str = "jev-latest") -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, Real) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Jev HTTP timeout must be positive finite seconds")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Jev model must be a nonempty string")
        self.timeout = float(timeout)
        self.model = model.strip()
        self._client = None
        self._sdk = None

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        key = os.getenv("TYPESAFE_API_KEY", "").strip()
        if not key:
            raise KeyError("TYPESAFE_API_KEY is required for Jev")
        try:
            sdk = importlib.import_module("typesafe_sdk")
        except ImportError:
            raise RuntimeError("Jev SDK unavailable: install typesafe-sdk==0.7.2") from None
        self._sdk = sdk
        try:
            self._client = sdk.TypeSafeClient(
                api_key=key,
                model=self.model,
                timeout=self.timeout,
                retry=sdk.RetryPolicy(max_retries=0),
            )
        except Exception as error:
            self._raise_safe(error)

    @staticmethod
    def _raise_safe(error: Exception) -> None:
        """Discard upstream messages and chaining: either may contain credentials."""
        name = type(error).__name__
        if name == "TypeSafeAPITimeoutError" or isinstance(error, TimeoutError):
            raise TimeoutError("Jev request timed out") from None
        if getattr(error, "status", None) in (401, 403):
            raise PermissionError("Jev authentication failed; check TYPESAFE_API_KEY") from None
        if name == "TypeSafeAPIResponseValidationError":
            raise ValueError("Jev returned an invalid response") from None
        if name == "TypeSafeAPIConnectionError":
            raise ConnectionError("Jev service connection failed") from None
        if name == "TypeSafeAPIError":
            raise RuntimeError("Jev service returned an API error") from None
        if name == "TypeSafeError":
            raise RuntimeError("Jev SDK configuration or request is invalid") from None
        raise RuntimeError("Jev request failed") from None

    def decide(self, state: dict) -> Decision:
        if not isinstance(state, dict):
            raise ValueError("Jev state must be a JSON object")
        try:
            json.dumps(state, allow_nan=False)
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise ValueError("Jev state must contain finite JSON-compatible values") from None
        started = time.perf_counter()
        self._ensure_client()
        try:
            question = self._sdk.Choice(instructions=INSTRUCTIONS, criteria=dict(ACTION_CRITERIA))
            response = self._client.system_one(state=state, questions={"action": question})
        except Exception as error:
            self._raise_safe(error)
        try:
            return self._parse(response, (time.perf_counter() - started) * 1000)
        except Exception:
            raise ValueError("Jev returned an invalid seven-action Choice response") from None

    @staticmethod
    def _parse(response, latency_ms: float) -> Decision:
        answers = response.choices
        if not isinstance(answers, Mapping) or "action" not in answers:
            raise ValueError("missing action answer")
        answer = answers["action"]
        if answer.type != "choice":
            raise ValueError("wrong answer type")
        choice = answer.choice
        if not isinstance(choice, str) or choice not in ACTION_CRITERIA:
            raise ValueError("unknown action")
        confidence = answer.confidence
        if isinstance(confidence, bool) or not isinstance(confidence, Real) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("invalid confidence")
        raw = answer.probabilities
        if not isinstance(raw, Mapping) or set(raw) != set(ACTION_CRITERIA):
            raise ValueError("probabilities must include exactly the seven actions")
        probabilities = {}
        for label, value in raw.items():
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("invalid probability")
            probabilities[label] = float(value)
        total = math.fsum(probabilities.values())
        if not math.isclose(total, 1.0, rel_tol=0, abs_tol=0.02):
            raise ValueError("unnormalized distribution")
        if probabilities[choice] + 1e-9 < max(probabilities.values()):
            raise ValueError("choice is not a highest-probability option")
        # Keep API probabilities unchanged, including acceptable rounding drift.
        # Never synthesize missing values or substitute top probability for confidence.
        return Decision(
            action=Action(choice), confidence=float(confidence),
            probabilities=probabilities, source="jev", latency_ms=latency_ms,
        )

    def close(self) -> None:
        """Release the official SDK's reusable HTTP client after the worker stops."""
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:
                raise RuntimeError("Jev client cleanup failed") from None
