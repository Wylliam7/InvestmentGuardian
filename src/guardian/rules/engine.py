"""Guardian Check — règles déterministes, configurables, testables sans IA ni AWS.

Statuts : OK, ATTENTION, CONFLIT. Seuil franchi quand mesure STRICTEMENT supérieure au seuil.
Tous les seuils sont des heuristiques pédagogiques (voir config/guardian_rules.yaml).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from guardian.data.loader import REPO_ROOT
from guardian.finance.analysis import AnalysisResult

CONFIG_DIR = REPO_ROOT / "config"
OK, ATTENTION, CONFLIT = "OK", "ATTENTION", "CONFLIT"
SUPPORTED_RULES = ("R1", "R2", "R4", "R5")


class ConfigError(Exception):
    """Configuration des règles ou des profils invalide."""


@dataclass(frozen=True)
class Finding:
    rule_id: str
    title: str
    status: str
    measured: float
    unit: str
    threshold_attention: float
    threshold_conflict: float
    profile_id: str
    justification: str
    method: str
    limitations: tuple
    heuristic: bool
    config_version: str
    evidence: dict = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["limitations"] = list(self.limitations)
        d["measured_pct"] = round(100 * self.measured, 2)
        d["threshold_attention_pct"] = round(100 * self.threshold_attention, 2)
        d["threshold_conflict_pct"] = round(100 * self.threshold_conflict, 2)
        return d


@dataclass(frozen=True)
class GuardianReport:
    profile_id: str
    profile_name: str
    config_version: str
    findings: tuple
    general_limitations: tuple
    missing_information: tuple

    def counts(self) -> dict:
        c = {OK: 0, ATTENTION: 0, CONFLIT: 0}
        for f in self.findings:
            c[f.status] += 1
        return c

    def to_dict(self) -> dict:
        return {"status": "ok", "profile_id": self.profile_id, "profile_name": self.profile_name,
                "config_version": self.config_version, "thresholds_are_heuristics": True,
                "counts": self.counts(), "findings": [f.to_dict() for f in self.findings],
                "general_limitations": list(self.general_limitations),
                "missing_information": list(self.missing_information)}


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        raise ConfigError(f"Lecture de {path.name} impossible : {e}") from e


def load_profiles(path: Path | None = None) -> dict:
    cfg = _load_yaml(path or CONFIG_DIR / "profiles.yaml")
    profiles = cfg.get("profiles")
    if not profiles:
        raise ConfigError("profiles.yaml : aucun profil défini")
    return profiles


def load_rules_config(path: Path | None = None) -> dict:
    cfg = _load_yaml(path or CONFIG_DIR / "guardian_rules.yaml")
    validate_rules_config(cfg)
    return cfg


def validate_rules_config(cfg: dict) -> None:
    if not isinstance(cfg.get("volatile_asset_vol_threshold"), (int, float)) or cfg["volatile_asset_vol_threshold"] <= 0:
        raise ConfigError("volatile_asset_vol_threshold doit être un nombre positif")
    rules = cfg.get("rules") or {}
    for rid in SUPPORTED_RULES:
        if rid not in rules:
            raise ConfigError(f"Règle {rid} absente de la configuration")
        r = rules[rid]
        for key in ("title", "justification", "method", "thresholds"):
            if key not in r:
                raise ConfigError(f"Règle {rid} : champ '{key}' manquant")
        for prof, th in r["thresholds"].items():
            a, c = th.get("attention"), th.get("conflict")
            if not all(isinstance(x, (int, float)) for x in (a, c)) or not (0 <= a < c <= 1):
                raise ConfigError(f"Règle {rid}/{prof} : il faut 0 <= attention < conflit <= 1")


def classify(measured: float, attention: float, conflict: float) -> str:
    if measured > conflict:
        return CONFLIT
    if measured > attention:
        return ATTENTION
    return OK


def volatile_assets(result: AnalysisResult, vol_threshold: float) -> list:
    return [a for a in result.assets if a.asset_class == "crypto" or a.annualized_vol > vol_threshold]


def evaluate(result: AnalysisResult, profile_id: str, rules_cfg: dict | None = None,
             profiles: dict | None = None) -> GuardianReport:
    cfg = rules_cfg or load_rules_config()
    profs = profiles or load_profiles()
    if profile_id not in profs:
        raise ConfigError(f"Profil inconnu : {profile_id!r}. Profils disponibles : {sorted(profs)}")
    version = str(cfg.get("version", "?"))
    vol_thr = float(cfg["volatile_asset_vol_threshold"])
    vol_assets = volatile_assets(result, vol_thr)

    measures = {
        "R1": (result.concentration.max_weight,
               {"largest_position": result.concentration.max_ticker,
                "weights_pct": {t: round(100 * w, 2) for t, w in result.weights.items()}}),
        "R2": (sum(a.weight for a in vol_assets),
               {"volatile_assets": [{"ticker": a.ticker, "weight_pct": round(100 * a.weight, 2),
                                     "annualized_volatility_pct": round(100 * a.annualized_vol, 2),
                                     "asset_class": a.asset_class} for a in vol_assets],
                "asset_volatility_threshold_pct": round(100 * vol_thr, 2)}),
        "R4": (result.volatility, {"factor": round(result.factor, 2), "n_observations": result.n_obs}),
        "R5": (abs(result.drawdown.max_drawdown),
               {"peak_date": str(result.drawdown.peak_date.date()),
                "trough_date": str(result.drawdown.trough_date.date()),
                "recovered": result.drawdown.recovered,
                "underwater_days": result.drawdown.underwater_days}),
    }
    findings = []
    for rid in SUPPORTED_RULES:
        rcfg = cfg["rules"][rid]
        th = rcfg["thresholds"].get(profile_id)
        if th is None:
            raise ConfigError(f"Règle {rid} : aucun seuil défini pour le profil {profile_id!r}")
        measured, evidence = measures[rid]
        status = classify(measured, th["attention"], th["conflict"])
        summary = (f"{rcfg['title']} : {100 * measured:.1f} % mesuré ; "
                   f"seuils heuristiques {100 * th['attention']:.0f} % (attention) et "
                   f"{100 * th['conflict']:.0f} % (conflit) pour {profs[profile_id]['display_name']} → {status}.")
        findings.append(Finding(
            rule_id=rid, title=rcfg["title"], status=status, measured=float(measured), unit=rcfg.get("unit", ""),
            threshold_attention=float(th["attention"]), threshold_conflict=float(th["conflict"]),
            profile_id=profile_id, justification=" ".join(str(rcfg["justification"]).split()),
            method=str(rcfg["method"]), limitations=tuple(rcfg.get("limitations", [])),
            heuristic=True, config_version=version, evidence=evidence, summary=summary))
    return GuardianReport(profile_id=profile_id, profile_name=profs[profile_id]["display_name"],
                          config_version=version, findings=tuple(findings),
                          general_limitations=tuple(cfg.get("general_limitations", [])),
                          missing_information=tuple(cfg.get("missing_information", [])))
