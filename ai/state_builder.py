"""Compact snapshots; the worker never receives live world objects."""


class GameStateBuilder:
    @staticmethod
    def build(world) -> dict:
        player = world.player
        zombie_distances = [float(player.pos.distance_to(z.pos)) for z in world.zombies]
        medkit_distances = []
        ammo_distances = []
        for pickup in world.pickups:
            if pickup.kind == "medkit":
                medkit_distances.append(float(player.pos.distance_to(pickup.pos)))
            elif pickup.kind == "ammo":
                ammo_distances.append(float(player.pos.distance_to(pickup.pos)))
        max_hp = float(player.max_hp)
        reloading = player.reload_remaining > 0
        return {
            "player": {
                "hp_percent": max(0.0, min(100.0, float(player.hp) / max_hp * 100)) if max_hp > 0 else 0.0,
                "ammo": int(player.ammo),
                "max_ammo": int(player.max_ammo),
                "reserve_ammo": int(player.reserve_ammo),
                "medkits": int(player.medkits),
                "weapon_ready": bool(player.cooldown <= 0 and not reloading),
                "reloading": bool(reloading),
            },
            "threat": {
                "zombie_count": len(zombie_distances),
                "nearest_zombie_distance": min(zombie_distances, default=None),
                "zombies_within_100": sum(d <= 100 for d in zombie_distances),
                "zombies_within_200": sum(d <= 200 for d in zombie_distances),
            },
            "resources": {
                "nearest_medkit_distance": min(medkit_distances, default=None),
                "nearest_ammo_distance": min(ammo_distances, default=None),
            },
            "context": {
                "survival_time": float(world.survival_time),
                "kills": int(world.kills),
                "wave": int(world.wave),
            },
        }
