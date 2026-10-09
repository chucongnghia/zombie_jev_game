from dataclasses import dataclass
from pygame import Vector2
from game import config as C

@dataclass
class Zombie:
    pos: Vector2
    hp: int = C.ZOMBIE_HP
    speed: float = C.ZOMBIE_SPEED
    damage: int = C.ZOMBIE_DAMAGE
    attack_remaining: float = 0.0

    def distance_to_player(self, player) -> float:
        return self.pos.distance_to(player.pos)
