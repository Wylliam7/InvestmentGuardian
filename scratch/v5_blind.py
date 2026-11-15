"""Anonymise les réponses Nova 2 Lite / Haiku 4.5 avant relecture : ordre aléatoire X/Y par question, sans nom de modèle,
sans jetons ni toolUseId, mise en forme Markdown retirée. La clé est écrite à part (scratch/v5_blind_key.json)."""
import json, random, re
random.seed(20261115)
pairs = [("dev", "v2", "haiku45"), ("holdout2", "nova2lite", "haiku45")]
blind, key = [], {}
for which, nova_tag, haiku_tag in pairs:
    n = {r["id"]: r for r in json.load(open(f"scratch/v5_bench_{which}_{nova_tag}.json"))}
    h = {r["id"]: r for r in json.load(open(f"scratch/v5_bench_{which}_{haiku_tag}.json"))}
    for qid in n:
        items = [("nova2lite", n[qid]), ("haiku45", h[qid])]
        random.shuffle(items)
        entry = {"id": f"{which}:{qid}", "question": n[qid]["question"], "persona": n[qid]["persona"], "preset_a": n[qid]["preset_a"], "preset_b": n[qid]["preset_b"]}
        for label, (model, r) in zip("XY", items):
            text = re.sub(r"\*\*|__|^#+\s*", "", r["text"] or "", flags=re.M)
            entry[label] = {"tools": [(c["tool"], {k: v for k, v in c["arguments"].items() if v}) for c in r["calls"]], "relaunched": r["relaunched"], "text": text}
            key[f"{which}:{qid}:{label}"] = model
        blind.append(entry)
json.dump(blind, open("scratch/v5_blind_answers.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(key, open("scratch/v5_blind_key.json", "w", encoding="utf-8"))
print(len(blind), "questions anonymisées")
