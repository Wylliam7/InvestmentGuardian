"""Validation des pondérations saisies par l'utilisateur (aucune dépendance Streamlit).

Principe : les poids saisis ne sont JAMAIS modifiés silencieusement. Toute erreur est signalée ; la normalisation
à 100 % n'existe que sous forme de fonction explicite, appelée sur action de l'utilisateur.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from guardian.finance.portfolio import WEIGHT_TOLERANCE

TOTAL_TOLERANCE_PTS = 100 * WEIGHT_TOLERANCE      # 0,01 point de pourcentage


@dataclass(frozen=True)
class BuilderResult:
    weights_pct: dict | None             # poids EXACTEMENT saisis (en %), seulement si aucune erreur
    errors: tuple = ()
    total_pct: float = 0.0
    n_rows: int = 0
    only_sum_is_wrong: bool = False      # la seule erreur est un total différent de 100 % (normalisation possible)
    rows_seen: dict = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return self.weights_pct is not None and not self.errors

    @property
    def fraction_weights(self) -> dict:
        return {t: w / 100.0 for t, w in self.weights_pct.items()}


def _is_blank(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x)) or (isinstance(x, str) and not x.strip())


def parse_weight_rows(rows, known_tickers) -> BuilderResult:
    """rows : liste de dicts {"ticker": str|None, "weight_pct": number|None}. Retourne les poids saisis ou les erreurs."""
    known = set(known_tickers)
    errors: list[str] = []
    seen: dict = {}
    dups: list[str] = []
    n_rows = 0
    total = 0.0
    for i, row in enumerate(rows, start=1):
        t, w = row.get("ticker"), row.get("weight_pct")
        if _is_blank(t) and _is_blank(w):
            continue                                                   # ligne vide : ignorée sans effet
        n_rows += 1
        if _is_blank(t):
            errors.append(f"Ligne {i} : un poids est saisi sans actif.")
            continue
        t = str(t).strip()
        if t not in known:
            errors.append(f"Actif absent de l'univers officiel : {t!r}.")
            continue
        if _is_blank(w):
            errors.append(f"{t} : aucun poids saisi.")
            continue
        try:
            wf = float(w)
        except (TypeError, ValueError):
            errors.append(f"{t} : poids non numérique ({w!r}).")
            continue
        if not math.isfinite(wf):
            errors.append(f"{t} : poids non valide.")
            continue
        if wf < 0:
            errors.append(f"{t} : poids négatif ({wf:g} %). La vente à découvert n'est pas permise.")
            continue
        if wf == 0:
            errors.append(f"{t} : poids nul. Retirez la ligne plutôt que de saisir 0 %.")
            continue
        if t in seen:
            if t not in dups:
                dups.append(t)
            continue
        seen[t] = wf
        total += wf
    for t in dups:
        errors.append(f"Actif en double : {t}. Un actif ne peut apparaître qu'une fois.")
    if not seen and not errors:
        errors.append("Le portefeuille est vide.")
    only_sum = False
    if not errors and abs(total - 100.0) > TOTAL_TOLERANCE_PTS:
        errors.append(f"La somme des poids vaut {total:.2f} % au lieu de 100 % (écart de {total - 100.0:+.2f} points).")
        only_sum = True
    return BuilderResult(weights_pct=dict(seen) if not errors else None, errors=tuple(errors), total_pct=round(total, 6),
                         n_rows=n_rows, only_sum_is_wrong=only_sum, rows_seen=dict(seen))


def normalize_to_100(weights_pct: dict) -> dict:
    """Normalisation EXPLICITE (proportionnelle) : à n'appeler que sur action de l'utilisateur."""
    total = sum(weights_pct.values())
    if total <= 0:
        raise ValueError("Impossible de normaliser : somme nulle.")
    return {t: 100.0 * w / total for t, w in weights_pct.items()}


def rows_from_weights(weights_pct: dict) -> list:
    return [{"ticker": t, "weight_pct": float(w)} for t, w in weights_pct.items()]
