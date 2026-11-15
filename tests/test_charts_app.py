"""Graphiques = vrais résultats ; application Streamlit exécutée avec AppTest, y compris AWS indisponible."""
import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from charts import allocation_figure, drawdown_figure, performance_figure
from conftest import REPO, fr_pct, v2_expected_metrics

WEIGHTS = {"NVDA": .40, "XBB.TO": .35, "XIU.TO": .25}


def test_charts_plot_the_computed_series(real_service):
    res = real_service.analyze(WEIGHTS)
    perf = performance_figure(res)
    port = perf.data[0]
    assert np.allclose(np.array(port.y), 100 * res.value.to_numpy() / res.value.iloc[0])
    assert list(port.x) == list(res.value.index.to_pydatetime())
    for tr, t in zip(perf.data[1:], res.asset_prices_cad.columns):
        p = res.asset_prices_cad[t]
        assert tr.name == t and np.allclose(np.array(tr.y), 100 * p.to_numpy() / p.iloc[0])
    dd = drawdown_figure(res).data[0]
    assert np.isclose(min(dd.y), 100 * res.drawdown.max_drawdown)
    alloc = allocation_figure(res).data[0]
    assert dict(zip(alloc.labels, alloc.values)) == pytest.approx({"NVDA": 40.0, "XBB.TO": 35.0, "XIU.TO": 25.0})


def _run_app():
    at = AppTest.from_file(str(REPO / "app" / "app.py"), default_timeout=60)
    return at.run()


def test_app_renders_engine_results_without_aws(monkeypatch, real_service):
    # AWS injoignable : point de terminaison local fermé, une seule tentative
    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "http://127.0.0.1:9")
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("AWS_RETRY_MODE", "standard")
    at = _run_app()
    assert not at.exception, at.exception
    res = real_service.analyze(WEIGHTS)
    metrics = {m.label: m.value for m in at.metric}
    exp = v2_expected_metrics(real_service, WEIGHTS)
    assert {k: metrics[k] for k in exp} == exp                                # valeurs identiques à celles du moteur (libellés V2)
    assert any("Simulation éducative" in m.value for m in at.markdown)
    # le bouton de question : AWS est indisponible → erreur explicite, indicateurs conservés
    at.text_area[0].set_value("Pourquoi ce portefeuille pourrait-il être risqué pour Robert ?")
    form_btn = [b for b in at.button if "Poser la question" in b.label][0]
    form_btn.click()
    at.run()
    assert not at.exception, at.exception
    assert any("Amazon Bedrock est injoignable" in e.value or "Aucun identifiant" in e.value for e in at.error), [e.value for e in at.error]
    assert {m.label: m.value for m in at.metric}["Fluctuations du portefeuille"] == fr_pct(res.volatility)


def test_app_tool_failure_shows_incomplete_analysis_and_no_model_text(monkeypatch):
    """Panne d'outil simulée + faux modèle qui improvise un chiffre : rien d'improvisé ne doit être affiché."""
    from conftest import ScriptedModel
    from guardian.agent_v5 import agent as agent_mod
    model = ScriptedModel(["evaluate_portfolio"], final_text="La volatilité est de 12,3 % (calcul direct).")
    original = agent_mod.AgentV5.__init__

    def patched(self, *a, **kw):
        kw["model_factory"] = lambda: model
        original(self, *a, **kw)
    monkeypatch.setattr(agent_mod.AgentV5, "__init__", patched)
    at = _run_app()
    next(c for c in at.sidebar.checkbox if "Simuler une panne" in c.label).check()
    at.run()
    at.text_area[0].set_value("Quel est le risque ?")
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert not at.exception, at.exception
    assert any("Analyse incomplète" in w.value for w in at.warning), [w.value for w in at.warning]
    rendered = " ".join(m.value for m in at.markdown) + " ".join(w.value for w in at.warning)
    assert "12,3" not in rendered
    assert any("Au moins un outil a échoué" in w.value for w in at.warning)
    # les indicateurs du moteur restent présents
    assert {m.label: m.value for m in at.metric}["Rendement historique"].endswith("%")
