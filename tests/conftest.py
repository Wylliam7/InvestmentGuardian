"""Utilitaires de test : données synthétiques et faux modèle Strands scripté (aucun appel AWS)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from strands.models import Model

from guardian.data.loader import DataBundle
from guardian.finance.panel import build_cad_panel

REPO = Path(__file__).resolve().parents[1]


def make_universe(rows):
    df = pd.DataFrame(rows, columns=["ticker", "name", "asset_class", "market", "currency", "sector"])
    df["asset_id"] = [f"A{i}" for i in range(len(df))]
    return df.set_index("ticker")


def make_bundle(universe: pd.DataFrame, prices: dict, fx: dict) -> DataBundle:
    """prices : {ticker: {date_str: adj_close}} ; fx : {date_str: usdcad}."""
    rows = []
    for t, series in prices.items():
        for d, p in series.items():
            rows.append({"date": pd.Timestamp(d), "ticker": t, "adj_close": float(p),
                         "currency": universe.loc[t, "currency"]})
    fx_s = pd.Series({pd.Timestamp(d): float(v) for d, v in fx.items()}).sort_index()
    return DataBundle(data_dir=Path("."), universe=universe, prices=pd.DataFrame(rows), fx=fx_s,
                      sha256={"synthetic": "0" * 64}, rows={"synthetic": len(rows)})


@pytest.fixture
def synthetic_universe():
    return make_universe([
        ("AAA.TO", "Actif CAD", "equity", "TSX", "CAD", "x"),
        ("BBB", "Actif USD", "equity", "NASDAQ", "USD", "x"),
        ("CCC-USD", "Crypto", "crypto", "Crypto (24/7)", "USD", "x"),
    ])


@pytest.fixture(scope="session")
def real_service():
    from guardian.agent.service import GuardianService
    return GuardianService.from_default()


class ScriptedModel(Model):
    """Faux modèle Strands : 1er appel -> demande les outils ; 2e appel -> texte final (scénario configurable)."""

    def __init__(self, tool_calls=("evaluate_portfolio",), final_text="Résultat interprété.", tool_args=None):
        self.tool_calls = list(tool_calls)
        self.final_text = final_text
        self.tool_args = tool_args or {}
        self.n_calls = 0

    def update_config(self, **kw):
        pass

    def get_config(self):
        return {"model_id": "scripted"}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kw):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        self.n_calls += 1
        usage = {"usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}, "metrics": {"latencyMs": 1}}
        yield {"messageStart": {"role": "assistant"}}
        if self.n_calls == 1 and self.tool_calls:
            for i, name in enumerate(self.tool_calls):
                yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{i}", "name": name}}}}
                yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(self.tool_args.get(name, {}))}}}}
                yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": self.final_text}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": usage}


class StepModel(Model):
    """Faux modèle Strands à étapes. Chaque appel du modèle (= un cycle interne de Strands) consomme une étape :
    ("tools", [noms]) → demande ces outils dans le même cycle (exécution parallèle possible) ;
    ("text", "réponse") → réponse finale. `seen` mémorise, pour chaque appel, les types de blocs reçus."""

    def __init__(self, steps, tool_args=None):
        self.steps = list(steps)
        self.tool_args = tool_args or {}
        self.i = 0
        self.seen = []
        self.prompts = []          # premier message utilisateur de chaque requête

    def update_config(self, **kw):
        pass

    def get_config(self):
        return {"model_id": "steps"}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kw):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        self.seen.append([[next(iter(b)) for b in m["content"]] for m in messages])
        if len(messages) == 1:
            self.prompts.append("".join(b.get("text", "") for b in messages[0]["content"]))
        step = self.steps[self.i] if self.i < len(self.steps) else ("text", "(fin du scénario)")
        self.i += 1
        yield {"messageStart": {"role": "assistant"}}
        if step[0] == "tools":
            for k, name in enumerate(step[1]):
                yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"s{self.i}-{k}", "name": name}}}}
                yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(self.tool_args.get(name, {}))}}}}
                yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": step[1]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}, "metrics": {"latencyMs": 1}}}


def fr_pct(x, digits=1):
    """Format d'affichage V2 : virgule décimale."""
    return f"{100 * x:.{digits}f}".replace(".", ",") + " %"


V2_MAIN_LABELS = ("Rendement historique", "Fluctuations du portefeuille", "Plus forte baisse historique", "Répartition de mon portefeuille")


def v2_expected_metrics(service, weights_frac):
    r = service.analyze(weights_frac)
    return {"Rendement historique": fr_pct(r.cumulative_return), "Fluctuations du portefeuille": fr_pct(r.volatility),
            "Plus forte baisse historique": fr_pct(r.drawdown.max_drawdown),
            "Répartition de mon portefeuille": f"≈ {r.concentration.effective_n:.1f}".replace(".", ",") + " positions"}


def expected_evaluate(service, weights, profile_id="robert"):
    """Sortie attendue de l'outil evaluate_portfolio : moteur V1 inchangé + contexte FNB (V3.1)."""
    from guardian.explain.funds import fund_exposure
    from guardian.agent.tools import portfolio_key_facts
    res = service.analyze(weights)
    out = {**res.to_tool_dict(), "fund_exposure": fund_exposure(res.weights, service.bundle.universe, res.concentration.max_ticker, res.concentration.max_weight)}
    from guardian.agent.tools import active_profile_facts
    kf = {**portfolio_key_facts(out, service.bundle.universe), "profil_actif": active_profile_facts(service, profile_id)}
    return {**out, "key_facts": kf, "portfolio": "A"}


def expected_compare(service, a, b, profile_id):
    """Sortie attendue de l'outil compare_scenarios : moteur V1 inchangé + contexte FNB par portefeuille (V3.1)."""
    from guardian.explain.funds import fund_exposure
    c = service.compare(a, b, profile_id)
    out = c.to_tool_dict()
    from guardian.agent.tools import portfolio_key_facts
    for key, r, g in (("portfolio_A", c.a, "guardian_A"), ("portfolio_B", c.b, "guardian_B")):
        out[key]["fund_exposure"] = fund_exposure(r.weights, service.bundle.universe, r.concentration.max_ticker, r.concentration.max_weight)
        out[key]["key_facts"] = portfolio_key_facts({**out[key], "window": out["window"]}, service.bundle.universe, out[g]["findings"])
    out["profile"] = service.profiles[profile_id]
    return out
