"""Logique pure (sans Streamlit) : que faire des portefeuilles A/B quand l'utilisateur change de profil ?

Règles :
- Un portefeuille personnalisé ou en cours d'édition n'est JAMAIS remplacé automatiquement.
- Les scénarios par défaut du nouveau profil sont chargés automatiquement seulement si l'utilisateur n'a encore rien choisi
  (les deux emplacements sont des préréglages intacts et jamais touchés) ; une annulation en un clic reste possible.
- Sinon, les scénarios suggérés sont seulement proposés, et ne sont chargés que sur action explicite, dans les
  emplacements qui sont des préréglages intacts.
"""
from __future__ import annotations

PRESET, CUSTOM, EDITED = "preset", "custom", "edited"


def slot_status(slot: dict, presets: dict) -> str:
    """'edited' : saisie différente des poids analysés (ou invalide) ; 'preset' : préréglage intact ; 'custom' : autre portefeuille."""
    if slot.get("dirty"):
        return EDITED
    pid = slot.get("preset")
    if pid in presets and presets[pid]["weights_pct"] == slot.get("applied_pct"):
        return PRESET
    return CUSTOM


def plan_switch(statuses: dict, touched: bool) -> str:
    """'auto_load' si rien n'a été choisi ou modifié par l'utilisateur, sinon 'suggest'."""
    return "auto_load" if (not touched and all(s == PRESET for s in statuses.values())) else "suggest"


def loadable(statuses: dict) -> list[str]:
    """Emplacements pouvant recevoir les scénarios suggérés : jamais un portefeuille personnalisé ou en cours d'édition."""
    return [k for k, s in statuses.items() if s == PRESET]


def matches_suggestion(slots: dict, defaults_for_profile: dict) -> bool:
    return slots["A"].get("preset") == defaults_for_profile["a"] and slots["B"].get("preset") == defaults_for_profile["b"]
