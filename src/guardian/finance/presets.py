"""Portefeuilles fictifs prédéfinis (config/presets.yaml)."""
from __future__ import annotations

from pathlib import Path

import yaml

from guardian.data.loader import REPO_ROOT
from guardian.finance.builder import parse_weight_rows, rows_from_weights

PRESETS_PATH = REPO_ROOT / "config" / "presets.yaml"
EXPECTED_PRESET_IDS = ("robert_prudent", "robert_nvda_40", "amira_croissance", "amira_tech_crypto")


class PresetError(Exception):
    pass


def load_presets(path: Path | None = None) -> dict:
    cfg = yaml.safe_load((path or PRESETS_PATH).read_text(encoding="utf-8")) or {}
    presets = cfg.get("presets")
    if not presets:
        raise PresetError("presets.yaml : aucun portefeuille défini")
    return presets


def load_profile_defaults(path: Path | None = None) -> dict:
    """{profil: {"a": id_préréglage, "b": id_préréglage}} — scénarios suggérés par profil."""
    cfg = yaml.safe_load((path or PRESETS_PATH).read_text(encoding="utf-8")) or {}
    return cfg.get("profile_defaults") or {}


def validate_profile_defaults(defaults: dict, presets: dict, profiles: dict) -> None:
    for pid in profiles:
        d = defaults.get(pid)
        if not d or d.get("a") not in presets or d.get("b") not in presets:
            raise PresetError(f"profile_defaults : scénarios A/B manquants ou inconnus pour le profil {pid!r}")


def validate_presets(presets: dict, known_tickers, profiles: dict) -> None:
    """Chaque préréglage : actifs connus, poids > 0, somme EXACTEMENT 100, profil suggéré existant."""
    for pid, p in presets.items():
        w = p["weights_pct"]
        if sum(w.values()) != 100:
            raise PresetError(f"{pid} : la somme des poids vaut {sum(w.values())} au lieu de 100")
        res = parse_weight_rows(rows_from_weights(w), known_tickers)
        if not res.valid:
            raise PresetError(f"{pid} : {'; '.join(res.errors)}")
        if p.get("profile_id") not in profiles:
            raise PresetError(f"{pid} : profil suggéré inconnu {p.get('profile_id')!r}")
