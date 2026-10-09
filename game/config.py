"""Gameplay constants and environment-backed runtime settings."""
from dataclasses import dataclass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FPS = 60
GAME_WIDTH = 1000
GAME_HEIGHT = 700
HEADER_HEIGHT = 60
DEBUG_PANEL_WIDTH = 360
SCREEN_WIDTH = GAME_WIDTH + DEBUG_PANEL_WIDTH
SCREEN_HEIGHT = GAME_HEIGHT + HEADER_HEIGHT
PLAYER_SPEED = 175.0
PLAYER_RADIUS = 13
PLAYER_HP = 100
MAGAZINE_SIZE = 10
START_RESERVE = 40
START_MEDKITS = 1
ZOMBIE_RADIUS = 13
ZOMBIE_HP = 30
ZOMBIE_DAMAGE = 10
ZOMBIE_SPEED = 57.0
ZOMBIE_ATTACK_INTERVAL = 0.85
BULLET_SPEED = 650.0
WEAPON_DAMAGE = 20
WEAPON_COOLDOWN = 0.28
WEAPON_RANGE = 600.0
RELOAD_SECONDS = 1.05
HEAL_AMOUNT = 40
HEAL_COOLDOWN = 0.9
WAVE_SECONDS = 25.0
RESOURCE_INTERVAL = 8.0
MAX_ZOMBIES = 90
MAX_PICKUPS = 16
JEV_DECISION_INTERVAL = 0.75
JEV_TIMEOUT = 5.0

@dataclass(frozen=True)
class Settings:
    mode: str = "mock"
    decision_interval: float = JEV_DECISION_INTERVAL
    timeout: float = JEV_TIMEOUT
    model: str = "jev-latest"
    log_dir: Path = ROOT / "logs"
    seed: int = 7

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("AI_MODE", "mock").lower()
        if mode not in {"mock", "jev", "manual", "fallback"}:
            raise ValueError("AI_MODE must be mock, jev, manual or fallback")
        interval = float(os.getenv("JEV_DECISION_INTERVAL", str(JEV_DECISION_INTERVAL)))
        timeout = float(os.getenv("JEV_TIMEOUT", str(JEV_TIMEOUT)))
        import math
        if not math.isfinite(interval) or not math.isfinite(timeout) or interval < 0.1 or timeout <= 0:
            raise ValueError("Decision interval must be >= 0.1 and timeout must be positive finite seconds")
        return cls(mode, interval, timeout, os.getenv("JEV_MODEL", "jev-latest"),
                   Path(os.getenv("LOG_DIR", str(ROOT / "logs"))), int(os.getenv("GAME_SEED", "7")))
