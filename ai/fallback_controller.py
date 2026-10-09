"""Local safety heuristic. It never invents model confidence or probabilities."""

from .models import Action, Decision


def _heuristic_action(state: dict) -> Action:
    player = state.get("player", {})
    threat = state.get("threat", {})
    resources = state.get("resources", {})
    hp = player.get("hp_percent", 100)
    ammo = player.get("ammo", 0)
    nearest = threat.get("nearest_zombie_distance")
    close = nearest is not None and nearest <= 70
    if close:
        return Action.MOVE_AWAY
    if hp <= 50 and player.get("medkits", 0) > 0:
        return Action.HEAL
    if player.get("reloading", False):
        return Action.MOVE_AWAY if nearest is not None and nearest <= 200 else Action.HOLD_POSITION
    if ammo <= 0:
        if player.get("reserve_ammo", 0) > 0:
            return Action.MOVE_AWAY if nearest is not None and nearest <= 130 else Action.RELOAD
        if resources.get("nearest_ammo_distance") is not None:
            return Action.MOVE_TO_AMMO
        return Action.MOVE_AWAY if nearest is not None else Action.HOLD_POSITION
    if hp <= 65 and resources.get("nearest_medkit_distance") is not None:
        return Action.MOVE_TO_MEDKIT
    if nearest is not None and player.get("weapon_ready", False):
        return Action.SHOOT_NEAREST
    if ammo < player.get("max_ammo", ammo) and player.get("reserve_ammo", 0) > 0 and nearest is None:
        return Action.RELOAD
    if player.get("reserve_ammo", 0) <= 0 and resources.get("nearest_ammo_distance") is not None:
        return Action.MOVE_TO_AMMO
    return Action.HOLD_POSITION


class FallbackController:
    def decide(self, state: dict) -> Decision:
        try:
            action = _heuristic_action(state)
        except Exception:
            # State may itself be malformed after a remote failure; fail safely.
            return Decision(action=Action.HOLD_POSITION, source="fallback", error="invalid_state")
        return Decision(action=action, source="fallback")
