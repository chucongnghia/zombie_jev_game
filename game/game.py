"""60 FPS orchestration; no network work occurs on the rendering thread."""
import logging
import time
from pathlib import Path
import pygame
from ai.models import Action, Decision
from ai.state_builder import GameStateBuilder
from ai.mock_jev import MockJevController
from ai.fallback_controller import FallbackController
from ai.jev_controller import JevController
from ai.decision_worker import DecisionWorker
from game import config as C
from game.session import Session
from game.world import World
from game.systems.action_executor import ActionExecutor
from game.systems.combat import shoot
from game.ui.renderer import Renderer

logger = logging.getLogger(__name__)


class Game:
    def __init__(self, settings: C.Settings):
        self.settings = settings
        pygame.init()
        self.screen = pygame.display.set_mode((C.SCREEN_WIDTH, C.SCREEN_HEIGHT))
        pygame.display.set_caption("Jev Zombie Survival | Tactical AI laboratory")
        self.clock = pygame.time.Clock()
        self.renderer = Renderer(self.screen)
        self.world = World(settings.seed)
        self.session = Session(settings.mode, settings.log_dir)
        self.builder = GameStateBuilder()
        self.executor = ActionExecutor()
        self.worker = DecisionWorker(settings.timeout)
        self.controllers = {"mock": MockJevController(settings.seed), "fallback": FallbackController(),
                            "jev": JevController(timeout=settings.timeout, model=settings.model)}
        self.generation = 0
        self.next_decision = 0.0
        self.timeout_degraded = False
        self.stale_request = False
        self.running = True
        logger.info("Game started; AI mode=%s", settings.mode)

    def change_mode(self, mode):
        self.session.finalize_action(self.world)
        self.session.mode = mode
        self.session.decision = Decision(Action.HOLD_POSITION, None, {}, "waiting", None)
        self.generation += 1
        self.next_decision = 0.0
        self.timeout_degraded = False
        self.stale_request = self.worker.busy
        self.executor.begin()
        logger.info("AI mode=%s; pending answers from older generations are discarded", mode)

    def restart(self):
        self.session.finish(self.world, "restart")
        mode = self.session.mode
        self.world = World(self.settings.seed)
        self.session = Session(mode, self.settings.log_dir)
        self.controllers["mock"] = MockJevController(self.settings.seed)
        self.generation += 1
        self.next_decision = 0.0
        self.timeout_degraded = False
        self.stale_request = self.worker.busy
        self.executor.begin()
        logger.info("Game restarted")

    def events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE: self.running = False
                elif event.key == pygame.K_TAB: self.renderer.show_state = not self.renderer.show_state
                elif event.key == pygame.K_F1: self.change_mode("manual")
                elif event.key == pygame.K_F2: self.change_mode("mock")
                elif event.key == pygame.K_F3: self.change_mode("jev")
                elif event.key == pygame.K_r:
                    if not self.world.alive: self.restart()
                    elif self.session.mode == "manual": self.world.last_effect = self.world.player.reload()
                elif event.key == pygame.K_h and self.session.mode == "manual" and self.world.alive:
                    self.world.last_effect = self.world.player.heal()

    def manual(self, dt):
        keys = pygame.key.get_pressed()
        direction = pygame.Vector2(int(keys[pygame.K_d]) - int(keys[pygame.K_a]),
                                   int(keys[pygame.K_s]) - int(keys[pygame.K_w]))
        self.world.move_player(direction, dt)
        if keys[pygame.K_SPACE]:
            nearest = self.world.nearest_zombie()
            self.world.last_effect = shoot(self.world, nearest.pos if nearest else None)

    def local_decision(self, mode: str, state: dict) -> Decision:
        started = time.perf_counter()
        decision = self.controllers[mode].decide(state)
        decision.latency_ms = (time.perf_counter() - started) * 1000
        return decision

    def apply(self, decision, state, decision_state=None):
        self.session.record(decision, state, self.world, decision_state)
        self.executor.begin()
        logger.info("%s action=%s confidence=%s latency_ms=%s error=%s", decision.source.upper(),
                    decision.action.value, decision.confidence, decision.latency_ms, decision.error)

    def tactical(self, now, dt):
        result = self.worker.poll(now)
        if result is not None and result.generation == self.generation and self.world.alive and self.session.mode != "manual":
            # Error fallbacks should act on present hazards, not a five-second-old snapshot.
            if result.decision.source == "fallback":
                fresh = self.builder.build(self.world)
                fallback = self.controllers["fallback"].decide(fresh)
                fallback.error = result.decision.error
                fallback.latency_ms = result.decision.latency_ms
                self.apply(fallback, result.state, decision_state=fresh)
            else:
                self.apply(result.decision, result.state)
            self.timeout_degraded = result.decision.error == "timeout"
            self.next_decision = now + self.settings.decision_interval
        if not self.world.alive or self.session.mode == "manual":
            return
        if now >= self.next_decision:
            state = self.builder.build(self.world)
            if self.session.mode in {"mock", "fallback"}:
                # Local O(7) rules do not use the network gate or require a thread.
                self.apply(self.local_decision(self.session.mode, state), state)
                self.next_decision = now + self.settings.decision_interval
            elif self.worker.busy and (self.timeout_degraded or self.stale_request):
                # A discarded generation must not freeze the new run behind an old HTTP call.
                local_mode = self.session.mode if self.session.mode in {"mock", "fallback"} else "fallback"
                self.apply(self.local_decision(local_mode, state), state)
                self.next_decision = now + self.settings.decision_interval
            elif self.worker.submit(self.controllers[self.session.mode], state, now, self.generation):
                self.session.last_state = state
                self.next_decision = now + self.settings.decision_interval
                self.timeout_degraded = False
                self.stale_request = False
                logger.debug("AI REQUEST state=%s", state)
            elif not self.worker.busy:
                # Another closed Game may still own the process-wide remote gate.
                self.apply(self.local_decision("fallback", state), state)
                self.next_decision = now + self.settings.decision_interval
        self.world.last_effect = self.executor.execute(self.world, self.session.decision.action, dt)

    def run(self, max_seconds=None, screenshot: Path | None = None):
        start = time.monotonic()
        try:
            while self.running:
                dt = min(0.05, self.clock.tick(C.FPS) / 1000)
                now = time.monotonic()
                self.events()
                if self.world.alive:
                    self.tactical(now, dt)
                    if self.session.mode == "manual": self.manual(dt)
                    self.world.tick(dt)
                    if not self.world.alive:
                        self.session.finish(self.world)
                        logger.info("GAME OVER %s", self.session.summary(self.world))
                else:
                    self.worker.poll(now)  # Discard dead-run answers; never apply them after restart.
                self.renderer.draw(self.world, self.session, self.worker.busy, self.clock.get_fps())
                pygame.display.flip()
                if max_seconds is not None and now - start >= max_seconds:
                    break
            if screenshot is not None:
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                pygame.image.save(self.screen, screenshot)
            return self.session.summary(self.world)
        finally:
            self.worker.close()
            self.session.finish(self.world, "quit" if not self.world.alive else "stopped")
            # Don't close an SDK transport while its daemon request is still executing.
            if not self.worker.busy:
                for controller in self.controllers.values():
                    close = getattr(controller, "close", None)
                    if close:
                        try:
                            close()
                        except Exception:
                            logger.warning("AI transport cleanup failed; game remains stopped safely")
            pygame.quit()
