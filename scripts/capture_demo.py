"""Reproduce state-viewer and end-of-run screenshots without API or external assets.

Run from project root: python -m scripts.capture_demo
"""
import os
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import json
import pygame
from game import config as C
from game.world import World
from game.session import Session
from game.ui.renderer import Renderer
from game.systems.action_executor import ActionExecutor
from ai.mock_jev import MockJevController
from ai.state_builder import GameStateBuilder


def main():
    pygame.init()
    screen = pygame.display.set_mode((C.SCREEN_WIDTH, C.SCREEN_HEIGHT))
    renderer = Renderer(screen)
    world = World(7)
    session = Session("mock", C.ROOT / "logs" / "capture")
    executor = ActionExecutor()
    controller = MockJevController(7)
    next_decision = 0.0
    captured = False
    output = C.ROOT / "artifacts"
    output.mkdir(exist_ok=True)
    try:
        while world.alive and world.survival_time < 300:
            if world.survival_time >= next_decision:
                state = GameStateBuilder.build(world)
                session.record(controller.decide(state), state, world)
                executor.begin()
                next_decision = world.survival_time + C.JEV_DECISION_INTERVAL
            world.last_effect = executor.execute(world, session.decision.action, 1 / 60)
            world.tick(1 / 60)
            if not captured and world.survival_time >= 40:
                renderer.show_state = True
                renderer.draw(world, session)
                pygame.image.save(screen, output / "state-viewer.png")
                renderer.show_state = False
                captured = True
        session.finish(world, "time_limit" if world.alive else "game_over")
        renderer.draw(world, session)
        pygame.image.save(screen, output / "end-run.png")
        print(json.dumps(session.summary(world), indent=2))
    finally:
        session.finish(world, "stopped")
        pygame.quit()


if __name__ == "__main__":
    main()
