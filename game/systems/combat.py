import pygame
from game import config as C
from game.entities.pickup import Bullet
from game.systems.collision import segment_rect_fraction, segment_circle_hit


def shoot(world, target) -> str:
    player = world.player
    if target is None:
        return "No target"
    if player.reload_remaining > 0:
        return "Cannot shoot while reloading"
    if player.ammo <= 0:
        return "Empty magazine"
    if player.cooldown > 0:
        return "Weapon cooling down"
    direction = target - player.pos
    if not direction.length_squared():
        direction = player.aim.copy()
    player.aim = direction.normalize()
    world.bullets.append(Bullet(player.pos.copy(), player.aim * C.BULLET_SPEED, C.WEAPON_RANGE))
    player.ammo -= 1
    player.cooldown = C.WEAPON_COOLDOWN
    world.shots += 1
    return "Fired at nearest target"


def tick_bullets(world, dt):
    for bullet in world.bullets[:]:
        start = bullet.pos.copy()
        step = bullet.velocity * dt
        if step.length() > bullet.remaining:
            step.scale_to_length(max(0.0, bullet.remaining))
        end = start + step
        segment_length = start.distance_to(end)
        wall_fractions = [f for w in world.walls if (f := segment_rect_fraction(start, end, w)) is not None]
        wall_fraction = min(wall_fractions, default=1.1)
        hit = None
        hit_fraction = wall_fraction
        for zombie in world.zombies:
            if zombie.hp > 0 and segment_circle_hit(start, end, zombie.pos, C.ZOMBIE_RADIUS + 3):
                # First intersection along the segment, not entity-list order.
                d = (end - start).normalize() if segment_length else pygame.Vector2(1, 0)
                relative = zombie.pos - start
                projection = relative.dot(d)
                perpendicular_sq = max(0, relative.length_squared() - projection ** 2)
                offset = max(0, (C.ZOMBIE_RADIUS + 3) ** 2 - perpendicular_sq) ** 0.5
                fraction = max(0, projection - offset) / segment_length if segment_length else 0
                if fraction < hit_fraction:
                    hit, hit_fraction = zombie, fraction
        bullet.pos = end
        bullet.remaining -= segment_length
        if hit is not None:
            hit.hp -= C.WEAPON_DAMAGE
            world.hits += 1
            if hit.hp <= 0:
                world.zombies.remove(hit)
                world.kills += 1
                world.score += 100
                world.effects.append([hit.pos.copy(), 0.4])
        if hit is not None or wall_fraction <= 1 or bullet.remaining <= 0:
            world.bullets.remove(bullet)


def tick_contacts(world, dt):
    for zombie in world.zombies:
        zombie.attack_remaining = max(0, zombie.attack_remaining - dt)
        if zombie.pos.distance_to(world.player.pos) <= C.PLAYER_RADIUS + C.ZOMBIE_RADIUS + 2:
            if zombie.attack_remaining == 0:
                world.player.hp = max(0, world.player.hp - zombie.damage)
                zombie.attack_remaining = C.ZOMBIE_ATTACK_INTERVAL
                world.damage_taken += zombie.damage
    for pickup in world.pickups[:]:
        if pickup.pos.distance_to(world.player.pos) < C.PLAYER_RADIUS + 14:
            if pickup.kind == "medkit":
                world.player.medkits += 1
                world.last_effect = "Collected medkit"
            else:
                world.player.reserve_ammo += 20
                world.last_effect = "Collected +20 reserve ammo"
            world.pickups.remove(pickup)
            world.collected += 1
