from dataclasses import dataclass
from pygame import Vector2

@dataclass
class Pickup:
    pos: Vector2
    kind: str

@dataclass
class Bullet:
    pos: Vector2
    velocity: Vector2
    remaining: float
