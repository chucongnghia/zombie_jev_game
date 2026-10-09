"""Asset-free arena, HUD, action distribution, history and state inspector."""
import json
import math
import textwrap
import pygame
from game import config as C

BG = (12, 20, 27)
PANEL = (17, 28, 37)
INK = (214, 231, 237)
MUTED = (128, 154, 168)
CYAN = (72, 221, 204)
RED = (243, 104, 109)
GOLD = (247, 197, 89)


class Renderer:
    def __init__(self, screen):
        self.screen = screen
        self.arena = pygame.Surface((C.GAME_WIDTH, C.GAME_HEIGHT))
        self.fonts = {size: pygame.font.SysFont("DejaVu Sans Mono", size) for size in (12, 14, 16, 20, 26, 38)}
        self.show_state = False

    def text(self, text, x, y, color=INK, size=14, surface=None):
        target = self.screen if surface is None else surface
        target.blit(self.fonts[size].render(str(text), True, color), (x, y))

    def wrapped(self, text, x, y, width=36, color=MUTED, size=12, max_lines=2):
        for index, line in enumerate(textwrap.wrap(str(text), width)[:max_lines]):
            self.text(line, x, y + index * (size + 4), color, size)

    def draw_arena(self, world):
        arena = self.arena
        arena.fill(BG)
        for x in range(0, C.GAME_WIDTH, 40):
            pygame.draw.line(arena, (19, 32, 39), (x, 0), (x, C.GAME_HEIGHT))
        for y in range(0, C.GAME_HEIGHT, 40):
            pygame.draw.line(arena, (19, 32, 39), (0, y), (C.GAME_WIDTH, y))
        for wall in world.walls:
            pygame.draw.rect(arena, (45, 59, 65), wall, border_radius=5)
            pygame.draw.rect(arena, (87, 109, 113), wall, 2, border_radius=5)
            for x in range(wall.left + 10, wall.right - 4, 20):
                pygame.draw.line(arena, (60, 76, 81), (x, wall.top + 6), (x, wall.bottom - 6))
        for pickup in world.pickups:
            rect = pygame.Rect(pickup.pos.x - 10, pickup.pos.y - 10, 20, 20)
            color = CYAN if pickup.kind == "medkit" else GOLD
            pygame.draw.rect(arena, (25, 50, 52), rect.inflate(8, 8), border_radius=5)
            pygame.draw.rect(arena, color, rect, 2, border_radius=3)
            if pickup.kind == "medkit":
                pygame.draw.line(arena, color, pickup.pos + (-5, 0), pickup.pos + (5, 0), 3)
                pygame.draw.line(arena, color, pickup.pos + (0, -5), pickup.pos + (0, 5), 3)
            else:
                for offset in (-4, 0, 4):
                    pygame.draw.line(arena, color, pickup.pos + (offset, -5), pickup.pos + (offset, 5), 2)
        for zombie in world.zombies:
            pygame.draw.circle(arena, (38, 52, 29), zombie.pos, C.ZOMBIE_RADIUS + 5)
            pygame.draw.circle(arena, (139, 164, 75), zombie.pos, C.ZOMBIE_RADIUS)
            pygame.draw.circle(arena, (221, 82, 71), zombie.pos + (-4, -3), 2)
            pygame.draw.circle(arena, (221, 82, 71), zombie.pos + (4, -3), 2)
            pygame.draw.line(arena, (84, 97, 57), zombie.pos + (-12, -20), zombie.pos + (12, -20), 3)
            pygame.draw.line(arena, RED, zombie.pos + (-12, -20),
                             zombie.pos + (-12 + 24 * zombie.hp / C.ZOMBIE_HP, -20), 3)
        for bullet in world.bullets:
            pygame.draw.circle(arena, GOLD, bullet.pos, 3)
        for pos, remaining in world.effects:
            pygame.draw.circle(arena, RED, pos, int(8 + (0.4 - remaining) * 70), 2)
        player = world.player
        pygame.draw.circle(arena, (26, 70, 72), player.pos, 22)
        pygame.draw.circle(arena, CYAN, player.pos, C.PLAYER_RADIUS)
        pygame.draw.circle(arena, INK, player.pos, C.PLAYER_RADIUS, 2)
        pygame.draw.line(arena, INK, player.pos, player.pos + player.aim * 25, 4)
        if player.reload_remaining:
            pygame.draw.arc(arena, GOLD, pygame.Rect(player.pos.x - 27, player.pos.y - 27, 54, 54),
                            0, 2 * math.pi * (1 - player.reload_remaining / C.RELOAD_SECONDS), 3)
        pygame.draw.rect(arena, (56, 79, 86), arena.get_rect(), 2)
        self.screen.blit(arena, (0, C.HEADER_HEIGHT))

    def draw_header(self, world, fps):
        pygame.draw.rect(self.screen, PANEL, (0, 0, C.SCREEN_WIDTH, C.HEADER_HEIGHT))
        self.text("JEV", 20, 12, CYAN, 26)
        self.text("ZOMBIE SURVIVAL", 88, 18, INK, 20)
        self.text(f"WAVE {world.wave:02d}  |  {world.survival_time:6.1f}s  |  KILLS {world.kills:03d}",
                  380, 20, GOLD, 16)
        self.text(f"{fps:4.0f} FPS", 880, 23, MUTED, 12)

    def draw_panel(self, world, session, pending):
        x = C.GAME_WIDTH + 18
        pygame.draw.rect(self.screen, PANEL, (C.GAME_WIDTH, C.HEADER_HEIGHT,
                                              C.DEBUG_PANEL_WIDTH, C.GAME_HEIGHT))
        d = session.decision
        p = world.player
        self.text(f"AI MODE / {session.mode.upper()}", x, 74, CYAN, 20)
        self.text(f"HP {p.hp:3d}/{p.max_hp}   MEDKITS {p.medkits}", x, 107, INK, 16)
        pygame.draw.rect(self.screen, (51, 65, 72), (x, 134, 320, 5))
        pygame.draw.rect(self.screen, RED if p.hp < 30 else CYAN, (x, 134, 320 * p.hp / p.max_hp, 5))
        self.text(f"AMMO {p.ammo}/{p.max_ammo}  RESERVE {p.reserve_ammo}", x, 147, GOLD, 16)
        nearest = world.nearest_zombie()
        dist = f"{nearest.distance_to_player(p):.0f}px" if nearest else "--"
        self.text(f"ZOMBIES {len(world.zombies):02d}   NEAREST {dist}", x, 174, MUTED, 14)
        self.text("CURRENT TACTICAL ACTION", x, 208, MUTED, 12)
        self.text("MANUAL CONTROL" if session.mode == "manual" else d.action.value, x, 230, CYAN, 20)
        conf = "n/a" if d.confidence is None else f"{d.confidence:.3f}"
        latency = "--" if d.latency_ms is None else f"{d.latency_ms:.0f}ms"
        self.text(f"CONF {conf}  LATENCY {latency}", x, 261, INK, 14)
        self.text(f"SOURCE {d.source}  {'[pending]' if pending else '[ready]'}", x, 284, MUTED, 12)
        if d.error:
            self.text(f"ERROR / {d.error}", x, 300, RED, 12)
        self.text("ACTION DISTRIBUTION" + (" / SYNTHETIC" if d.source == "mock" else ""), x, 315, GOLD, 12)
        if d.probabilities:
            for index, (name, probability) in enumerate(sorted(d.probabilities.items(), key=lambda item: -item[1])):
                y = 341 + index * 24
                self.text(name, x, y, INK if name == d.action.value else MUTED, 12)
                pygame.draw.rect(self.screen, (36, 51, 62), (x + 164, y + 4, 110, 9), border_radius=3)
                pygame.draw.rect(self.screen, CYAN, (x + 164, y + 4, int(110 * probability), 9), border_radius=3)
                self.text(f"{probability:.0%}", x + 280, y - 1, INK, 12)
        else:
            self.text("No probabilities supplied", x, 345, MUTED, 14)
        self.text("Uncalibrated estimates, not success rates.", x, 510, MUTED, 12)
        self.text("DECISION HISTORY", x, 536, GOLD, 12)
        for index, entry in enumerate(session.history):
            confidence = "--" if entry["confidence"] is None else f"{entry['confidence']:.2f}"
            self.text(f"{entry['timestamp']:5.1f}s {entry['action']:<15} {confidence}",
                      x, 558 + index * 17, MUTED if index else INK, 12)
        self.wrapped(world.last_effect, x, 703, max_lines=1, color=CYAN)
        self.text("F1 MANUAL  F2 MOCK  F3 JEV  TAB STATE", x, 734, MUTED, 12)

    def draw_state(self, session):
        rect = pygame.Rect(28, C.HEADER_HEIGHT + 20, 700, 650)
        pygame.draw.rect(self.screen, (17, 28, 37), rect, border_radius=12)
        pygame.draw.rect(self.screen, CYAN, rect, 1, border_radius=12)
        self.text("LAST STATE SENT / WHAT THE AI SEES", 48, rect.top + 18, CYAN, 20)
        for index, line in enumerate(json.dumps(session.last_state, indent=2).splitlines()):
            self.text(line, 48, rect.top + 55 + index * 16, INK, 12)
        self.wrapped(session.last_outcome, 48, rect.bottom - 48, width=78, color=GOLD, max_lines=2)

    def draw_game_over(self, world, session):
        shade = pygame.Surface((C.GAME_WIDTH, C.GAME_HEIGHT), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 175))
        self.screen.blit(shade, (0, C.HEADER_HEIGHT))
        box = pygame.Rect(180, 145, 640, 535)
        pygame.draw.rect(self.screen, PANEL, box, border_radius=14)
        pygame.draw.rect(self.screen, RED, box, 2, border_radius=14)
        self.text("GAME OVER", 350, 169, RED, 38)
        stats = session.summary(world)
        def confidence_label(value):
            if not value:
                return "n/a"
            return f"{value['action']} {value['confidence']:.3f} ({value['source']})"
        def number(value, digits=3):
            return "n/a" if value is None else f"{value:.{digits}f}"
        lines = [f"Survival {world.survival_time:.1f}s  |  Kills {world.kills}  |  Score {world.score}",
                 f"Decisions: {stats.get('total_decisions', 0)}",
                 f"Jev decisions: {stats.get('jev_decisions', 0)}",
                 f"Average confidence: {number(stats.get('average_confidence'))}",
                 f"Average Jev latency: {number(stats.get('average_jev_latency'), 1)} ms",
                 f"API errors: {stats.get('api_errors', 0)} / Fallbacks: {stats.get('fallback_count', 0)}",
                 "AI ANALYSIS",
                 f"Most used: {stats.get('most_used_action')}",
                 f"Highest: {confidence_label(stats.get('highest_confidence_action'))}",
                 f"Lowest: {confidence_label(stats.get('lowest_confidence_decision'))}",
                 f"Fallback rate: {stats.get('fallback_rate', 0):.1%}",
                 "R RESTART    ESC QUIT"]
        for index, line in enumerate(lines):
            self.wrapped(line, 208, 238 + index * 34, width=58, color=GOLD if index in (6, 11) else INK,
                         size=14, max_lines=1)

    def draw(self, world, session, pending=False, fps=0):
        self.screen.fill(BG)
        self.draw_arena(world)
        self.draw_header(world, fps)
        self.draw_panel(world, session, pending)
        if self.show_state:
            self.draw_state(session)
        if not world.alive:
            self.draw_game_over(world, session)
