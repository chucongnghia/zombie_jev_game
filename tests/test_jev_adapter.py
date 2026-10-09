"""Offline adapter coverage: fake SDK plus real SDK on a mock HTTP transport."""

import json
import math
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ai.decision_definition import ACTION_CRITERIA, INSTRUCTIONS
from ai.jev_controller import JevController
from ai.models import Action


LABELS = list(ACTION_CRITERIA)
STATE = {"player": {"hp_percent": 30, "ammo": 0, "medkits": 1},
         "threat": {"nearest_zombie_distance": 190}}


def response(choice="HEAL", confidence=0.60):
    values = {label: 0.05 for label in LABELS}
    values[choice] = 0.70
    answer = SimpleNamespace(type="choice", choice=choice,
                             confidence=confidence, probabilities=values)
    return SimpleNamespace(choices={"action": answer})


class JevAdapterTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"TYPESAFE_API_KEY": "offline-test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = Mock()
        self.client.system_one.return_value = response()
        self.sdk = SimpleNamespace(TypeSafeClient=Mock(return_value=self.client),
                                   RetryPolicy=Mock(side_effect=lambda **kw: SimpleNamespace(**kw)),
                                   Choice=Mock(side_effect=lambda **kw: SimpleNamespace(type="choice", **kw)))
        self.loader = patch("ai.jev_controller.importlib.import_module", return_value=self.sdk)
        self.load = self.loader.start()
        self.addCleanup(self.loader.stop)

    def test_definition_exactly_matches_enum(self):
        self.assertEqual(set(ACTION_CRITERIA), {action.value for action in Action})
        self.assertTrue(all(isinstance(value, str) and value for value in ACTION_CRITERIA.values()))
        self.assertIn("single best immediate action", INSTRUCTIONS)

    def test_lazy_construction_request_and_preserved_confidence(self):
        controller = JevController(timeout=1.25, model="jev-1.13.0")
        self.load.assert_not_called()
        result = controller.decide(STATE)
        self.assertEqual(result.action, Action.HEAL)
        self.assertEqual(result.confidence, 0.60)
        self.assertEqual(result.probabilities["HEAL"], 0.70)
        self.assertNotEqual(result.confidence, result.probabilities["HEAL"])
        self.assertEqual(result.source, "jev")
        self.assertGreaterEqual(result.latency_ms, 0)
        self.assertIsNone(result.error)
        self.sdk.TypeSafeClient.assert_called_once()
        options = self.sdk.TypeSafeClient.call_args.kwargs
        self.assertEqual(options["api_key"], "offline-test-key")
        self.assertEqual(options["model"], "jev-1.13.0")
        self.assertEqual(options["timeout"], 1.25)
        self.assertEqual(options["retry"].max_retries, 0)
        call = self.client.system_one.call_args.kwargs
        self.assertIs(call["state"], STATE)
        self.assertEqual(set(call["questions"]), {"action"})
        self.assertEqual(call["questions"]["action"].criteria, ACTION_CRITERIA)
        controller.decide(STATE)
        self.sdk.TypeSafeClient.assert_called_once()
        controller.close()
        controller.close()
        self.client.close.assert_called_once()

    def test_missing_key_is_lazy_and_does_not_import_sdk(self):
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "  "}):
            controller = JevController()
            with self.assertRaisesRegex(KeyError, "TYPESAFE_API_KEY"):
                controller.decide(STATE)
        self.load.assert_not_called()

    def test_missing_sdk_has_install_hint(self):
        self.load.side_effect = ImportError("private details")
        with self.assertRaisesRegex(RuntimeError, "typesafe-sdk==0.7.2") as caught:
            JevController().decide(STATE)
        self.assertNotIn("private", str(caught.exception))

    def test_invalid_settings_and_state(self):
        for timeout in (0, -1, math.inf, math.nan, True, "5"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                JevController(timeout=timeout)
        for model in ("", " ", None):
            with self.subTest(model=model), self.assertRaises(ValueError):
                JevController(model=model)
        for state in ([], {"x": math.nan}, {"x": object()}):
            with self.subTest(state=type(state)), self.assertRaises(ValueError):
                JevController().decide(state)
        self.load.assert_not_called()

    def test_rounding_drift_is_preserved_not_fabricated(self):
        value = response()
        value.choices["action"].probabilities["HEAL"] = 0.695
        self.client.system_one.return_value = value
        result = JevController().decide(STATE)
        self.assertAlmostEqual(sum(result.probabilities.values()), 0.995)
        self.assertEqual(result.probabilities, value.choices["action"].probabilities)
        self.assertEqual(result.confidence, 0.60)
        self.assertEqual(set(result.probabilities), set(LABELS))

    def test_malformed_responses_rejected(self):
        mutations = [
            lambda value: value.choices.clear(),
            lambda value: setattr(value.choices["action"], "type", "noul"),
            lambda value: setattr(value.choices["action"], "choice", "FLY"),
            lambda value: setattr(value.choices["action"], "choice", "RELOAD"),
            lambda value: value.choices["action"].probabilities.pop("RELOAD"),
            lambda value: value.choices["action"].probabilities.update(FLY=0.0),
            lambda value: value.choices["action"].probabilities.update(HEAL=math.nan),
            lambda value: value.choices["action"].probabilities.update(HEAL=math.inf),
            lambda value: value.choices["action"].probabilities.update(HEAL=-0.1),
            lambda value: value.choices["action"].probabilities.update(HEAL=1.1),
            lambda value: value.choices["action"].probabilities.update(HEAL=True),
            lambda value: value.choices["action"].probabilities.update(HEAL="0.7"),
            lambda value: value.choices["action"].probabilities.update(HEAL=0.1),
            lambda value: setattr(value.choices["action"], "confidence", math.nan),
            lambda value: setattr(value.choices["action"], "confidence", True),
            lambda value: setattr(value.choices["action"], "confidence", 1.1),
            lambda value: delattr(value.choices["action"], "confidence"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                value = response()
                mutate(value)
                self.client.system_one.return_value = value
                with self.assertRaisesRegex(ValueError, "invalid seven-action"):
                    JevController().decide(STATE)

    def test_api_errors_are_sanitized(self):
        cases = [("TypeSafeAPIError", 401, PermissionError),
                 ("TypeSafeAPIError", 403, PermissionError),
                 ("TypeSafeAPITimeoutError", None, TimeoutError),
                 ("TypeSafeAPIConnectionError", None, ConnectionError),
                 ("TypeSafeAPIResponseValidationError", None, ValueError),
                 ("TypeSafeAPIError", 429, RuntimeError),
                 ("TypeSafeError", None, RuntimeError),
                 ("UnexpectedError", None, RuntimeError)]
        for name, status, expected in cases:
            with self.subTest(name=name, status=status):
                error = type(name, (Exception,), {})("secret-key-in-upstream-body")
                error.status = status
                self.client.system_one.side_effect = error
                with self.assertRaises(expected) as caught:
                    JevController().decide(STATE)
                self.assertNotIn("secret-key", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    def test_construction_and_close_errors_are_sanitized(self):
        self.sdk.TypeSafeClient.side_effect = ValueError("secret-key")
        with self.assertRaisesRegex(RuntimeError, "Jev request failed"):
            JevController().decide(STATE)
        self.sdk.TypeSafeClient.side_effect = None
        controller = JevController()
        controller.decide(STATE)
        self.client.close.side_effect = RuntimeError("secret-key")
        with self.assertRaisesRegex(RuntimeError, "cleanup failed") as caught:
            controller.close()
        self.assertNotIn("secret-key", str(caught.exception))
        controller.close()


class RealSDKOfflineTests(unittest.TestCase):
    def test_official_sdk_request_and_response_without_network(self):
        try:
            import httpx2
            import typesafe_sdk
        except ImportError:
            self.skipTest("optional typesafe-sdk is not installed")
        captured = []

        def handler(request):
            captured.append(request)
            answer = response().choices["action"]
            return httpx2.Response(200, json={
                "model": "jev-1.13.0", "answers": {"action": vars(answer)},
                "usage": {"input_tokens": 120, "output_tokens": 12},
            })

        actual_client = typesafe_sdk.TypeSafeClient

        def factory(**kwargs):
            return actual_client(**kwargs, base_url="https://api.typesafe.ai",
                                 transport=httpx2.MockTransport(handler))

        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "offline-test-key"}), \
             patch.object(typesafe_sdk, "TypeSafeClient", side_effect=factory):
            controller = JevController(timeout=0.5)
            try:
                result = controller.decide(STATE)
            finally:
                controller.close()
        self.assertEqual(result.action, Action.HEAL)
        self.assertEqual(result.confidence, 0.6)
        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(str(request.url), "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(request.headers["Authorization"], "Bearer offline-test-key")
        body = json.loads(request.content)
        self.assertEqual(body["state"], STATE)
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["questions"]["action"]["type"], "choice")
        self.assertEqual(body["questions"]["action"]["criteria"], ACTION_CRITERIA)
        self.assertEqual(request.extensions["timeout"]["read"], 0.5)


if __name__ == "__main__":
    unittest.main()
