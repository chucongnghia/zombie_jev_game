import random
import pygame
from game import config as C
from game.entities.zombie import Zombie
from game.entities.pickup import Pickup
from game.systems.collision import is_free


class Spawner:
    def __init__(self, seed: int):
        self.random = random.Random(seed)
        self.spawn_remaining = 1.0
        self.resource_remaining = C.RESOURCE_INTERVAL

    def free_position(self, world, edge: bool = False):
        for _ in range(100):
            if edge:
                side = self.random.randrange(4)
                x = self.random.uniform(20, C.GAME_WIDTH - 20)
                y = self.random.uniform(20, C.GAME_HEIGHT - 20)
                if side == 0: x = 20
                elif side == 1: x = C.GAME_WIDTH - 20
                elif side == 2: y = 20
                else: y = C.GAME_HEIGHT - 20
            else:
                x = self.random.uniform(35, C.GAME_WIDTH - 35)
                y = self.random.uniform(35, C.GAME_HEIGHT - 35)
            pos = pygame.Vector2(x, y)
            if is_free(pos, 18, world.walls) and (not edge or pos.distance_to(world.player.pos) > 180):
                return pos
        return None

    def tick(self, world, dt):
        world.wave = 1 + int(world.survival_time / C.WAVE_SECONDS)
        self.spawn_remaining -= dt
        if self.spawn_remaining <= 0:
            self.spawn_remaining = max(0.4, 3.0 / (1 + 0.5 * (world.wave - 1)))
            if len(world.zombies) < C.MAX_ZOMBIES:
                pos = self.free_position(world, edge=True)
                if pos is not None:
                    world.zombies.append(Zombie(pos, speed=C.ZOMBIE_SPEED + min(70, (world.wave - 1) * 8)))
        self.resource_remaining -= dt
        if self.resource_remaining <= 0:
            self.resource_remaining = C.RESOURCE_INTERVAL
            if len(world.pickups) < C.MAX_PICKUPS:
                pos = self.free_position(world)
                if pos is not None:
                    world.pickups.append(Pickup(pos, self.random.choice(["ammo", "ammo", "medkit"])))
