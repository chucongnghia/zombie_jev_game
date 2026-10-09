# Verification — Jev Zombie Survival

Verified in this workspace on 2026-10-09, Python 3.14.7, pygame-ce 2.5.8, typesafe-sdk 0.7.2.

## Final automated checks

```text
.venv/bin/python -m pytest -q
92 passed, 37 subtests passed in 1.32s

.venv/bin/python -m compileall -q main.py ai game tests scripts
exit 0

.venv/bin/python -m pip check
No broken requirements found.
```

Tests cover compact JSON state, all seven actions, validation, synthetic mock distribution, heuristic fallback, timeout/deepcopy/single-flight/late results, actual SDK request and parsing on MockTransport, combat, walls, ammo reserve, healing, pickups, waves, JSONL outcomes, manual/mock/Jev switching, restart, cross-session pending network requests, no duplicate timeout records, cleanup failure and reachable wall-corner navigation.

Independent read-only review found and verified fixes for stale-response gate freezing a restarted/new game, stateless wall steering oscillation, same-frame duplicate timeout records, one-shot actions falsely reporting success, missing game-over confidence values and bullet range overshoot. Final reviewer rerun: 92 passed, 37 subtests passed; no outstanding findings from reviewed scope.

## Executed game demos

- [Mock run](mock-run.txt): 12.027 simulation seconds, 3 kills, 16 decisions, 0 API errors. [Screenshot](mock-demo.png).
- [Jev mode without a key](jev-no-key-run.txt): 3.016 seconds, 4 fallback decisions, 4 missing_key errors, exited successfully without crash or fabricated confidence.
- [Full offline run](capture-run.txt): 88.567 seconds survival, 38 kills, wave 4, 116 decisions, 0 errors. [Game Over](end-run.png), [state viewer](state-viewer.png).
- [Final benchmark output](benchmark-run.txt): three seeds 7/8/9 per local mode, 120s cap. Mock and fallback each averaged 81.011s survival and 31.667 kills. No run reached the cap. Same gameplay is expected: mock uses the same heuristic and only its synthetic distribution varies.

The full offline screenshot run and benchmark are fixed-step simulations, not real-time rendering performance measurements.

## Jev integration evidence and limitation

Official SDK source tag v0.7.2 and docs were verified before adapter implementation:
[SDK](https://docs.typesafe.ai/sdk/python), [API](https://docs.typesafe.ai/api), [models](https://docs.typesafe.ai/models), [confidence](https://docs.typesafe.ai/confidence), [tagged source](https://github.com/typesafe-ai/typesafe-sdk-python/tree/v0.7.2).

Adapter tests use installed SDK + `httpx2.MockTransport` and assert the precise endpoint, Bearer auth with an offline dummy key, seven-choice JSON request and typed response parsing. API probabilities and confidence are preserved unchanged. These tests do not send network requests.

A **real Jev tool call** through Harness was made during implementation, model `jev-1.13.0` (alias `jev-latest`), on a game state with HP 20%, ammo 0, reserve 20, medkits 1, nearest enemy 190px. Result:

```json
{
  "action": "HEAL",
  "confidence": 0.600,
  "probabilities": {
    "HEAL": 0.660,
    "MOVE_AWAY": 0.170,
    "RELOAD": 0.100,
    "SHOOT_NEAREST": 0.060,
    "MOVE_TO_AMMO": 0.010,
    "MOVE_TO_MEDKIT": 0.000,
    "HOLD_POSITION": 0.000
  }
}
```

This is a tool-call sample, not a Python gameplay run. **No authenticated Python Jev gameplay run was possible because TYPESAFE_API_KEY was absent.** Add your own key to `.env` to test live game control. No generated/mock probabilities are labelled as Jev outputs.
