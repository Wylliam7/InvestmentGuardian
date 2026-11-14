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

    def __init__(self, steps):
        self.steps = list(steps)
        self.i = 0
        self.seen = []

    def update_config(self, **kw):
        pass

    def get_config(self):
        return {"model_id": "steps"}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kw):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        self.seen.append([[next(iter(b)) for b in m["content"]] for m in messages])
        step = self.steps[self.i] if self.i < len(self.steps) else ("text", "(fin du scénario)")
        self.i += 1
        yield {"messageStart": {"role": "assistant"}}
        if step[0] == "tools":
            for k, name in enumerate(step[1]):
                yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"s{self.i}-{k}", "name": name}}}}
                yield {"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}
                yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": step[1]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}, "metrics": {"latencyMs": 1}}}
