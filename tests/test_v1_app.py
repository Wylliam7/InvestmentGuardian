"""Interface V1 exécutée avec Streamlit AppTest (aucun appel AWS)."""
import pytest
from streamlit.testing.v1 import AppTest

from conftest import REPO
from guardian.finance.presets import load_presets

MAIN = ("Rendement cumulé", "Rendement annualisé", "Volatilité annualisée", "Drawdown maximal")


def run_app():
    return AppTest.from_file(str(REPO / "app" / "app.py"), default_timeout=90).run()


def main_metrics(at):
    return {m.label: m.value for m in at.metric if m.label in MAIN}


def expected_metrics(service, weights_pct):
    r = service.analyze({t: w / 100 for t, w in weights_pct.items()})
    return {"Rendement cumulé": f"{100 * r.cumulative_return:.1f} %", "Rendement annualisé": f"{100 * r.annualized_return:.1f} %",
            "Volatilité annualisée": f"{100 * r.volatility:.1f} %", "Drawdown maximal": f"{100 * r.drawdown.max_drawdown:.1f} %"}


def test_header_title_subtitle_and_readable_banner():
    at = run_app()
    assert not at.exception, at.exception
    assert "Investment Guardian" in at.title[0].value
    md = " ".join(m.value for m in at.markdown)
    assert "Your decisions. Your risks. Explained." in md and "Simulation éducative — aucun conseil financier personnalisé" in md
    assert "color: #3D2C00" in md and "background: #FFF4D6" in md                      # contraste explicite du bandeau


def test_default_state_shows_robert_and_the_nvidia_scenario(real_service):
    at = run_app()
    assert at.selectbox(key="profile_id").value == "robert"
    assert main_metrics(at) == expected_metrics(real_service, {"NVDA": 40, "XBB.TO": 35, "XIU.TO": 25})
    assert at.session_state.ctx.profile_id == "robert" and at.session_state.ctx.weights_b is not None


def test_switching_profile_keeps_metrics_and_updates_agent_context():
    at = run_app()
    at.selectbox(key="preset_A").set_value("robert_prudent").run()          # choix explicite : l'allocation n'est plus remplacée automatiquement
    before = main_metrics(at)
    at.selectbox(key="profile_id").set_value("amira").run()
    assert not at.exception, at.exception
    assert main_metrics(at) == before                                                  # mêmes métriques, quel que soit le profil
    assert at.session_state.ctx.profile_id == "amira"
    assert any("Amira" in m.value and "objectifs déclarés" in m.value for m in at.markdown)


@pytest.mark.parametrize("pid", list(load_presets()))
def test_each_preset_loads_analyses_and_feeds_the_agent_context(pid, real_service):
    at = run_app()
    at.selectbox(key="preset_A").set_value(pid).run()
    assert not at.exception, at.exception
    w = load_presets()[pid]["weights_pct"]
    assert main_metrics(at) == expected_metrics(real_service, w)
    assert at.session_state.ctx.weights == {t: v / 100 for t, v in w.items()}          # l'agent voit les allocations réellement sélectionnées


def test_comparison_tab_shows_same_period_and_no_winner(real_service):
    at = run_app()
    assert not at.exception, at.exception
    caps = " ".join(c.value for c in at.caption)
    assert "exactement la même période" in caps and "aucun portefeuille n'est désigné comme meilleur" in caps
    assert any("Compromis historiques observés" in m.value for m in at.markdown)
    assert any("Volatilité annualisée plus élevée pour A" in m.value for m in at.markdown)


def test_disabling_portfolio_b_removes_it_from_the_agent_context():
    at = run_app()
    at.checkbox(key="use_b").uncheck().run()
    assert not at.exception, at.exception
    assert at.session_state.ctx.weights_b is None
    assert any("Activez le portefeuille B" in i.value for i in at.info)


def test_builder_shows_analysed_weights_and_sum():
    at = run_app()
    md = " ".join(m.value for m in at.markdown)
    assert "Poids réellement analysés" in md and "NVDA 40 %" in md and "XBB.TO 35 %" in md
    sums = [m.value for m in at.metric if m.label == "Somme des poids saisis"]
    assert sums == ["100.00 %", "100.00 %"]


def test_app_still_computes_without_bedrock_and_reports_the_outage(monkeypatch, real_service):
    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "http://127.0.0.1:9")
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "1")
    at = run_app()
    at.text_area[0].set_value("Pourquoi ce portefeuille pourrait-il être risqué pour Robert ?")
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert not at.exception, at.exception
    assert any("injoignable" in e.value or "Aucun identifiant" in e.value for e in at.error), [e.value for e in at.error]
    assert main_metrics(at) == expected_metrics(real_service, {"NVDA": 40, "XBB.TO": 35, "XIU.TO": 25})     # le moteur reste disponible
