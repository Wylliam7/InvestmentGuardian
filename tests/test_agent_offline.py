"""Agent, outils, trace et garde-fous — sans aucun appel AWS (faux modèle scripté)."""
import json

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

from conftest import ScriptedModel
from guardian.agent.agent import GuardianAgent, evaluate_turn, map_error
from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer, sanitize

WEIGHTS = {"NVDA": .40, "XBB.TO": .35, "XIU.TO": .25}


def make_agent(service, model, fail=()):
    ctx = SessionContext(weights=WEIGHTS, profile_id="robert", fail_tools=set(fail))
    return GuardianAgent(service, ctx, Tracer(), model_factory=lambda: model)


# ---------------------------------------------------------------- schémas d'outils (leçon phase 0)
def test_tool_schemas_expose_real_parameters(real_service):
    tools = build_tools(real_service, SessionContext(WEIGHTS, "robert"), Tracer())
    specs = {t.tool_spec["name"]: t.tool_spec["inputSchema"]["json"]["properties"] for t in tools}
    assert set(specs) == {"evaluate_portfolio", "check_profile_constraints"}
    assert set(specs["evaluate_portfolio"]) == {"start_date", "end_date"}
    assert set(specs["check_profile_constraints"]) == {"profile_id", "start_date", "end_date"}


# ---------------------------------------------------------------- appel réel d'outil et trace fidèle
def test_agent_calls_real_tool_and_trace_matches_execution(real_service):
    ag = make_agent(real_service, ScriptedModel(["evaluate_portfolio", "check_profile_constraints"],
                                                final_text="Interprétation sans chiffre."))
    tr = ag.ask("Pourquoi ce portefeuille pourrait-il être risqué pour Robert ?")
    assert not tr.withheld and tr.error is None
    by_tool = {r.tool: r for r in tr.tool_records}       # Strands peut exécuter les outils en parallèle : l'ordre n'est pas garanti
    assert sorted(by_tool) == ["check_profile_constraints", "evaluate_portfolio"] and len(tr.tool_records) == 2
    ev = by_tool["evaluate_portfolio"]
    # la trace correspond à l'exécution : le résultat tracé est exactement celui du moteur
    expected = real_service.analyze(WEIGHTS).to_tool_dict()
    assert ev.status == "ok" and ev.result == expected
    assert ev.arguments == {"start_date": "", "end_date": ""}
    assert ev.duration_ms > 0 and ev.result_digest and ev.started_at
    assert set(ev.data_refs["files_sha256_prefix"]) == {"assets_universe.csv", "prices_daily.csv", "fx_usdcad_daily.csv"}
    assert ev.data_refs["window"]["n_observations"] == 1228
    chk = by_tool["check_profile_constraints"]
    assert sum(chk.result["counts"].values()) == 4 and len(chk.result["findings"]) == 4
    assert chk.arguments == {"profile_id": "robert", "start_date": "", "end_date": ""}
    json.dumps(ag.tracer.export())     # exportable


def test_trace_contains_no_secret_patterns(real_service):
    ag = make_agent(real_service, ScriptedModel(["evaluate_portfolio"]))
    ag.ask("test")
    blob = json.dumps(ag.tracer.export())
    for pat in ("AKIA", "ASIA", "aws_secret", "session_token"):
        assert pat not in blob


# ---------------------------------------------------------------- test 8 : panne d'outil
def test_tool_failure_is_recorded_and_unvalidated_numbers_are_withheld(real_service):
    # le faux modèle « improvise » un chiffre après l'échec de l'outil, exactement le comportement observé en phase 0
    model = ScriptedModel(["evaluate_portfolio"], final_text="La volatilité est de 12,3 % (calcul direct).")
    ag = make_agent(real_service, model, fail={"evaluate_portfolio"})
    tr = ag.ask("Quel est le risque ?")
    assert len(tr.tool_records) == 1 and tr.tool_records[0].status == "error"
    assert "Panne simulée" in tr.tool_records[0].error
    assert tr.withheld and tr.text is None and "incomplète" in tr.withheld_reason
    assert "12,3" not in json.dumps(tr.__dict__, default=str)          # le chiffre improvisé n'est nulle part dans le résultat
    # le moteur reste utilisable et ses chiffres sont inchangés
    assert real_service.analyze(WEIGHTS).volatility > 0
    # la réponse retenue n'est pas réinjectée dans la conversation
    assert "12,3" not in json.dumps(ag._agent.messages, default=str)


def test_answer_with_numbers_but_no_tool_is_withheld(real_service):
    ag = make_agent(real_service, ScriptedModel([], final_text="Le rendement est de 45 % par an."))
    tr = ag.ask("Quel rendement ?")
    assert tr.tool_records == [] and tr.withheld and "chiffres" in tr.withheld_reason


def test_answer_without_numbers_or_tool_gets_caveat(real_service):
    ag = make_agent(real_service, ScriptedModel([], final_text="Bonjour, comment puis-je vous aider ?"))
    tr = ag.ask("Bonjour")
    assert not tr.withheld and tr.caveat and "Aucun outil" in tr.caveat


def test_unknown_tool_requested_by_model_is_not_presented_as_validated(real_service):
    ag = make_agent(real_service, ScriptedModel(["outil_inexistant"], final_text="Le risque est de 30 %."))
    tr = ag.ask("?")
    assert tr.withheld            # le SDK signale l'erreur, notre journal n'a rien : réponse retenue


def test_evaluate_turn_logic():
    class R:  # enregistrement minimal
        def __init__(self, tool, status): self.tool, self.status = tool, status
    assert evaluate_turn("x 1", [R("a", "error")], {})[0]
    assert evaluate_turn("x 1", [R("a", "ok")], {"a": {"calls": 1, "errors": 0}})[0] is False
    assert evaluate_turn("x 1", [R("a", "ok")], {"a": {"calls": 2, "errors": 0}})[0]      # appel SDK non tracé
    assert evaluate_turn("x 1", [R("a", "ok")], {"a": {"calls": 1, "errors": 1}})[0]


# ---------------------------------------------------------------- test 9 : AWS indisponible
@pytest.mark.parametrize("exc,kind", [
    (ClientError({"Error": {"Code": "ExpiredTokenException", "Message": "x"}}, "Converse"), "credentials_expired"),
    (ClientError({"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "Converse"), "access_denied"),
    (ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "Converse"), "throttling"),
    (ClientError({"Error": {"Code": "ValidationException", "Message": "x"}}, "Converse"), "model_error"),
    (NoCredentialsError(), "no_credentials"),
    (EndpointConnectionError(endpoint_url="https://bedrock-runtime.invalid"), "network"),
    (RuntimeError("boum"), "unknown"),
])
def test_aws_errors_are_mapped_and_engine_stays_available(real_service, exc, kind):
    def broken():
        raise exc
    ctx = SessionContext(WEIGHTS, "robert")
    ag = GuardianAgent(real_service, ctx, Tracer(), model_factory=broken)
    tr = ag.ask("Pourquoi ?")
    assert tr.error and tr.error["kind"] == kind and tr.text is None and tr.withheld
    assert tr.error["exception"] == type(exc).__name__          # le type réel n'est pas masqué
    res, rep = real_service.check(WEIGHTS, "robert")             # moteur et Guardian Check intacts
    assert res.n_obs == 1228 and len(rep.findings) == 4


def test_error_detail_is_sanitized():
    e = RuntimeError("clé AKIAABCDEFGHIJKLMNOP et aws_secret_access_key=abc123 jeton " + "A" * 60)
    d = map_error(e)["detail"]
    assert "AKIA" not in d and "abc123" not in d and "A" * 40 not in d
    assert "[masqué]" in sanitize("Bearer abcdefghijklmnopqrstuvwxyz0123")
