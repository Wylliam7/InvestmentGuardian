"""Guardian Check — règles déterministes, configurables, testables sans IA ni AWS.

Statuts : OK (affiché « Conforme »), ATTENTION, CONFLIT, INFO.
- Règles « max » (R1, R2, R4, R5) : seuil franchi quand la mesure est STRICTEMENT supérieure au seuil.
- Règles « min » (R7) : seuil franchi quand la mesure est STRICTEMENT inférieure au seuil.
Tous les seuils sont des heuristiques pédagogiques (voir config/guardian_rules.yaml), pas des normes.
Les constats décrivent un conflit POTENTIEL avec les objectifs déclarés du persona ; ils ne présument pas
de la tolérance personnelle réelle de l'investisseur.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from guardian.data.loader import REPO_ROOT
from guardian.finance.analysis import AnalysisResult

CONFIG_DIR = REPO_ROOT / "config"
OK, ATTENTION, CONFLIT, INFO = "OK", "ATTENTION", "CONFLIT", "INFO"
STATUS_LABELS = {OK: "Conforme", ATTENTION: "Attention", CONFLIT: "Conflit", INFO: "Information"}
SUPPORTED_RULES = ("R1", "R2", "R4", "R5", "R7")


class ConfigError(Exception):
    """Configuration des règles ou des profils invalide."""


@dataclass(frozen=True)
class Finding:
    rule_id: str
    title: str
    status: str
    measured: float | None
    unit: str
    threshold_attention: float | None
    threshold_conflict: float | None
    profile_id: str
    justification: str
    method: str
    limitations: tuple
    heuristic: bool
    config_version: str
    direction: str = "max"
    value_kind: str = "fraction"
    evidence: dict = field(default_factory=dict)
    summary: str = ""
    display: dict = field(default_factory=dict)     # textes prêts à afficher : measured, attention, conflict

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["limitations"] = list(self.limitations)
        d["status_label"] = self.status_label
        if self.value_kind == "fraction":
            for k in ("measured", "threshold_attention", "threshold_conflict"):
                d[k + "_pct"] = None if d[k] is None else round(100 * d[k], 2)
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
        c = {OK: 0, ATTENTION: 0, CONFLIT: 0, INFO: 0}
        for f in self.findings:
            c[f.status] += 1
        return c

    def by_id(self) -> dict:
        return {f.rule_id: f for f in self.findings}

    def to_dict(self) -> dict:
        return {"status": "ok", "profile_id": self.profile_id, "profile_name": self.profile_name,
                "config_version": self.config_version, "thresholds_are_heuristics": True,
                "wording": "Un statut Conflit signale un conflit POTENTIEL avec les objectifs déclarés du persona, "
                           "selon des seuils heuristiques du prototype ; ce n'est ni une norme ni une conclusion absolue.",
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
        for key in ("title", "justification", "method", "thresholds", "direction", "value_kind"):
            if key not in r:
                raise ConfigError(f"Règle {rid} : champ '{key}' manquant")
        if r["direction"] not in ("max", "min") or r["value_kind"] not in ("fraction", "count"):
            raise ConfigError(f"Règle {rid} : direction ('max'|'min') ou value_kind ('fraction'|'count') invalide")
        for prof, th in r["thresholds"].items():
            a, c = th.get("attention"), th.get("conflict")
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, c)):
                raise ConfigError(f"Règle {rid}/{prof} : seuils numériques requis")
            if r["direction"] == "max":
                ok = 0 <= a < c and (c <= 1 or r["value_kind"] == "count")
                if not ok:
                    raise ConfigError(f"Règle {rid}/{prof} : il faut 0 <= attention < conflit (<= 1 pour une fraction)")
            else:
                if not (0 < c < a):
                    raise ConfigError(f"Règle {rid}/{prof} : pour une règle 'min', il faut 0 < conflit < attention")
    if "R10" not in (cfg.get("info_rules") or {}):
        raise ConfigError("info_rules.R10 absente de la configuration")


def classify(measured: float, attention: float, conflict: float, direction: str = "max") -> str:
    if direction == "min":
        if measured < conflict:
            return CONFLIT
        if measured < attention:
            return ATTENTION
        return OK
    if measured > conflict:
        return CONFLIT
    if measured > attention:
        return ATTENTION
    return OK


def volatile_assets(result: AnalysisResult, vol_threshold: float) -> list:
    return [a for a in result.assets if a.asset_class == "crypto" or a.annualized_vol > vol_threshold]


def _fmt(value: float, kind: str) -> str:
    return f"{100 * value:.1f} %" if kind == "fraction" else f"{value:.1f} positions effectives"


def _fmt_threshold(value: float, kind: str, direction: str) -> str:
    op = ">" if direction == "max" else "<"
    return f"{op} {100 * value:.0f} %" if kind == "fraction" else f"{op} {value:g}"


def _phrase(status: str, name: str) -> str:
    if status == CONFLIT:
        return f"Conflit potentiel avec les objectifs déclarés de {name}, selon les seuils heuristiques du prototype."
    if status == ATTENTION:
        return f"Point d'attention pour {name}, selon les seuils heuristiques du prototype."
    return f"Aucun seuil heuristique du prototype n'est franchi pour {name}."


def tech_share(result: AnalysisResult, tech_sectors) -> tuple[float, list, float]:
    """Part des positions dont l'étiquette sectorielle est technologique + poids des FNB non décomposés."""
    tech = [a for a in result.assets if getattr(a, "sector", "") in set(tech_sectors)]
    qqq = sum(a.weight for a in result.assets if a.ticker == "QQQ")
    return sum(a.weight for a in tech), [a.ticker for a in tech], qqq


def evaluate(result: AnalysisResult, profile_id: str, rules_cfg: dict | None = None,
             profiles: dict | None = None) -> GuardianReport:
    cfg = rules_cfg or load_rules_config()
    profs = profiles or load_profiles()
    if profile_id not in profs:
        raise ConfigError(f"Profil inconnu : {profile_id!r}. Profils disponibles : {sorted(profs)}")
    name = profs[profile_id]["display_name"]
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
        "R7": (result.concentration.effective_n,
               {"hhi": round(result.concentration.hhi, 4), "n_positions": len(result.weights)}),
    }
    findings = []
    for rid in SUPPORTED_RULES:
        rcfg = cfg["rules"][rid]
        th = rcfg["thresholds"].get(profile_id)
        if th is None:
            raise ConfigError(f"Règle {rid} : aucun seuil défini pour le profil {profile_id!r}")
        direction, kind = rcfg["direction"], rcfg["value_kind"]
        measured, evidence = measures[rid]
        status = classify(round(float(measured), 9), th["attention"], th["conflict"], direction)   # arrondi : évite un faux franchissement par erreur de virgule flottante
        display = {"measured": _fmt(measured, kind),
                   "attention": _fmt_threshold(th["attention"], kind, direction),
                   "conflict": _fmt_threshold(th["conflict"], kind, direction),
                   "phrase": _phrase(status, name)}
        summary = (f"{rcfg['title']} : {display['measured']} (seuils heuristiques : attention {display['attention']}, "
                   f"conflit {display['conflict']}). {_phrase(status, name)}")
        findings.append(Finding(
            rule_id=rid, title=rcfg["title"], status=status, measured=float(measured), unit=rcfg.get("unit", ""),
            threshold_attention=float(th["attention"]), threshold_conflict=float(th["conflict"]),
            profile_id=profile_id, justification=" ".join(str(rcfg["justification"]).split()),
            method=str(rcfg["method"]), limitations=tuple(rcfg.get("limitations", [])),
            heuristic=True, config_version=version, direction=direction, value_kind=kind,
            evidence=evidence, summary=summary, display=display))

    # R10 : information, sans seuil
    r10 = cfg["info_rules"]["R10"]
    ev10 = {"window_years": round(result.years, 2), "n_observations": result.n_obs,
            "etf_positions_not_decomposed": [a.ticker for a in result.assets if a.asset_class.startswith("etf")]}
    text = [f"Analyse sur {result.years:.1f} an(s), {result.n_obs} dates communes ; les FNB ne sont pas décomposés en titres."]
    shown = None
    if profs[profile_id].get("show_sector_context"):
        share, tickers, qqq = tech_share(result, cfg.get("tech_sectors", []))
        ev10.update({"tech_share_pct": round(100 * share, 2), "tech_positions": tickers, "qqq_weight_pct": round(100 * qqq, 2),
                     "tech_sectors": list(cfg.get("tech_sectors", []))})
        shown = share
        text.append(f"Part de positions étiquetées technologie ou communication : {100 * share:.1f} % ({', '.join(tickers) or 'aucune'})"
                    + (f", plus {100 * qqq:.1f} % en QQQ, FNB de croissance fortement technologique non décomposé" if qqq else "")
                    + f". {name} souhaite éviter une concentration exclusivement technologique ; aucun seuil n'est appliqué à cette part en V1.")
    findings.append(Finding(
        rule_id="R10", title=r10["title"], status=INFO, measured=shown, unit="fraction du portefeuille" if shown is not None else "",
        threshold_attention=None, threshold_conflict=None, profile_id=profile_id,
        justification=" ".join(str(r10["justification"]).split()), method=str(r10["method"]),
        limitations=tuple(r10.get("limitations", [])), heuristic=True, config_version=version, direction="none",
        value_kind="fraction", evidence=ev10, summary=" ".join(text),
        display={"measured": "" if shown is None else f"{100 * shown:.1f} %", "attention": "", "conflict": ""}))
    return GuardianReport(profile_id=profile_id, profile_name=name, config_version=version, findings=tuple(findings),
                          general_limitations=tuple(cfg.get("general_limitations", [])),
                          missing_information=tuple(cfg.get("missing_information", [])))
