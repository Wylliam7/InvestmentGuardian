"""Parcours Amira (diversification) sur le vrai Nova 2 Lite : N exécutions indépendantes, code inchangé entre les exécutions.
Écrit scratch/v5_live_amira.json (réponses, appels, toolUseId) et scratch/v5_live_amira_messages.json (historique Strands complet, masqué)."""
import json
import sys

sys.path.insert(0, "/home/participant/guardian-v5/src")
from guardian.agent.service import GuardianService  # noqa: E402
from guardian.agent.tools import SessionContext  # noqa: E402
from guardian.agent.tracer import sanitize  # noqa: E402
from guardian.agent_v5.agent import AgentV5  # noqa: E402

A = {"NVDA": .25, "TSLA": .15, "QQQ": .25, "SHOP.TO": .05, "BTC-USD": .20, "ETH-USD": .10}
Q = ("Mon portefeuille contient six positions. Est-ce que cela signifie automatiquement que je suis bien diversifiée ? "
     "Explique la différence entre le nombre de positions et les risques auxquels je suis exposée.")
svc = GuardianService.from_default()
rows, msgs = [], []
for i in range(int(sys.argv[1]) if len(sys.argv) > 1 else 5):
    r = AgentV5(svc, SessionContext(dict(A), "amira")).ask(Q)            # agent neuf : exécutions indépendantes
    row = {"run": i + 1, "relaunched": r.relaunched, "confirmed": r.confirmed, "notice": r.notice, "provenance_ok": r.provenance_ok,
           "calls": [{"id": c.id, "tool": c.tool, "toolUseId": c.tool_use_id, "arguments": c.arguments, "status": c.status,
                      "reused_from": c.reused_from, "duration_ms": c.duration_ms, "error": c.error} for c in r.calls],
           "model_tool_uses": r.model_tool_uses, "sdk_tool_counts": r.sdk_tool_counts, "computed": r.computed,
           "usage": r.usage, "cycles": r.cycles, "duration_s": r.duration_s, "text": r.text, "error": r.error}
    rows.append(row)
    msgs.append({"run": i + 1, "messages": r.messages})
    print(f"run {i + 1}: appels={[(c['tool'], c['toolUseId'], c['status'], c['reused_from']) for c in row['calls']]} relance={r.relaunched} "
          f"confirmé={r.confirmed} provenance={r.provenance_ok} cycles={r.cycles} jetons={r.usage.get('inputTokens')}/{r.usage.get('outputTokens')} "
          f"{r.duration_s}s", flush=True)
clean = lambda o: json.loads(sanitize(json.dumps(o, ensure_ascii=False, default=str)))  # noqa: E731
json.dump(clean(rows), open("/home/participant/guardian-v5/scratch/v5_live_amira.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(clean(msgs), open("/home/participant/guardian-v5/scratch/v5_live_amira_messages.json", "w", encoding="utf-8"), ensure_ascii=False)
