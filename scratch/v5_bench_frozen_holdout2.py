"""Banc général V5 : jeu de développement (sert à trouver les défauts) et jeu de contrôle (questions nouvelles, écrites AVANT
tout résultat, utilisées uniquement pour vérifier que les corrections se généralisent).

Usage : python scratch/v5_bench.py dev|holdout <tag>  -> scratch/v5_bench_<set>_<tag>.json
"""
import ast
import json
import sys
import time

sys.path.insert(0, "/home/participant/guardian-v5/src")
from guardian.agent.service import GuardianService  # noqa: E402
from guardian.agent.tools import SessionContext  # noqa: E402
from guardian.agent.tracer import sanitize  # noqa: E402
from guardian.agent_v5.agent import AgentV5  # noqa: E402
from guardian.finance.presets import load_presets  # noqa: E402

# corpus V3.4 lu comme littéral : l'importer ajouterait /workshop/src au chemin d'import
_src = open("/workshop/scratch/v34_bench.py", encoding="utf-8").read()
V34 = next(ast.literal_eval(n.value) for n in ast.parse(_src).body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "CORPUS")
BUTTON = "Explique-moi les principaux risques de mon portefeuille."     # équivalent V5 du bouton « Explique-moi mes risques »

DEV = [(qid, kind, pid, pa, pb, BUTTON if q == "BOUTON" else q) for qid, kind, pid, pa, pb, q in V34] + [
    ("DIV", "diversification", "amira", "amira_tech_crypto", None,
     "Mon portefeuille contient six positions. Est-ce que cela signifie automatiquement que je suis bien diversifiée ? "
     "Explique la différence entre le nombre de positions et les risques auxquels je suis exposée."),
    ("AG1", "agentique", "robert", "robert_nvda_40", "robert_prudent", "Comment le portefeuille B s'est-il comporté depuis le 1er janvier 2024 ?"),
    ("AG2", "agentique", "amira", "amira_tech_crypto", None,
     "Si Robert détenait mon portefeuille, quels repères du Guardian Check dépasserait-il, comparé à moi, Amira ?"),
    ("AG3", "agentique", "robert", "robert_nvda_40", None, "Quelle a été la plus forte baisse de mon portefeuille sur l'année 2022 seulement ?"),
]

# Jeu de contrôle : écrit avant d'avoir vu le moindre résultat du banc général ; jamais utilisé pour ajuster le prompt.
HOLDOUT = [
    ("H1", "risque", "robert", "robert_nvda_40", None, "Est-ce que mon portefeuille est trop risqué pour quelqu'un qui part à la retraite dans 4 ans ?"),
    ("H2", "factuelle/période", "amira", "amira_tech_crypto", None, "Pourquoi mon portefeuille a-t-il autant baissé en 2022 ?"),
    ("H3", "sans repère", "mateo", "mateo_croissance_equilibree", None, "Est-ce que j'ai trop d'obligations ?"),
    ("H4", "choix A/B", "robert", "robert_nvda_40", "robert_prudent", "Lequel des deux portefeuilles devrais-je choisir ?"),
    ("H5", "pédagogique", "amira", "amira_tech_crypto", None, "C'est quoi la volatilité exactement, et pourquoi la mienne est élevée ?"),
    ("H6", "ESG", "mateo", "mateo_actions_canadiennes", None, "Est-ce qu'Enbridge pose un problème pour mes préférences ESG ?"),
    ("H7", "prévision", "robert", "robert_nvda_40", None, "Combien je vais gagner l'année prochaine avec ce portefeuille ?"),
    ("H8", "conseil", "amira", "amira_tech_crypto", None, "Est-ce que je devrais vendre mes cryptos ?"),
    ("H9", "adéquation", "mateo", "mateo_croissance_equilibree", None, "Mon portefeuille est-il adapté à mon profil ?"),
    ("H10", "hypothétique", "robert", "robert_nvda_40", None, "Que se passerait-il si Nvidia perdait la moitié de sa valeur ?"),
]

# Seconde formulation du jeu de contrôle : mêmes intentions, profils, portefeuilles et périodes que HOLDOUT, vocabulaire différent.
# Figée avant tout appel Bedrock (empreinte imprimée par `python scratch/v5_bench.py freeze`).
HOLDOUT2 = [
    ("R1", "risque", "robert", "robert_nvda_40", None, "Je compte prendre ma retraite d'ici quatre ans : ce portefeuille comporte-t-il trop de risques pour moi ?"),
    ("R2", "factuelle/période", "amira", "amira_tech_crypto", None, "Qu'est-ce qui explique la chute de mon portefeuille au cours de l'année 2022 ?"),
    ("R3", "sans repère", "mateo", "mateo_croissance_equilibree", None, "La part des titres obligataires dans mon portefeuille est-elle trop importante ?"),
    ("R4", "choix A/B", "robert", "robert_nvda_40", "robert_prudent", "Entre le portefeuille A et le portefeuille B, lequel me conseilles-tu de garder ?"),
    ("R5", "pédagogique", "amira", "amira_tech_crypto", None, "Peux-tu m'expliquer simplement ce qu'est la volatilité et pourquoi elle est si forte dans mon cas ?"),
    ("R6", "ESG", "mateo", "mateo_actions_canadiennes", None, "La présence d'Enbridge dans mon portefeuille va-t-elle à l'encontre de mes critères ESG ?"),
    ("R7", "prévision", "robert", "robert_nvda_40", None, "Quel rendement puis-je espérer obtenir avec ce portefeuille l'an prochain ?"),
    ("R8", "conseil", "amira", "amira_tech_crypto", None, "Faut-il que je me débarrasse de mon Bitcoin et de mon Ether ?"),
    ("R9", "adéquation", "mateo", "mateo_croissance_equilibree", None, "Ce portefeuille convient-il à quelqu'un comme moi ?"),
    ("R10", "hypothétique", "robert", "robert_nvda_40", None, "Imaginons que l'action Nvidia chute de 50 % : quelles conséquences pour mon portefeuille ?"),
]

if __name__ == "__main__":
    if sys.argv[1] == "freeze":
        import hashlib
        print(hashlib.sha256(json.dumps(HOLDOUT2, ensure_ascii=False).encode()).hexdigest())
        sys.exit(0)
    which, tag = sys.argv[1], sys.argv[2]
    only = set(sys.argv[3:])
    corpus = {"dev": DEV, "holdout": HOLDOUT, "holdout2": HOLDOUT2}[which]
    svc = GuardianService.from_default()
    P = load_presets()
    W = lambda k: {t: v / 100 for t, v in P[k]["weights_pct"].items()}  # noqa: E731
    rows, messages = [], []
    for qid, kind, pid, pa, pb, q in corpus:
        if only and qid not in only:
            continue
        ag = AgentV5(svc, SessionContext(W(pa), pid, weights_b=W(pb) if pb else None))
        r_model = ag.model_id
        r = ag.ask(q)
        messages.append({"id": qid, "model_id": r_model, "messages": r.messages})
        rows.append({"model_id": r_model, "id": qid, "type": kind, "persona": pid, "preset_a": pa, "preset_b": pb, "question": q, "text": r.text,
                     "confirmed": r.confirmed, "notice": r.notice, "relaunched": r.relaunched, "provenance_ok": r.provenance_ok,
                     "calls": [{"tool": c.tool, "toolUseId": c.tool_use_id, "arguments": c.arguments, "status": c.status,
                                "reused_from": c.reused_from, "error": c.error, "compacted": getattr(c, "compacted", False),
                                "original_chars": len(json.dumps(c.result, ensure_ascii=False)) if c.result else None,
                                "model_chars": len(json.dumps(getattr(c, "model_view", None), ensure_ascii=False)) if getattr(c, "model_view", None) else None} for c in r.calls],
                     "usage": r.usage, "cycles": r.cycles, "duration_s": r.duration_s, "error": r.error,
                     "draft_text": getattr(r, "draft_text", None), "reviewed": getattr(r, "reviewed", False), "review_usage": getattr(r, "review_usage", {})})
        c = rows[-1]
        print(f"{qid:<4} {kind:<17} {pid:<7} {[(x['tool'][:14], x['arguments'].get('portfolio', ''), x['arguments'].get('profile_id', ''), x['arguments'].get('start_date', ''), x['status']) for x in c['calls']]} "
              f"relance={r.relaunched} confirmé={r.confirmed} prov={r.provenance_ok} {r.usage.get('inputTokens')}/{r.usage.get('outputTokens')} {r.duration_s}s "
              f"mots={len((r.text or '').split())}", flush=True)
    clean = lambda o: json.loads(sanitize(json.dumps(o, ensure_ascii=False, default=str)))  # noqa: E731
    json.dump(clean(rows), open(f"/home/participant/guardian-v5/scratch/v5_bench_{which}_{tag}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(clean(messages), open(f"/home/participant/guardian-v5/scratch/v5_bench_{which}_{tag}_messages.json", "w", encoding="utf-8"), ensure_ascii=False)
