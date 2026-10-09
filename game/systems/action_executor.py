"""Mechanical HOW layer: turn tactical actions into continuous local controls."""
import pygame
from ai.models import Action
from game import config as C
from game.systems.combat import shoot


class ActionExecutor:
    def __init__(self):
        self.one_shot_done = False
        self.one_shot_result = ""

    def begin(self):
        self.one_shot_done = False
        self.one_shot_result = ""

    def execute(self, world, action: Action, dt: float) -> str:
        player = world.player
        nearest = world.nearest_zombie()
        if action == Action.SHOOT_NEAREST:
            return shoot(world, nearest.pos if nearest else None)
        if action == Action.RELOAD:
            if not self.one_shot_done:
                self.one_shot_done = True
                self.one_shot_result = player.reload()
            if self.one_shot_result in {"Reload started", "Reloading..."}:
                return "Reloading..." if player.reload_remaining else "Reload complete"
            return self.one_shot_result
        if action == Action.HEAL:
            if not self.one_shot_done:
                self.one_shot_done = True
                self.one_shot_result = player.heal()
            return self.one_shot_result
        if action == Action.MOVE_AWAY:
            if nearest is None:
                return "No nearby threat"
            direction = player.pos - nearest.pos
            if direction.length_squared():
                direction = direction.normalize()
            else:
                direction = pygame.Vector2(1, 0)
            # Avoid getting pinned to a border: mix repulsion with tangential motion.
            margin = 90
            edge = pygame.Vector2()
            if player.pos.x < margin: edge.x += 1
            if player.pos.x > C.GAME_WIDTH - margin: edge.x -= 1
            if player.pos.y < margin: edge.y += 1
            if player.pos.y > C.GAME_HEIGHT - margin: edge.y -= 1
            if edge.length_squared():
                direction += edge * 1.5 + direction.rotate(90) * 0.75
            distance = world.move_player(direction, dt)
            return "Evading nearest enemy" if distance else "Movement blocked"
        if action in (Action.MOVE_TO_MEDKIT, Action.MOVE_TO_AMMO):
            kind = "medkit" if action == Action.MOVE_TO_MEDKIT else "ammo"
            pickup = world.nearest_pickup(kind)
            if pickup is None:
                return f"No {kind} on map"
            distance = world.move_player_to(pickup.pos, dt)
            return f"Approaching {kind}" if distance else "Movement blocked"
        return "Holding position"
