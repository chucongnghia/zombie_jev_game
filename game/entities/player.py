from dataclasses import dataclass, field
from pygame import Vector2
from game import config as C

@dataclass
class Player:
    pos: Vector2 = field(default_factory=lambda: Vector2(500, 350))
    hp: int = C.PLAYER_HP
    max_hp: int = C.PLAYER_HP
    ammo: int = C.MAGAZINE_SIZE
    max_ammo: int = C.MAGAZINE_SIZE
    reserve_ammo: int = C.START_RESERVE
    medkits: int = C.START_MEDKITS
    speed: float = C.PLAYER_SPEED
    cooldown: float = 0.0
    reload_remaining: float = 0.0
    heal_remaining: float = 0.0
    aim: Vector2 = field(default_factory=lambda: Vector2(1, 0))

    def tick(self, dt: float) -> None:
        self.cooldown = max(0.0, self.cooldown - dt)
        self.heal_remaining = max(0.0, self.heal_remaining - dt)
        if self.reload_remaining > 0:
            self.reload_remaining = max(0.0, self.reload_remaining - dt)
            if self.reload_remaining == 0:
                amount = min(self.max_ammo - self.ammo, self.reserve_ammo)
                self.ammo += amount
                self.reserve_ammo -= amount

    def reload(self) -> str:
        if self.reload_remaining > 0:
            return "Reloading..."
        if self.ammo >= self.max_ammo:
            return "Magazine full"
        if self.reserve_ammo <= 0:
            return "No reserve ammo: collect a box"
        self.reload_remaining = C.RELOAD_SECONDS
        return "Reload started"

    def heal(self) -> str:
        if self.hp >= self.max_hp:
            return "Health already full"
        if self.medkits <= 0:
            return "No medkits"
        if self.heal_remaining > 0:
            return "Medkit cooldown"
        self.medkits -= 1
        self.hp = min(self.max_hp, self.hp + C.HEAL_AMOUNT)
        self.heal_remaining = C.HEAL_COOLDOWN
        return f"Healed +{C.HEAL_AMOUNT} HP"
