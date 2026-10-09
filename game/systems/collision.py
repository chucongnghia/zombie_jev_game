"""Circle/wall collisions and inexpensive local obstacle steering."""
import math
import pygame
from game import config as C


def circle_hits_rect(pos: pygame.Vector2, radius: float, rect: pygame.Rect) -> bool:
    x = min(max(pos.x, rect.left), rect.right)
    y = min(max(pos.y, rect.top), rect.bottom)
    return (pos.x - x) ** 2 + (pos.y - y) ** 2 < radius ** 2


def is_free(pos, radius, walls) -> bool:
    return (radius <= pos.x <= C.GAME_WIDTH - radius
            and radius <= pos.y <= C.GAME_HEIGHT - radius
            and not any(circle_hits_rect(pos, radius, wall) for wall in walls))


def move_circle(pos, direction, speed, dt, radius, walls) -> pygame.Vector2:
    if direction.length_squared() == 0:
        return pos.copy()
    velocity = direction.normalize() * speed * dt
    # Try small turns then progressively wider turns; no game objects enter the AI state.
    for angle in (0, 35, -35, 70, -70, 105, -105):
        step = velocity.rotate(angle)
        candidate = pos + step
        if is_free(candidate, radius, walls):
            return candidate
    # Slide on one axis when pressed against a wall or arena border.
    for step in (pygame.Vector2(velocity.x, 0), pygame.Vector2(0, velocity.y)):
        if is_free(pos + step, radius, walls):
            return pos + step
    return pos.copy()


def segment_circle_hit(start, end, center, radius: float) -> bool:
    segment = end - start
    if segment.length_squared() == 0:
        return start.distance_squared_to(center) <= radius ** 2
    t = max(0.0, min(1.0, (center - start).dot(segment) / segment.length_squared()))
    return (start + t * segment).distance_squared_to(center) <= radius ** 2


def segment_rect_fraction(start, end, rect) -> float | None:
    clipped = rect.clipline(tuple(start), tuple(end))
    if not clipped:
        return None
    distance = start.distance_to(end)
    return start.distance_to(pygame.Vector2(clipped[0])) / distance if distance else 0.0
