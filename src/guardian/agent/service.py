"""Façade déterministe utilisée par l'interface ET par les outils de l'agent."""
from __future__ import annotations

from dataclasses import dataclass, field

from guardian.data.loader import DataBundle, load_bundle
from guardian.finance.analysis import AnalysisResult, analyze_portfolio
from guardian.finance.panel import CadPanel, build_cad_panel
from guardian.esg.data import EsgData, empty_esg_data, load_esg_data
from guardian.esg.engine import EsgReport, evaluate_esg
from guardian.rules.engine import GuardianReport, evaluate, load_profiles, load_rules_config


@dataclass
class GuardianService:
    bundle: DataBundle
    panel: CadPanel
    rules_cfg: dict
    profiles: dict
    esg_data: EsgData = field(default_factory=empty_esg_data)
    _cache: dict = field(default_factory=dict)

    @classmethod
    def from_default(cls, data_dir=None) -> "GuardianService":
        bundle = load_bundle(data_dir)
        return cls(bundle=bundle, panel=build_cad_panel(bundle),
                   rules_cfg=load_rules_config(), profiles=load_profiles(),
                   esg_data=load_esg_data(universe_tickers=bundle.universe.index))

    def analyze(self, weights: dict, start=None, end=None, rebalance: str = "monthly") -> AnalysisResult:
        key = (tuple(sorted(weights.items())), str(start), str(end), rebalance)
        if key not in self._cache:
            self._cache[key] = analyze_portfolio(self.bundle, self.panel, weights, start or None, end or None, rebalance)
        return self._cache[key]

    def check(self, weights: dict, profile_id: str, start=None, end=None) -> tuple[AnalysisResult, GuardianReport]:
        res = self.analyze(weights, start, end)
        return res, evaluate(res, profile_id, self.rules_cfg, self.profiles)

    def compare(self, weights_a: dict, weights_b: dict, profile_id: str, start=None, end=None):
        from guardian.finance.compare import compare_portfolios
        return compare_portfolios(self, weights_a, weights_b, profile_id, start or None, end or None)

    def check_esg(self, weights: dict, profile_id: str) -> EsgReport:
        """Cohérence ESG (module distinct du Guardian Check financier). Valide d'abord les poids comme tout autre calcul."""
        from guardian.finance.portfolio import validate_weights
        w = validate_weights(weights, self.bundle.universe.index)
        return evaluate_esg(w, self.bundle.universe, profile_id, self.profiles[profile_id], self.esg_data)
