"""Command-line entry point. Defaults to fully offline mock AI."""
import argparse
from dataclasses import replace
import json
import logging
import math
import os
from pathlib import Path
from dotenv import load_dotenv
from game.config import ROOT, Settings


def main():
    parser = argparse.ArgumentParser(description="Jev Zombie Survival: tactical AI laboratory")
    parser.add_argument("--mode", choices=["mock", "jev", "manual", "fallback"])
    parser.add_argument("--headless", action="store_true", help="SDL dummy video/audio drivers")
    parser.add_argument("--seconds", type=float, help="Stop automatically (benchmark default 120)")
    parser.add_argument("--screenshot", type=Path, help="Save final frame as PNG")
    parser.add_argument("--benchmark", action="store_true", help="Compare offline AI simulations")
    parser.add_argument("--benchmark-modes", nargs="+", choices=["mock", "fallback", "jev"], default=["mock", "fallback"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0):
        parser.error("--seconds must be a finite positive number")
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    load_dotenv(ROOT / ".env", override=False)
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        parser.error(str(exc))
    if args.mode: settings = replace(settings, mode=args.mode)
    if args.seed is not None: settings = replace(settings, seed=args.seed)
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(settings.log_dir / "game.log", encoding="utf-8")])
    # HTTP client's informational URLs aren't needed in the gameplay event log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.benchmark:
        from game.benchmark import benchmark
        report = benchmark(settings, args.benchmark_modes, args.runs, args.seconds or 120)
    else:
        from game.game import Game
        report = Game(settings).run(args.seconds, args.screenshot)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
