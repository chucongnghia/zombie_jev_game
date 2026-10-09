"""Deterministic simulation independent of rendering and network requests."""
import pygame
from game import config as C
from game.entities.player import Player
from game.entities.pickup import Pickup
from game.systems.spawning import Spawner
from game.systems.collision import move_circle
from game.systems.combat import tick_bullets, tick_contacts
from game.systems.navigation import ObstacleNavigator


class World:
    def __init__(self, seed: int = 7):
        self.player = Player()
        self.zombies = []
        self.bullets = []
        self.pickups = [Pickup(pygame.Vector2(180, 350), "medkit"),
                        Pickup(pygame.Vector2(800, 350), "ammo"),
                        Pickup(pygame.Vector2(500, 600), "ammo")]
        self.walls = [pygame.Rect(245, 140, 140, 42), pygame.Rect(620, 160, 42, 145),
                      pygame.Rect(255, 490, 42, 130), pygame.Rect(680, 520, 135, 42)]
        self.survival_time = 0.0
        self.kills = self.score = self.shots = self.hits = self.damage_taken = self.collected = 0
        self.wave = 1
        self.effects = []
        self.last_effect = "Waiting for tactical decision"
        self.spawner = Spawner(seed)
        self.navigator = ObstacleNavigator()

    @property
    def alive(self) -> bool:
        return self.player.hp > 0

    def nearest_zombie(self):
        return min(self.zombies, key=lambda z: z.pos.distance_squared_to(self.player.pos), default=None)

    def nearest_pickup(self, kind):
        return min((p for p in self.pickups if p.kind == kind),
                   key=lambda p: p.pos.distance_squared_to(self.player.pos), default=None)

    def move_player(self, direction, dt):
        old = self.player.pos.copy()
        self.player.pos = move_circle(old, direction, self.player.speed, dt, C.PLAYER_RADIUS, self.walls)
        return self.player.pos.distance_to(old)

    def move_player_to(self, target: pygame.Vector2, dt: float) -> float:
        direction = self.navigator.direction("player", self.player.pos, target, self.walls, C.PLAYER_RADIUS)
        return self.move_player(direction, dt)

    def tick(self, dt):
        if not self.alive:
            return
        self.survival_time += dt
        self.player.tick(dt)
        self.spawner.tick(self, dt)
        live_ids = {id(zombie) for zombie in self.zombies}
        for key in list(self.navigator.routes):
            if key != "player" and key not in live_ids:
                self.navigator.routes.pop(key, None)
        for zombie in self.zombies:
            direction = self.navigator.direction(id(zombie), zombie.pos, self.player.pos,
                                                 self.walls, C.ZOMBIE_RADIUS)
            # Mild separation prevents all enemies occupying exactly the same point.
            if direction.length_squared():
                direction = direction.normalize()
            for other in self.zombies:
                delta = zombie.pos - other.pos
                if other is not zombie and 0 < delta.length_squared() < (C.ZOMBIE_RADIUS * 2) ** 2:
                    direction += delta.normalize() * 0.45
            zombie.pos = move_circle(zombie.pos, direction, zombie.speed, dt, C.ZOMBIE_RADIUS, self.walls)
        tick_bullets(self, dt)
        tick_contacts(self, dt)
        for effect in self.effects[:]:
            effect[1] -= dt
            if effect[1] <= 0:
                self.effects.remove(effect)
