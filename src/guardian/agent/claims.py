"""Contrôle déterministe des affirmations ESSENTIELLES d'un texte généré par le modèle, contre les sorties d'outils de la requête.

Ce contrôle est PARTIEL et le dit : il couvre des catégories d'affirmations nommées (voir CHECKED / NOT_CHECKED), pas toutes les phrases.
Principe : un pourcentage n'est plus accepté parce que le même nombre existe « quelque part » dans les résultats ; il est rattaché à l'ancre la plus proche
de sa phrase (un titre, un indicateur financier, une catégorie ESG) et doit figurer parmi les valeurs de CETTE ancre.
Aucun appel au modèle, aucun réseau : uniquement des règles écrites et testées. Un manque de précision est toujours préférable à une fausse alerte
silencieuse, donc les doutes (ancre ambiguë, négation dans la phrase) ne produisent pas de violation.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

CHECKED = (
    "valeurs numériques rattachées à un titre, à un indicateur financier ou à une catégorie ESG (lorsque le rattachement est identifiable dans la phrase)",
    "identité, âge, horizon et niveau de risque du persona",
    "distinctions ESG : exclusion ou observation, environnement/social ou gouvernance, conflit, information complémentaire ou insuffisante",
    "absence de résultat présentée comme conformité ESG",
    "seuils ESG (inexistants)",
    "actifs vérifiés, FNB non évaluables et actifs sans objet pour le critère",
    "statuts du Guardian Check (R1, R2, R4, R5, R7) lorsque le critère, le profil et le portefeuille sont identifiables, et nombres de conflits ou de points de vigilance annoncés",
    "ordres d'achat ou de vente",
    "caractéristiques ou émotions du persona absentes de son profil",
)
NOT_CHECKED = (
    "la justification d'une interprétation ou d'une conclusion",
    "les qualificatifs (« élevé », « important », « modéré ») hors des catégories ci-dessus",
    "les pourcentages sans titre ni indicateur identifiable (comparés seulement à l'ensemble des résultats de la requête)",
    "toute phrase sans chiffre ni terme surveillé",
)

_STOP_SUFFIX = {"inc", "inc.", "corp", "corp.", "corporation", "ltd", "ltd.", "co", "co.", "plc", "sa", "ag", "the", "/the", "(class", "a)", "class", "company", "limited"}


def fold(s: str) -> str:
    """Minuscules sans accents, ponctuation typographique normalisée ; LONGUEUR IDENTIQUE à l'original (les positions restent valides)."""
    out = []
    for c in s.lower():
        c = {"’": "'", "‘": "'", "−": "-", "–": "-", "—": "-", "\u00a0": " ", "\u202f": " ", "\u2009": " "}.get(c, c)
        d = unicodedata.normalize("NFD", c)
        out.append(d[0] if d else c)
    return "".join(out)


@dataclass
class Violation:
    category: str
    message: str
    excerpt: str

    def to_dict(self) -> dict:
        return {"category": self.category, "message": self.message, "excerpt": self.excerpt}


@dataclass
class ClaimReport:
    violations: list = field(default_factory=list)
    anchored_numbers: int = 0          # nombres effectivement rattachés à une ancre et contrôlés
    free_numbers: int = 0              # pourcentages sans ancre identifiable
    status_checked: int = 0            # affirmations de statut Guardian comparées aux constats réellement retournés
    status_unverified: bool = False    # le texte parle de statuts alors que le Guardian Check n'a pas été exécuté
    status_derived: int = 0            # sans Guardian Check : affirmations R1 / R7 comparées à la mesure et aux repères transmis par evaluate_portfolio
    checked: tuple = CHECKED
    not_checked: tuple = NOT_CHECKED

    @property
    def ok(self) -> bool:
        return not self.violations

    def summary(self) -> str:
        base = (f"Contrôle automatique PARTIEL : {self.anchored_numbers} nombre(s) rattaché(s) à un titre, un indicateur ou une catégorie ESG ont été comparés aux "
                f"résultats des outils ; {self.free_numbers} pourcentage(s) sans rattachement identifiable n'ont été comparés qu'à l'ensemble des résultats. ")
        st_ = (f"{self.status_checked} affirmation(s) de statut Guardian comparée(s) aux constats du Guardian Check. " if self.status_checked else "")
        if self.status_derived:
            st_ += (f"{self.status_derived} affirmation(s) sur R1 ou R7 comparée(s) à la mesure et aux repères transmis par evaluate_portfolio "
                    "(cohérence seulement, pas un statut du Guardian Check). ")
        if self.status_unverified:
            st_ += "Le texte mentionne des repères ou des statuts, mais le Guardian Check n'a pas été exécuté pendant cette requête : ils ne sont pas vérifiés. "
        return base + st_ + "Non vérifié automatiquement : " + " ; ".join(self.not_checked) + "."

    def to_dict(self) -> dict:
        return {"ok": self.ok, "violations": [v.to_dict() for v in self.violations], "anchored_numbers": self.anchored_numbers,
                "free_numbers": self.free_numbers, "status_checked": self.status_checked, "status_derived": self.status_derived, "status_unverified": self.status_unverified, "checked": list(self.checked), "not_checked": list(self.not_checked), "summary": self.summary()}


# ----------------------------------------------------------------------------- faits tirés des sorties d'outils
@dataclass
class Facts:
    profiles: dict
    active: str
    universe: object = None
    aliases: dict = field(default_factory=dict)            # ticker -> alias repliés
    ticker_values: dict = field(default_factory=dict)      # ticker -> valeurs (en %) acceptables pour CE titre
    ticker_weights: dict = field(default_factory=dict)     # ticker -> poids (en %) dans un portefeuille de la requête
    indicators: dict = field(default_factory=dict)         # type d'indicateur -> valeurs acceptables
    esg_states: dict = field(default_factory=dict)         # état ESG -> valeurs (poids en %) acceptables
    esg_lines: dict = field(default_factory=dict)          # ticker -> {state, records}
    has_esg: bool = False
    has_tools: bool = False
    effective_n: set = field(default_factory=set)
    portfolios: list = field(default_factory=list)        # poids (en %) de chaque portefeuille de la requête
    rule_thr: dict = field(default_factory=dict)          # règle -> repères (en %) réellement appliqués au profil, plus la valeur mesurée
    n_lines: set = field(default_factory=set)
    all_numbers: set = field(default_factory=set)


def _add(d: dict, key, v) -> None:
    if isinstance(v, bool) or v is None:
        return
    if isinstance(v, (int, float)):
        d.setdefault(key, set()).add(abs(round(float(v), 6)))


def _walk(obj, out: set) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(abs(float(obj)))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, out)


def _aliases_for(ticker: str, name: str, extra: tuple = ()) -> set:
    out = {fold(ticker)}
    if "-" in ticker:                                  # BTC-USD -> btc
        out.add(fold(ticker.split("-")[0]))
    for n in (name, *extra):
        f = fold(str(n or "")).strip()
        if not f:
            continue
        f = re.sub(r"\(class [a-z]\)", "", f).strip()
        words = [w for w in re.split(r"\s+", f) if w]
        while words and words[-1].strip(".,") in _STOP_SUFFIX:
            words.pop()
        core = " ".join(words).strip(" ,.")
        if len(core) >= 4:
            out.add(core)
    return out


def _walk_entities(facts: "Facts", obj) -> None:
    """Toute entrée {ticker: …, valeurs numériques} d'une preuve d'outil alimente les valeurs acceptables de CE ticker."""
    if isinstance(obj, dict):
        t = obj.get("ticker")
        if isinstance(t, str) and t in facts.aliases:
            for v in obj.values():
                _add(facts.ticker_values, t, v)
        for v in obj.values():
            _walk_entities(facts, v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk_entities(facts, v)


def _findings(f: "Facts", findings: list) -> None:
    """Constats du Guardian Check : seuils, mesures par règle et preuves par titre."""
    for fd in findings:
        _walk_entities(f, fd.get("evidence"))
        for k in ("threshold_attention_pct", "threshold_conflict_pct", "measured_pct"):
            _add(f.indicators, "threshold", fd.get(k))
        for k in ("threshold_attention_pct", "threshold_conflict_pct"):
            _add(f.indicators, "threshold_only", fd.get(k))
        if fd.get("threshold_attention") is not None and fd.get("value_kind") != "fraction":
            f.effective_n.update({float(fd["threshold_attention"]), float(fd["threshold_conflict"])})
        rid, ev = fd.get("rule_id"), fd.get("evidence") or {}
        if fd.get("value_kind") == "fraction" and fd.get("threshold_attention_pct") is not None:
            _add(f.rule_thr, (rid, "attention"), fd.get("threshold_attention_pct"))
            _add(f.rule_thr, (rid, "conflit"), fd.get("threshold_conflict_pct"))
            _add(f.rule_thr, (rid, "mesure"), fd.get("measured_pct"))
            if rid == "R2":
                _add(f.rule_thr, (rid, "actif"), ev.get("asset_volatility_threshold_pct"))
        kind = {"R1": "conc", "R2": "volatile_share", "R4": "vol", "R5": "dd"}.get(rid)
        if kind:
            _add(f.indicators, kind, fd.get("measured_pct"))
        if rid == "R2":
            _add(f.indicators, "threshold", ev.get("asset_volatility_threshold_pct"))
            for a in ev.get("volatile_assets", []):
                _add(f.indicators, "volatile_share", a.get("weight_pct"))
        if rid == "R10":
            for k in ("tech_share_pct", "qqq_weight_pct"):
                _add(f.indicators, "tech", ev.get(k))


def _portfolio_numbers(facts: Facts, pf: dict, label_weights: bool = True) -> None:
    if pf.get("weights_pct"):
        facts.portfolios.append(dict(pf["weights_pct"]))
    for t, w in (pf.get("weights_pct") or {}).items():
        _add(facts.ticker_values, t, w)
        _add(facts.ticker_weights, t, w)
    facts.n_lines.add(len(pf.get("weights_pct") or {}))
    m = pf.get("metrics") or {}
    for k, kind in (("cumulative_return_pct", "ret"), ("annualized_return_pct", "ret"), ("annualized_volatility_pct", "vol"), ("max_drawdown_pct", "dd")):
        _add(facts.indicators, kind, m.get(k))
    c = pf.get("concentration") or {}
    _add(facts.indicators, "conc", c.get("largest_position_weight_pct"))
    _add(facts.indicators, "top3", c.get("top3_weight_pct"))
    _add(facts.indicators, "conc", c.get("hhi"))
    if c.get("effective_number_of_positions") is not None:
        facts.effective_n.add(round(float(c["effective_number_of_positions"]), 2))
    for kind, key in (("exposure", "asset_class_exposure_pct"), ("exposure", "currency_exposure_pct")):
        for v in (pf.get(key) or {}).values():
            _add(facts.indicators, kind, v)
    _add(facts.indicators, "companies", (pf.get("asset_class_exposure_pct") or {}).get("equity"))
    for c in ((pf.get("key_facts") or {}).get("répartition_par_classe") or {}).get("classes", []):
        _add(facts.indicators, "exposure", c.get("pct"))
        if c.get("classe") == "actions individuelles":
            _add(facts.indicators, "companies", c.get("pct"))
    for kind in ("exposure", "funds"):
        for w in (pf.get("weights_pct") or {}).values():
            _add(facts.indicators, kind, w)
    for a in pf.get("assets") or []:
        t = a["ticker"]
        for k in ("weight_pct", "annualized_volatility_pct", "cumulative_return_pct", "max_drawdown_pct"):
            _add(facts.ticker_values, t, a.get(k))
        facts.aliases.setdefault(t, set()).update(_aliases_for(t, a.get("name")))
    fx = pf.get("fund_exposure") or {}
    _add(facts.indicators, "funds", fx.get("fund_weight_pct"))
    for f in fx.get("fund_lines") or []:
        _add(facts.indicators, "funds", f.get("weight_pct"))


def build_facts(records: list, profiles: dict, active: str, universe=None) -> Facts:
    f = Facts(profiles=profiles, active=active, universe=universe)
    if universe is not None:
        for t in universe.index:
            f.aliases.setdefault(t, set()).update(_aliases_for(t, universe.loc[t, "name"]))
    for r in records:
        if r.status != "ok" or not isinstance(r.result, dict):
            continue
        f.has_tools = True
        res = r.result
        _walk(res, f.all_numbers)
        if r.tool in ("evaluate_portfolio", "check_profile_constraints"):
            _portfolio_numbers(f, res)
            prof = (res.get("key_facts") or {}).get("profil_actif") or {}
            for lvl, v in (prof.get("repères_concentration_plus_grande_position") or {}).items():
                num = re.search(r"\d+(?:[.,]\d+)?", str(v))
                if num:
                    _add(f.rule_thr, ("R1", lvl), float(num.group(0).replace(",", ".")))
                    _add(f.indicators, "threshold_only", float(num.group(0).replace(",", ".")))
                    _add(f.indicators, "threshold", float(num.group(0).replace(",", ".")))
            if prof and (res.get("concentration") or {}).get("largest_position_weight_pct") is not None:
                _add(f.rule_thr, ("R1", "mesure"), res["concentration"]["largest_position_weight_pct"])
                _add(f.indicators, "threshold", res["concentration"]["largest_position_weight_pct"])   # comme measured_pct des constats
            tech = (res.get("key_facts") or {}).get("technology") or {}
            for k in ("part_directe_mesurée_pct", "QQQ_pct_non_décomposé"):
                _add(f.indicators, "tech", tech.get(k))
            _findings(f, res.get("findings") or [])
        elif r.tool == "compare_scenarios":
            for key in ("portfolio_A", "portfolio_B"):
                _portfolio_numbers(f, res.get(key) or {})
            deltas: set = set()
            _walk(res.get("differences_B_minus_A"), deltas)
            for kind in ("vol", "dd", "ret", "conc"):
                f.indicators.setdefault(kind, set()).update(deltas)
            for g in ("guardian_A", "guardian_B"):
                _findings(f, (res.get(g) or {}).get("findings") or [])
        elif r.tool == "check_esg_preferences" and res.get("applicable"):
            f.has_esg = True
            for ln in res.get("lines") or []:
                t = ln["ticker"]
                _add(f.ticker_values, t, ln.get("weight_pct"))
                _add(f.ticker_weights, t, ln.get("weight_pct"))
                recs = ln.get("documented_records") or []
                f.esg_lines[t] = {"state": ln["state"], "records": recs, "name": ln.get("name")}
                extra = tuple(x.get("company_name_in_source", "") for x in recs)
                f.aliases.setdefault(t, set()).update(_aliases_for(t, ln.get("name"), extra))
            cov = res.get("coverage") or {}
            by_label = {"Controverse documentée à examiner": "DOCUMENTED", "Information complémentaire documentée (hors critère déclaré)": "COMPLEMENTARY",
                        "Aucune controverse identifiée dans les sources consultées": "NONE_FOUND", "Information insuffisante": "INSUFFICIENT", "Non applicable": "NOT_APPLICABLE"}
            for label, v in (cov.get("weights_by_state_pct") or {}).items():
                _add(f.esg_states, by_label.get(label, label), v)
            _add(f.esg_states, "CHECKED", cov.get("checked_in_sources_pct"))
            _add(f.esg_states, "CHECKED", cov.get("checked_of_applicable_pct"))
            for cat in [*(res.get("documented_categories") or []), *(res.get("complementary_information") or [])]:
                _add(f.esg_states, "DOCUMENTED" if cat["relevance"] == "direct" else "COMPLEMENTARY", cat.get("weight_pct"))
            for sc in res.get("search_scope") or []:
                _add(f.esg_states, "NONE_FOUND", sc.get("weight_pct"))
            fv = res.get("fund_verification") or {}
            _add(f.esg_states, "INSUFFICIENT", fv.get("weight_pct"))
            u = res.get("underlying_exposure") or {}
            _add(f.indicators, "funds", u.get("etf_weight_pct"))
            _add(f.indicators, "companies", u.get("direct_company_weight_pct"))
    return f


# ----------------------------------------------------------------------------- segmentation et ancres
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÉÈÀÂÎÔÛ*#(\-\d])|;\s+")
_PCT = re.compile(r"(?<![\d.,])[−-]?(\d+(?:[.,]\d+)?)\s*%")
_NUM_POS = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:positions?|lignes?)\b")

INDICATOR_PATTERNS = (
    ("dd", r"\br5\b|drawdown|plus forte baisse|baisse (?:historique|maximale|maximum)|perte (?:historique|maximale)|baisse de \d|recul"),
    ("vol", r"\br4\b|volatilit|fluctuations? (?:du|de votre|annualis|historiques?)|fluctue"),
    ("ret", r"rendement|performance"),
    ("top3", r"(?:trois|3) (?:plus )?(?:grandes|grosses|importantes|principales)|top ?3|(?:trois|3) (?:premieres |principales |principaux )?(?:lignes|positions|actifs)"),
    ("conc", r"\br1\b|plus grande position|position dominante|concentration|plus gros(?:se)? position"),
    ("volatile_share", r"\br2\b|actifs? (?:tres )?(?:fluctuants?|volatils?)|part d'actifs"),
    ("threshold", r"seuils?|reperes?|au-dela de|depass"),
    ("tech", r"technolog|\btech\b"),
    ("exposure", r"exposition|classe d'actifs|obligations?|devise|\busd\b|\bcad\b"),
    ("funds", r"\bfnb\b|\bfonds\b"),
    ("companies", r"actions? individuelles?|entreprises? detenues? directement"),
)
ESG_PATTERNS = (
    ("DOCUMENTED", r"controverses? documentees?|exclusion environnementale|a examiner|exclu(?:e|es|s)?\b"),
    ("COMPLEMENTARY", r"information(?:s)? complementaires?|observation|gouvernance|hors (?:du )?critere"),
    ("NONE_FOUND", r"aucune controverse|non trouv|sans correspondance|cherch\w+ et non|n'?ont pas ete trouv"),
    ("INSUFFICIENT", r"insuffisan|non evaluables?|faute de donnees|pas pu etre evalu|ne peut pas etre evalu|n'a pas pu etre evalu"),
    ("NOT_APPLICABLE", r"non applicable|sans objet"),
    ("CHECKED", r"couverture|couvr\w*|couvert\w*|verifie|cherche dans|source consultee|sources consultees"),
)
NEGATION = re.compile(r"\b(?:pas|jamais|aucun(?:e)?|ni|non|sans|impossible|hors|n'est|ne peut|ne sont|ne permet|n'a|n'ont)\b")


NEGATION_STRICT = re.compile(r"\b(?:pas|jamais|impossible|non|ne peut|ne peuvent|n'a pas|n'ont pas|ne permet\w*|insuffisan\w*|pour confirmer|a confirmer|pour verifier|a verifier|necessiterait|necessite|empeche\w*|limite\w*|incomplet\w*|inconnu\w*)\b")


@dataclass
class _Anchor:
    start: int
    end: int
    kind: str       # ticker | ind | esg
    key: str


def _find_anchors(seg_f: str, facts: Facts) -> list:
    anchors = []
    taken = []
    cands = []
    for t, al in facts.aliases.items():
        for a in al:
            if not a:
                continue
            pat = rf"(?<![a-z0-9.\-]){re.escape(a)}(?![a-z0-9\-]|\.[a-z0-9])"
            for m in re.finditer(pat, seg_f):
                cands.append((m.start(), m.end(), t))
    cands.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
    for s, e, t in cands:
        if any(s < te and e > ts for ts, te in taken):
            continue
        taken.append((s, e))
        anchors.append(_Anchor(s, e, "ticker", t))
    for kind, pat in INDICATOR_PATTERNS:
        for m in re.finditer(pat, seg_f):
            anchors.append(_Anchor(m.start(), m.end(), "ind", kind))
    if facts.has_esg:
        for kind, pat in ESG_PATTERNS:
            for m in re.finditer(pat, seg_f):
                anchors.append(_Anchor(m.start(), m.end(), "esg", kind))
    return anchors


def _dist(a: _Anchor, s: int, e: int) -> int:
    if a.end <= s:
        return s - a.end
    if a.start >= e:
        return a.start - e
    return 0


def _allowed(facts: Facts, a: _Anchor) -> set:
    if a.kind == "ticker":
        return facts.ticker_values.get(a.key, set())
    if a.kind == "ind":
        return facts.indicators.get(a.key, set())
    return facts.esg_states.get(a.key, set())


def _matches(val: float, digits: int, allowed: set) -> bool:
    """Égalité à la précision affichée : arrondi (± une demi-unité) ou troncature (180,91 écrit « 180 »)."""
    tol = 0.5 * 10 ** (-digits) + 1e-9
    unit = 10 ** (-digits)
    return any(abs(x - val) <= tol or (0 <= x - val < unit - 1e-9) for x in allowed)


# ----------------------------------------------------------------------------- vérifications
_ESG_CONTEXT = re.compile(r"\besg\b|controvers|nbim|exclu|observation|gouvernance|durab|ethiq|environnement|social")
_CONFORM = re.compile(r"\bconforme[s]?\b|conformite|\brespecte(?:nt)?\b|sans controverse(?! identifiee)|exempts? de controverse|aucun conflit|pas de conflit")
_LABELS = re.compile(r"\bdurables?\b|\bethiques?\b")
_ORDERS = re.compile(r"\b(?:achetez|vendez|conservez|je (?:vous )?recommande|nous (?:vous )?recommandons|vous devriez|vous devez|il faut (?:vendre|acheter|reduire|augmenter)|"
                     r"je vous conseille|nous vous conseillons|(?:acheter|vendre) (?:des|de la|du|vos|votre|\d)|passez un ordre|placez un ordre|"
                     r"(?:devrait|pourrait) (?:considerer|envisager)\s*:?\s*(?:[-*•]\s*)?(?:de |d'|un |le |la |une )?(?:\*\*)?(?:reequilibr|reduction|reduire|vendre|acheter|diversif|augmenter)|"
                     r"(?:une )?reduction de (?:cette|sa|la) (?:concentration|position|part)[^.]{0,60}pourrait)")
_INVENTED = ("anxi", "inquiet", "nerveu", "stress", "peur", "craint", "angoiss", "besoin de liquidit", "liquidites", "hypothequ", "heritage",
             "etudes des enfants", "proprietaire", "divorc", "veuf", "licenci", "dette", "pret etudiant")


def _near_alias(aliases: list, pos: int):
    best = None
    for a in aliases:
        d = a.start - pos if a.start >= pos else pos - a.end
        d = max(d, 0)
        if best is None or d < best[0]:
            best = (d, a)
    return best


_CRITERIA = (("R2", r"actifs? (?:tres |historiquement )?(?:volatils?|fluctuants?)"), ("R1", r"concentration|plus grande position|position dominante|un seul actif"),
             ("R4", r"volatilite (?:annualisee )?du portefeuille|fluctuations du portefeuille"), ("R5", r"plus forte baisse|drawdown|perte (?:historique )?maximale"))
_CLAUSE_SPLIT = re.compile(r"(?<!\d),\s|\s+et\s+|\s+mais\s+|\s+alors que\s+|\s+tandis que\s+")


def _clause_bounds(seg_f: str, sp: int, ep: int) -> tuple:
    """Proposition contenant le pourcentage (coupée aux virgules, « et », « mais »…), pour ne pas rattacher un chiffre à l'ancre d'une autre proposition."""
    cs, ce = 0, len(seg_f)
    for m in _CLAUSE_SPLIT.finditer(seg_f):
        if m.end() <= sp:
            cs = m.end()
        elif m.start() >= ep:
            ce = m.start()
            break
    return cs, ce


def _top3_ok(named: set, facts: Facts) -> bool:
    """Les titres présentés comme « les trois plus grandes positions » doivent l'être dans au moins un portefeuille de la requête (égalités admises)."""
    for w in facts.portfolios:
        ranked = sorted(w.values(), reverse=True)
        if len(ranked) < 3 or not named <= set(w):
            continue
        third = ranked[2]
        above = {t for t, v in w.items() if v > third}
        cands = {t for t, v in w.items() if v >= third}
        if named <= cands and (len(named) < 3 or above <= named):
            return True
    return False


_CLASS_WORDS = (("actions individuelles", ({"equity"},)), ("fnb d'actions", ({"etf_equity"},)), ("fnb d'obligations", ({"etf_bond"},)),
                ("obligations", ({"etf_bond"},)), ("cryptoactifs", ({"crypto"},)), ("cryptomonnaies", ({"crypto"},)), ("crypto", ({"crypto"},)),
                ("actions", ({"equity"}, {"equity", "etf_equity"})), ("fnb", ({"etf_equity", "etf_bond"}, {"etf_equity", "etf_bond", "etf_commodity"})))
_INCL = re.compile(r"(actions individuelles|fnb d'actions|fnb d'obligations|obligations|cryptoactifs|cryptomonnaies|crypto|actions|fnb)\s*(?:\*\*)?\s*:?\s*(?:\*\*)?\s*"
                   r"(\d+(?:[.,]\d+)?)\s*%(?:\*\*)?\s*\(\s*dont\s+(?:\*\*)?(\d+(?:[.,]\d+)?)\s*%(?:\*\*)?\s*([^)]{1,40})\)")


def _check_class_inclusion(seg: str, seg_f: str, facts: Facts, rep: ClaimReport) -> None:
    """« Actions : 45 % (dont 25 % en FNB QQQ) » : le titre cité dans « dont » doit appartenir à la catégorie dont le total est annoncé."""
    if facts.universe is None or not facts.portfolios:
        return
    for m in _INCL.finditer(seg_f):
        total = float(m.group(2).replace(",", "."))
        inside = [t for t, al in facts.aliases.items() if any(re.search(rf"(?<![a-z0-9.\-]){re.escape(a)}(?![a-z0-9\-])", m.group(4)) for a in al)]
        if len(inside) != 1:
            continue
        options = dict(_CLASS_WORDS)[m.group(1)]
        for w in facts.portfolios:
            if inside[0] not in w:
                continue
            cls = {t: str(facts.universe.loc[t, "asset_class"]) for t in w}
            match = [opt for opt in options if abs(sum(v for t, v in w.items() if cls[t] in opt) - total) < 0.51]
            if match and all(cls[inside[0]] not in opt for opt in match):
                rep.violations.append(Violation("categorie_actif", f"{inside[0]} est présenté comme inclus dans « {m.group(1)} » ({m.group(2)} %), "
                                                f"mais il n'appartient pas à cette catégorie dans les données (classe : {cls[inside[0]]}).", seg.strip()[:200]))
            break


_ANAPHORA = re.compile(r"\b(?:cette action|ce titre|cet actif|cette position|ce fnb|cette cryptomonnaie|ce cryptoactif|ce dernier|cette derniere)\b")


def _check_numbers(seg: str, seg_f: str, facts: Facts, rep: ClaimReport, prev_tickers: tuple = ()) -> None:
    anchors = _find_anchors(seg_f, facts)
    ticker_anchors = [a for a in anchors if a.kind == "ticker"]
    if not ticker_anchors and len(prev_tickers) == 1 and _ANAPHORA.search(seg_f):
        m0 = _ANAPHORA.search(seg_f)
        anchors.append(_Anchor(m0.start(), m0.end(), "ticker", prev_tickers[0]))     # le titre nommé dans la phrase précédente
        ticker_anchors = [anchors[-1]]
    top3 = [a for a in anchors if a.kind == "ind" and a.key == "top3"]
    if top3 and facts.portfolios:
        named = {a.key for a in ticker_anchors if a.start >= top3[0].start}
        if len(named) >= 2 and not _top3_ok(named, facts):
            rep.violations.append(Violation("valeur_associee", f"Les titres présentés comme les trois plus grandes positions ({', '.join(sorted(named))}) ne le sont pas d'après les poids des outils.",
                                            seg.strip()[:200]))
    for m in _PCT.finditer(seg):
        raw = m.group(1)
        val = float(raw.replace(",", "."))
        if val in (0.0, 100.0):
            continue
        digits = len(re.split(r"[.,]", raw)[1]) if re.search(r"[.,]", raw) else 0
        sp, ep = m.start(), m.end()
        cs, ce = _clause_bounds(seg_f, sp, ep)
        local = [a for a in anchors if a.end > cs and a.start < ce]
        weak = lambda a: 30 if (a.kind == "esg" and a.key == "CHECKED") else 0     # « sources consultées » est une précision, pas la catégorie  # noqa: E731
        # sans ancre dans sa propre proposition, un pourcentage n'est pas rattaché au titre d'une autre proposition (« Les 30 % directs et les 25 % de QQQ »)
        cand = local or [a for a in anchors if a.kind != "ticker"]
        near = sorted(((_dist(a, sp, ep) + weak(a), a) for a in cand), key=lambda x: x[0])
        if not near or near[0][0] > 60:
            rep.free_numbers += 1
            continue
        d1, a1 = near[0]
        rep.anchored_numbers += 1
        ticker_anchors = [a for a in anchors if a.kind == "ticker"]
        allowed1 = _allowed(facts, a1)
        # un nombre introduit comme seuil (« seuil … de X % », « repère de conflit de X % ») doit être le repère de ce critère, à ce niveau, pour le profil
        intro = seg_f[max(cs, sp - 45):sp]
        if re.search(r"\bseuils?\b|\breperes?\b", intro):
            crit, best = None, None
            for rid, pat in _CRITERIA:
                for cm in re.finditer(pat, seg_f):
                    d = abs(cm.start() - sp)
                    if best is None or d < best:
                        best, crit = d, rid
            lvl = "conflit" if re.search(r"conflit", intro) else ("attention" if re.search(r"attention|vigilance", intro) else None)
            known = {k[1]: v for k, v in facts.rule_thr.items() if k[0] == crit}
            if crit and (known.get("attention") or known.get("conflit")):
                allowed = known.get(lvl, set()) if lvl else set().union(*known.values())
                allowed = allowed | known.get("actif", set()) | known.get("mesure", set())
                if not _matches(val, digits, allowed):
                    rep.violations.append(Violation("valeur_associee", f"Le pourcentage {m.group(0).strip()} est présenté comme un seuil du critère {crit}"
                                                    + (f" (niveau {lvl})" if lvl else "") + ", mais ce n'est pas le repère appliqué à ce profil.", seg.strip()[:200]))
                    continue
        # une proposition sur la technologie ne peut citer que les parts réellement mesurées (jamais un total recalculé)
        if facts.indicators.get("tech") and any(a.kind == "ind" and a.key == "tech" for a in local) and not _matches(val, digits, facts.indicators["tech"]):
            own = a1.kind == "ticker" or (a1.kind == "ind" and a1.key in ("vol", "dd", "ret", "top3", "conc"))
            if not ((own and _matches(val, digits, allowed1)) or (re.search(r"\bseuils?\b|\breperes?\b", seg_f[:sp]) and _matches(val, digits, facts.indicators.get("threshold_only", set())))):
                t = facts.indicators["tech"]
                rep.violations.append(Violation("valeur_associee", f"Le pourcentage {m.group(0).strip()} est présenté comme une part technologique : seules la part directement mesurée et "
                                                f"le poids de QQQ existent ({', '.join(f'{x:g} %' for x in sorted(t))}) ; l'exposition technologique totale n'est pas mesurée.",
                                                seg.strip()[:200]))
                continue
        if _matches(val, digits, allowed1):
            continue
        before = seg_f[max(0, sp - 3):sp]
        if re.search(r"[<>≥≤]\s*$", before) and _matches(val, digits, facts.indicators.get("threshold", set())):
            continue                                                   # « 40 % > 20 % » : la seconde valeur est un repère
        if any(a.kind == "ind" and a.key == "threshold" and d <= 25 and _matches(val, digits, _allowed(facts, a)) for d, a in near):
            continue                                                   # « dépasse 35 % (NVDA, …) » : la valeur est le repère, la parenthèse liste les titres
        par = re.match(r"[\s*_]*\(([^)]{1,80})\)", seg_f[ep:])
        if par and par.group(1).strip().startswith("dont"):
            par = None                                       # « (dont …) » désigne une partie du total : voir _check_class_inclusion
        if par:
            inside = [a.key for a in ticker_anchors if ep + par.start(1) <= a.start < ep + par.end(1)]
            items = [x.strip(" .*_") for x in re.split(r",|\bet\b", par.group(1)) if x.strip(" .*_")]
            if inside and len(items) > len(set(inside)):
                inside = []                                # un élément de la liste n'est pas reconnu : pas de conclusion sur la somme
            if inside:
                group = round(sum(max(facts.ticker_weights.get(t, {0}) or {0}) for t in set(inside)), 6)
                if _matches(val, digits, {group}) or (len(set(inside)) == 1 and _matches(val, digits, _allowed(facts, _Anchor(0, 0, "ticker", inside[0])))):
                    continue
                rep.violations.append(Violation("valeur_associee", f"Le pourcentage {m.group(0).strip()} ne correspond pas au poids des titres cités entre parenthèses ({', '.join(dict.fromkeys(inside))}).", seg.strip()[:200]))
                continue
        # « seuil d'attention de X % » : le seuil qualifie l'indicateur voisin, sa valeur doit figurer parmi les seuils des outils
        if any(a.kind == "ind" and a.key == "threshold" and _matches(val, digits, _allowed(facts, a)) for _, a in near):
            continue
        # mesure propre à un titre nommé plus tôt dans la phrase (« La position de NVDA…, avec une volatilité de 50,71 % ») : la valeur est celle du titre
        prev = [a for a in ticker_anchors if a.end <= sp]
        own_metric = any(a.kind == "ind" and a.key in ("vol", "dd", "ret") for a in (local or [a1]))
        if prev and (own_metric or cs - max(prev, key=lambda a: a.end).end <= 25) \
                and _matches(val, digits, _allowed(facts, max(prev, key=lambda a: a.end))):
            continue
        # repères énumérés dans une phrase sur les seuils (« respectivement de 10 % et 20 % »)
        if re.search(r"\bseuils?\b|\breperes?\b", seg_f[:sp]) and _matches(val, digits, facts.indicators.get("threshold_only", set())):
            continue
        # part technologique partielle correcte dans une phrase sur la technologie (un autre mot peut être plus proche)
        if any(a.kind == "ind" and a.key == "tech" for a in anchors) and _matches(val, digits, facts.indicators.get("tech", set())):
            continue
        # ambiguïté : une autre ancre toute proche pour laquelle la valeur est correcte
        if any(d <= d1 + 25 and (a.kind != a1.kind or (a.key != a1.key and a in local)) and _matches(val, digits, _allowed(facts, a)) for d, a in near[1:]):
            continue
        # somme d'un groupe de titres cités dans la phrase, ou valeur d'une catégorie ESG à laquelle appartiennent les titres cités
        tick = {a.key for a in ticker_anchors}
        strict = a1.kind == "ind" and a1.key in ("tech", "vol", "dd", "ret")      # une somme de poids n'est jamais une volatilité, une baisse ou une part technologique
        if not strict and len(tick) > 1 and _matches(val, digits, {round(sum(max(facts.ticker_weights.get(t, {0}) or {0}) for t in tick), 6)}):
            continue
        if facts.has_esg and a1.kind == "ind" and a1.key in ("exposure", "funds", "companies") and _ESG_CONTEXT.search(seg_f) \
                and any(_matches(val, digits, facts.esg_states.get(k, set())) for k in ("DOCUMENTED", "COMPLEMENTARY", "NONE_FOUND", "INSUFFICIENT", "NOT_APPLICABLE", "CHECKED")):
            continue
        if not strict and (a1.kind != "ind" or a1.key in ("conc", "top3", "volatile_share", "exposure")):
            if facts.has_esg and tick:
                states = {facts.esg_lines[t]["state"] for t in tick if t in facts.esg_lines}
                if any(_matches(val, digits, facts.esg_states.get(s, set())) for s in states):
                    continue
        if a1.kind == "ticker":
            what = a1.key
        elif a1.kind == "ind":
            what = {"vol": "la volatilité", "dd": "la plus forte baisse historique", "ret": "le rendement", "conc": "la concentration", "top3": "les trois plus grandes positions",
                    "threshold": "un repère de vigilance", "exposure": "une exposition", "funds": "la part des FNB", "companies": "la part d'actions individuelles",
                    "volatile_share": "la part d'actifs très fluctuants", "tech": "la part technologique"}.get(a1.key, a1.key)
        else:
            what = {"DOCUMENTED": "la part documentée à examiner", "COMPLEMENTARY": "la part d'information complémentaire", "NONE_FOUND": "la part sans controverse identifiée",
                    "INSUFFICIENT": "la part non évaluable", "NOT_APPLICABLE": "la part sans objet", "CHECKED": "la couverture"}.get(a1.key, a1.key)
        rep.violations.append(Violation("valeur_associee",
                                        f"Le pourcentage {m.group(0).strip()} est associé à {what}, mais cette valeur ne correspond pas aux résultats des outils pour ce titre, cet indicateur ou cette catégorie.",
                                        seg.strip()[:200]))
    for m in _NUM_POS.finditer(seg):
        v = float(m.group(1).replace(",", "."))
        if facts.effective_n or facts.n_lines:
            ok = any(abs(v - x) <= 0.051 for x in facts.effective_n) or any(abs(v - x) < 1e-9 for x in facts.n_lines)
            ok = ok or any(abs(v - round(x)) < 1e-9 for x in facts.effective_n)
            if not ok and re.search(r"effectif|poids egal|equivalent", seg_f):
                rep.violations.append(Violation("valeur_associee", f"Le nombre de positions « {m.group(0)} » ne correspond ni au nombre effectif de positions ni au nombre de lignes calculés.", seg.strip()[:200]))


def _has_neg(seg_f: str) -> bool:
    return bool(NEGATION.search(seg_f))


def _has_strict_neg(seg_f: str) -> bool:
    """Négation franche (« pas », « jamais », « impossible »…) : « aucune controverse » est lui-même une affirmation, pas une négation du contrôle."""
    return bool(NEGATION_STRICT.search(seg_f))


_FIN_WORDS = re.compile(r"guardian|financi|volatilit|drawdown|concentration|baisse|fluctu|position|rendement")


def _check_esg_semantics(seg: str, seg_f: str, facts: Facts, rep: ClaimReport, prev_f: str = "") -> None:
    ctx = bool(_ESG_CONTEXT.search(seg_f)) and facts.has_esg
    if not ctx and facts.has_esg and prev_f and _ESG_CONTEXT.search(prev_f) and not _FIN_WORDS.search(seg_f) and re.search(r"seuils?", seg_f):
        ctx = True                                   # « Selon les seuils…, cela représente un conflit » après une phrase ESG : même sujet
    neg = _has_neg(seg_f)
    sneg = _has_strict_neg(seg_f)
    if ctx and "seuil" in seg_f and not re.search(r"aucun seuil|pas de seuil|sans seuil|n'utilise (?:aucun )?seuil|ne s'appliquent pas|n'appliqu\w+ (?:aucun )?seuil", seg_f) \
            and not re.search(r"guardian|financi|volatilit|drawdown|concentration|baisse", seg_f):
        rep.violations.append(Violation("seuil_esg", "Le texte parle de seuils à propos de l'ESG : le module ESG n'utilise aucun seuil ni aucun score.", seg.strip()[:200]))
    if ctx and "seuil" in seg_f and re.search(r"seuils? heuristiques?", seg_f) and not neg and (re.search(r"\besg\b|controvers", seg_f) or not _ESG_CONTEXT.search(seg_f)):
        rep.violations.append(Violation("seuil_esg", "Les « seuils heuristiques » sont ceux du Guardian Check financier ; ils ne s'appliquent pas à l'ESG.", seg.strip()[:200]))
    if facts.has_esg and _CONFORM.search(seg_f) and (re.search(r"\besg\b|controvers|preference", seg_f)) and not sneg:
        rep.violations.append(Violation("conformite_esg", "Le texte présente une conformité ou une absence de conflit ESG : une absence de résultat n'est jamais une preuve de conformité.", seg.strip()[:200]))
    if not facts.has_esg:
        return
    if _LABELS.search(seg_f) and not sneg:
        rep.violations.append(Violation("conformite_esg", "Le texte qualifie un actif ou le portefeuille de « durable » ou « éthique » : aucun score ni label ESG n'existe dans cet outil.", seg.strip()[:200]))
    insufficient_funds = [t for t, v in facts.esg_lines.items() if v["state"] == "INSUFFICIENT"]
    if insufficient_funds and re.search(r"\bfnb\b", seg_f) and not sneg and re.search(r"verifie|conforme|aucune controverse", seg_f):
        rep.violations.append(Violation("verification_actif", "Les FNB sans composition connue sont présentés comme vérifiés ou sans controverse.", seg.strip()[:200]))
    if re.search(r"\bconflits?\b", seg_f) and not sneg:
        doc = facts.esg_states.get("DOCUMENTED", set())
        for m in _PCT.finditer(seg):
            val = float(m.group(1).replace(",", "."))
            digits = len(re.split(r"[.,]", m.group(1))[1]) if re.search(r"[.,]", m.group(1)) else 0
            if val not in (0.0, 100.0) and not _matches(val, digits, doc):
                rep.violations.append(Violation("conflit_esg", f"Le pourcentage {m.group(0).strip()} est présenté comme « en conflit » : seule la part documentée liée à la préférence déclarée peut l'être, et les catégories ne s'additionnent pas.", seg.strip()[:200]))
    anchors = [a for a in _find_anchors(seg_f, facts) if a.kind == "ticker" and a.key in facts.esg_lines]
    if not anchors:
        return

    def owner(pos: int):
        b = _near_alias(anchors, pos)
        return b[1].key if b else None

    for m in re.finditer(r"\bexclu(?:e|es|s)?\b|\bexclusions?\b", seg_f):
        t = owner(m.start())
        recs = facts.esg_lines[t]["records"] if t else []
        if t and not neg and not any(r["decision"] == "exclusion" for r in recs):
            rep.violations.append(Violation("exclusion_observation", f"{t} est présenté comme exclu alors que les outils ne retournent pas d'exclusion pour ce titre.", seg.strip()[:200]))
    for m in re.finditer(r"\bobservation\b|sous observation", seg_f):
        t = owner(m.start())
        recs = facts.esg_lines[t]["records"] if t else []
        if t and not neg and recs and all(r["decision"] == "exclusion" for r in recs):
            rep.violations.append(Violation("exclusion_observation", f"{t} est présenté comme sous observation alors que la décision enregistrée est une exclusion.", seg.strip()[:200]))
    for m in re.finditer(r"environnement\w*|\bsocial\w*|\bsociaux\b|gouvernance", seg_f):
        t = owner(m.start())
        recs = facts.esg_lines[t]["records"] if t else []
        if not (t and recs) or neg:
            continue
        dims = {r["dimension"] for r in recs}
        word = m.group(0)
        d = "G" if word.startswith("gouvern") else ("E" if word.startswith("environ") else "S")
        if d not in dims:
            rep.violations.append(Violation("dimension_esg", f"{t} est rattaché à la dimension « {word} » alors que les outils retournent la dimension {', '.join(sorted(dims))}.", seg.strip()[:200]))
    for m in re.finditer(r"\bconflits?\b", seg_f):
        t = owner(m.start())
        if t and not neg and facts.esg_lines[t]["state"] != "DOCUMENTED":
            rep.violations.append(Violation("conflit_esg", f"{t} est présenté comme un conflit alors que son état ESG est {facts.esg_lines[t]['state']} (un conflit suppose une information documentée liée à la préférence déclarée).", seg.strip()[:200]))
    for m in re.finditer(r"verifi\w+|cherch\w+|couvert\w*|conforme\w*|aucune controverse", seg_f):
        t = owner(m.start())
        if t and not sneg and facts.esg_lines[t]["state"] in ("NOT_APPLICABLE", "INSUFFICIENT"):
            rep.violations.append(Violation("verification_actif", f"{t} est présenté comme vérifié ou sans controverse alors que son état ESG est {facts.esg_lines[t]['state']}.", seg.strip()[:200]))
    for m in re.finditer(r"controverse documentee|exclu(?:e|es|s)?\b|sous observation", seg_f):
        t = owner(m.start())
        if t and not neg and facts.esg_lines[t]["state"] == "NONE_FOUND":
            rep.violations.append(Violation("controverse_inventee", f"Une controverse ou une décision est attribuée à {t} alors qu'aucune n'a été trouvée dans les sources consultées.", seg.strip()[:200]))


def _check_tech_conflict(seg: str, seg_f: str, facts: Facts, rep: ClaimReport) -> None:
    """La part technologique (R10) est une information sans seuil : aucun outil ne conclut à un conflit avec la préférence technologique."""
    if not facts.indicators.get("tech") and "technolog" not in seg_f:
        return
    if re.search(r"\bconflit", seg_f) and re.search(r"technolog", seg_f) and not _has_neg(seg_f) \
            and not re.search(r"volatil|baisse|drawdown|fluctu|plus grande position|concentration dans un actif|actifs? (?:tres )?(?:volatils?|fluctuants?)", seg_f):
        rep.violations.append(Violation("conflit_non_etabli", "Le texte présente un conflit avec la préférence technologique : la part technologique est une information sans seuil, aucun outil n'établit ce conflit.", seg.strip()[:200]))


def _check_persona(seg: str, seg_f: str, facts: Facts, named_in_text: set, rep: ClaimReport) -> None:
    names = {pid: fold(p.get("display_name", pid)) for pid, p in facts.profiles.items()}
    in_seg = {pid for pid, n in names.items() if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", seg_f)}
    subject = None
    if len(in_seg) == 1:
        subject = next(iter(in_seg))
    elif not in_seg and named_in_text <= {facts.active}:
        subject = facts.active
    if subject is None:
        return
    p = facts.profiles[subject]
    label = p.get("display_name", subject)
    spans = []
    for m in re.finditer(r"(\d{1,2})\s*(?:-|a)\s*(\d{1,2})\s*ans", seg_f):
        spans.append((m.start(), m.end()))
        if (int(m.group(1)), int(m.group(2))) != (p.get("horizon_years_min"), p.get("horizon_years_max")):
            rep.violations.append(Violation("persona", f"L'horizon « {m.group(0)} » ne correspond pas à celui de {label} ({p.get('horizon_years_min')} à {p.get('horizon_years_max')} ans).", seg.strip()[:200]))
    for m in re.finditer(r"(\d{1,2})\s*ans\s+ou\s+plus", seg_f):
        spans.append((m.start(), m.end()))
        if p.get("horizon_years_max") or int(m.group(1)) != p.get("horizon_years_min"):
            rep.violations.append(Violation("persona", f"L'horizon « {m.group(0)} » ne correspond pas à celui de {label}.", seg.strip()[:200]))
    lo, hi = p.get("horizon_years_min"), p.get("horizon_years_max")
    for m in re.finditer(r"horizon (?:de placement )?(?:de |d'environ |d'au moins |d'une duree de )?(\d{1,2})\s*ans(?!\s*(?:-|a|ou)\s)", seg_f):
        spans.append((m.start(), m.end()))
        v = int(m.group(1))
        if lo is not None and (v < lo or (hi is not None and v > hi)):
            rep.violations.append(Violation("persona", f"L'horizon « {m.group(0)} » ne correspond pas à celui de {label} "
                                            f"({lo} à {hi} ans)." if hi else f"L'horizon « {m.group(0)} » ne correspond pas à celui de {label} ({lo} ans ou plus).",
                                            seg.strip()[:200]))
    ages = {q.get("age") for q in facts.profiles.values() if q.get("age")}
    for m in re.finditer(r"\b(\d{2})\s*ans\b", seg_f):
        if any(s <= m.start() < e for s, e in spans):
            continue
        v = int(m.group(1))
        if v in ages and v != p.get("age"):
            rep.violations.append(Violation("persona", f"L'âge {v} ans ne correspond pas à {label} ({p.get('age')} ans).", seg.strip()[:200]))
    mine = fold(str(p.get("risk_profile_label", "")))
    for m in re.finditer(r"(?:profil(?: de risque| a risque)?|tolerance(?: au risque)?|risque)\s*:?\s*(?:\*\*)?(faible a modere|faible|modere|eleve)", seg_f):
        if m.group(1) not in mine:
            rep.violations.append(Violation("persona", f"Le niveau de risque « {m.group(1)} » ne correspond pas à {label} ({p.get('risk_profile_label')}).", seg.strip()[:200]))
    for pid, q in facts.profiles.items():
        occ = fold(str(q.get("occupation", "")))
        if pid != subject and occ and occ in seg_f:
            rep.violations.append(Violation("persona", f"La profession de {q.get('display_name')} est attribuée à {label}.", seg.strip()[:200]))


# ----------------------------------------------------------------------------- statuts du Guardian Check (contrôle générique, V3.3)
# Une affirmation de statut n'est comparée que si le critère, le profil et le portefeuille sont identifiables sans ambiguïté.
# Le niveau affirmé est traduit en ENSEMBLE de statuts compatibles (« au-dessus du repère d'attention » = ATTENTION ou CONFLIT pour un repère plafond).
OK_, ATT_, CONF_ = "OK", "ATTENTION", "CONFLIT"
_STATUS_CRITERIA = (
    ("R2", r"\br2\b|actifs? (?:tres |historiquement )?(?:volatils?|fluctuants?)|exposition aux actifs|part d'actifs (?:tres )?(?:volatils?|fluctuants?)"),
    ("R1", r"\br1\b|concentration(?! techno| sector| sur (?:les |la )?techno| esg)|plus grande position|position dominante|poids de la plus grande"),
    ("R4", r"\br4\b|volatilite(?! de nvda)|fluctuations? (?:annualisees? )?du portefeuille"),
    ("R5", r"\br5\b|plus forte baisse|drawdown|perte (?:historique )?maximale|baisse (?:historique )?maximale"),
    ("R7", r"\br7\b|nombre effectif|positions? effectives?|positions de poids egal|diversification \(nombre effectif"),
)
_LEVEL = r"(conflit|attention|vigilance)"
_NEG_NEAR = re.compile(r"(?:\bne\b|\bn'|\bpas\b|\baucun\w*\b|\bsans\b|\bjamais\b)")


def _status_facts(records: list) -> dict:
    """(profil, portefeuille) -> {règle: (statut, sens)} pour les constats réellement retournés pendant la requête."""
    out: dict = {}
    for r in records:
        if r.status != "ok" or not isinstance(r.result, dict):
            continue
        res = r.result
        groups = []
        if r.tool == "check_profile_constraints":
            groups.append((res.get("profile_id"), res.get("portfolio", "A"), res.get("findings") or []))
        elif r.tool == "compare_scenarios":
            for pf in ("A", "B"):
                groups.append((res.get("profile_id"), pf, (res.get(f"guardian_{pf}") or {}).get("findings") or []))
        for pid, pf, findings in groups:
            d = out.setdefault((pid, pf), {})
            for fd in findings:
                if fd.get("rule_id") in ("R1", "R2", "R4", "R5", "R7") and fd.get("status") in (OK_, ATT_, CONF_):
                    d[fd["rule_id"]] = (fd["status"], fd.get("direction", "max"))
    return out


def _derived_status_facts(records: list, active: str) -> dict:
    """Sans Guardian Check : cohérence R1 / R7 avec la mesure et les repères configurés transmis par evaluate_portfolio (jamais affiché comme statut)."""
    for r in records:
        if r.tool != "evaluate_portfolio" or r.status != "ok" or not isinstance(r.result, dict):
            continue
        prof = (r.result.get("key_facts") or {}).get("profil_actif") or {}
        c = r.result.get("concentration") or {}
        num = lambda x: float(re.search(r"\d+(?:[.,]\d+)?", str(x)).group(0).replace(",", "."))  # noqa: E731
        try:
            r1, r7 = prof["repères_concentration_plus_grande_position"], prof["repères_nombre_effectif_de_positions"]
            w, n = c["largest_position_weight_pct"], c["effective_number_of_positions"]
            s1 = CONF_ if w > num(r1["conflit"]) else (ATT_ if w > num(r1["attention"]) else OK_)
            s7 = CONF_ if n < num(r7["conflit"]) else (ATT_ if n < num(r7["attention"]) else OK_)
        except (KeyError, AttributeError, TypeError):
            continue
        return {(active, r.result.get("portfolio", "A")): {"R1": (s1, "max"), "R7": (s7, "min")}}
    return {}


def _level_set(level: str, relation: str, direction: str) -> set:
    """relation : 'cross' (franchi/dépassé), 'above', 'below', 'notcross'. Repère plafond (max) ou plancher (min, R7)."""
    conf = level == "conflit"
    if relation == "cross":
        return {CONF_} if conf else {ATT_, CONF_}
    if relation == "notcross":
        return {OK_, ATT_} if conf else {OK_}
    above = relation == "above"
    if direction == "min":
        above = not above                                   # pour un plancher, « sous le repère » = franchi
    if above:
        return {CONF_} if conf else {ATT_, CONF_}
    return {OK_, ATT_} if conf else {OK_}


def _claimed_statuses(seg_f: str, direction: str) -> set | None:
    """Ensemble des statuts compatibles avec ce que la phrase affirme ; None si elle n'affirme aucun statut identifiable."""
    sets = []
    for m in re.finditer(r"(depasse\w*|franchi\w*|excede\w*)\s+(?:(pas|plus|jamais)\s+)?(?:le |les |du |des |aucun |un )?(?:seuils?|reperes?)\s+(?:de |d')?" + _LEVEL, seg_f):
        neg = bool(m.group(2)) or bool(_NEG_NEAR.search(seg_f[max(0, m.start() - 12):m.start()]))
        sets.append(_level_set(m.group(3), "notcross" if neg else "cross", direction))
    for m in re.finditer(r"(?:seuils?|reperes?)\s+(?:de |d')?" + _LEVEL + r"[^.;,]{0,50}?\b(?:est|soit|sont|a ete|ont ete|n'est|ne soit|n'a ete)\s+(?:pas\s+)?(?:depasse|franchi)\w*", seg_f):
        neg = bool(re.search(r"n'est|ne soit|n'a ete|\bpas\b", m.group(0))) or bool(re.search(r"aucun\w*\s*$", seg_f[max(0, m.start() - 10):m.start()]))
        sets.append(_level_set(m.group(1), "notcross" if neg else "cross", direction))
    for m in re.finditer(r"(au-dessus|au-dela|superieur\w*|>)\s*(?:d[eu]s?|a|au|aux)?\s*(?:le |la |les |l')?(?:seuils?|reperes?)\s+(?:de |d')?" + _LEVEL, seg_f):
        sets.append(_level_set(m.group(2), "above", direction))
    for m in re.finditer(r"(en dessous|en deca|sous|inferieur\w*|<)\s*(?:d[eu]s?|a|au|aux)?\s*(?:le |la |les |l')?(?:seuils?|reperes?)\s+(?:de |d')?" + _LEVEL, seg_f):
        sets.append(_level_set(m.group(2), "below", direction))
    if re.search(r"\b(?:sous|en dessous d)\w*\s+(?:les|des) (?:seuils|reperes)\b(?! (?:de |d')" + _LEVEL + ")", seg_f):
        sets.append({OK_} if direction == "max" else None)
    for m in re.finditer(r"(?:→|->|\bstatut\b|\bniveau\b|:)\s*:?\s*(?:\*\*)?\s*(ok|conforme|attention|vigilance|conflit|point de vigilance|risque important)\b(?!\s*(?:de |d'|a |>|<|potentiel avec|si\b|des que|au-dela|au-dessus|en dessous|sous\b))", seg_f):
        sets.append({"ok": {OK_}, "conforme": {OK_}, "attention": {ATT_}, "vigilance": {ATT_}, "point de vigilance": {ATT_},
                     "conflit": {CONF_}, "risque important": {CONF_}}[m.group(1)])
    if re.search(r"\b(?:point|niveau) (?:de vigilance|d'attention)\b", seg_f) and not _NEG_NEAR.search(seg_f[:30]):
        sets.append({ATT_})
    if re.search(r"\b(?:pas de|aucun|sans) conflit\b|\bn'est pas en conflit\b", seg_f):
        sets.append({OK_, ATT_})
    elif re.search(r"\b(?:en conflit|conflit potentiel)\b", seg_f) and not re.search(r"(?:seuil|repere)s? de conflit", seg_f):
        sets.append({CONF_})
    if re.search(r"\baucun risque\b", seg_f):
        sets.append({OK_})
    sets = [x for x in sets if x]
    if not sets:
        return None
    out = set.intersection(*sets)
    return out or None                                       # affirmations contradictoires dans la phrase : ambiguë, pas de verdict


_GLOBAL_STATUS = re.compile(r"\baucun (?:seuil|repere)s?\b[^.;]{0,40}?\b(?:n'est|ne soit|n'a ete|ne sont|n'ont ete)\s+(?:pas\s+)?(?:depasse|franchi)|"
                            r"\btous les (?:reperes|seuils|criteres) sont respectes\b|\bdans les limites des (?:seuils|reperes)\b|"
                            r"\b(?:aucun|ne presente aucun) conflit (?:potentiel )?(?:avec|selon)\b")
_COUNT_WORDS = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6}


def _which(seg_f: str, options: list, pattern) -> list:
    return [o for o in options if re.search(pattern(o), seg_f)]


def _check_statuses(seg: str, seg_f: str, sfacts: dict, profiles: dict, active: str, pf_hint: str | None, rep: "ClaimReport", derived: bool = False) -> None:
    if not sfacts:
        return
    pids = sorted({k[0] for k in sfacts})
    named = [p for p in pids if re.search(rf"(?<![a-z0-9]){re.escape(fold(profiles.get(p, {}).get('display_name', p)))}(?![a-z0-9])", seg_f)]
    pid = named[0] if len(named) == 1 else (pids[0] if len(pids) == 1 else (active if not named and active in pids else None))
    if pid is None:
        return
    pfs = sorted({k[1] for k in sfacts if k[0] == pid})
    in_seg = [p for p in pfs if re.search(rf"\bportefeuilles? {p.lower()}\b|\*\*{p.lower()}\*\*|\({p.lower()}\)|\b{p.lower()} (?:presente|a |affiche|compte|reste|depasse|est)", seg_f)]
    pf = in_seg[0] if len(in_seg) == 1 else (pf_hint if len(in_seg) == 0 and pf_hint in pfs else (pfs[0] if len(pfs) == 1 else None))
    if pf is None:
        return
    statuses = sfacts[(pid, pf)]
    if re.search(r"technolog|\besg\b|controvers", seg_f):
        return                                               # préférence technologique ou ESG : aucun statut Guardian ne s'y rapporte
    crit = [rid for rid, pat in _STATUS_CRITERIA if re.search(pat, seg_f)]
    if len(crit) == 1 and crit[0] in statuses:
        real, direction = statuses[crit[0]]
        claimed = _claimed_statuses(seg_f, direction)
        if claimed is not None:
            if derived:
                rep.status_derived += 1
            else:
                rep.status_checked += 1
            if real not in claimed:
                rep.violations.append(Violation("statut_guardian",
                    (f"Le texte attribue au critère {crit[0]} un niveau incohérent avec la mesure et les repères configurés transmis par evaluate_portfolio "
                     f"(le Guardian Check n'a pas été exécuté pendant cette requête)." if derived else
                     f"Le texte attribue au critère {crit[0]} (portefeuille {pf}) un niveau incompatible avec le Guardian Check, qui retourne « {real} »."),
                    seg.strip()[:200]))
        return
    if derived:
        return                                               # constats globaux : seuls les vrais constats du Guardian Check font foi
    if crit:
        return                                               # plusieurs critères dans la phrase : pas d'attribution à un seul critère
    counts = {OK_: 0, ATT_: 0, CONF_: 0}
    for st_, _ in statuses.values():
        counts[st_] += 1
    if re.search(r"\baucun (?:seuil|repere)s?\b[^.;]{0,40}?\b(?:n'est|ne soit|n'a ete|ne sont)\s+(?:pas\s+)?(?:depasse|franchi)|\btous les (?:reperes|seuils|criteres) sont respectes\b", seg_f):
        rep.status_checked += 1
        if counts[ATT_] + counts[CONF_]:
            rep.violations.append(Violation("statut_guardian", f"Le texte affirme qu'aucun repère n'est dépassé (portefeuille {pf}), alors que le Guardian Check retourne "
                                            f"{counts[CONF_]} conflit(s) et {counts[ATT_]} point(s) de vigilance.", seg.strip()[:200]))
    for lvl, pat in ((CONF_, r"\b(\d+|deux|trois|quatre|cinq|six)\s+(?:\*\*)?(?:conflits potentiels|risques importants)"),
                     (ATT_, r"\b(\d+|un seul|une seule|deux|trois|quatre|cinq|six|aucun)\s+(?:\*\*)?points? (?:de vigilance|d'attention)")):
        for m in re.finditer(pat, seg_f):
            raw = m.group(1).replace(" seul", "").replace(" seule", "")
            n = 0 if raw == "aucun" else (int(raw) if raw.isdigit() else _COUNT_WORDS.get(raw))
            if n is None:
                continue
            rep.status_checked += 1
            if n != counts[lvl]:
                rep.violations.append(Violation("statut_guardian", f"Le texte annonce {n} {'conflit(s)' if lvl == CONF_ else 'point(s) de vigilance'} (portefeuille {pf}), "
                                                f"le Guardian Check en retourne {counts[lvl]}.", seg.strip()[:200]))


def check_claims(text: str, records: list, profiles: dict, active: str, universe=None) -> ClaimReport:
    """Vérifie les affirmations essentielles de `text` contre les résultats d'outils de la requête (voir CHECKED / NOT_CHECKED)."""
    rep = ClaimReport()
    facts = build_facts(records, profiles, active, universe)
    if not facts.has_tools:
        return rep
    folded = fold(text or "")
    names = {pid: fold(p.get("display_name", pid)) for pid, p in profiles.items()}
    named_in_text = {pid for pid, n in names.items() if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", folded)}
    profile_text = fold(" ".join(repr(p) for p in profiles.values()))
    name_re = re.compile("|".join(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])" for n in names.values()))
    for seg in (x for line in (text or "").split("\n") for x in _SPLIT.split(line) if x and x.strip()):
        sf = fold(seg)
        if not name_re.search(sf):
            continue
        for term in _INVENTED:
            if term in sf and term not in profile_text:
                rep.violations.append(Violation("persona_invente", f"Le texte attribue à un persona un élément absent de son profil officiel (« {term}… »).", seg.strip()[:200]))
    orders = _ORDERS.search(folded)
    if orders:
        s = max(0, orders.start() - 40)
        rep.violations.append(Violation("ordre", "Le texte formule un ordre ou une recommandation d'achat ou de vente : l'outil ne donne aucun conseil personnalisé.", (text or "")[s:orders.end() + 40]))
    prev_f = ""
    sfacts = _status_facts(records)
    dfacts = {} if sfacts else _derived_status_facts(records, active)
    pf_hint, lines = None, (text or "").split("\n")
    for line in lines:
        lf = fold(line)
        if re.match(r"\s*#", line):
            pf_hint = None                                       # nouvel en-tête de section : on oublie le portefeuille courant
        heads = set(re.findall(r"\bportefeuille ([ab])\b|\*\*([ab])\*\*", lf))
        heads = {x for t in heads for x in t if x}
        if len(heads) == 1 and len(lf) < 80:
            pf_hint = heads.pop().upper()                        # ligne courte du type « - **Portefeuille A** (Robert) »
        for seg in (x for x in _SPLIT.split(line) if x and x.strip()):
            if sfacts:
                _check_statuses(seg, fold(seg), sfacts, profiles, active, pf_hint, rep)
            elif dfacts:
                _check_statuses(seg, fold(seg), dfacts, profiles, active, pf_hint, rep, derived=True)
    if not sfacts:
        rep.status_unverified = bool(re.search(r"\b(?:conflit|vigilance|seuils? de|reperes? de)\b", folded))
        for seg in (x for line in lines for x in _SPLIT.split(line) if x and x.strip()):
            sf = fold(seg)
            if _GLOBAL_STATUS.search(sf) and not any(re.search(pat, sf) for _, pat in _STATUS_CRITERIA):   # un critère nommé rend la portée ambiguë
                rep.violations.append(Violation("statut_non_verifiable", "Le texte affirme un constat sur l'ensemble des repères du Guardian Check, "
                                                "qui n'a pas été exécuté pendant cette requête : ce constat ne peut pas être vérifié.", seg.strip()[:200]))
    prev_tickers: tuple = ()
    for seg in (s for line in (text or "").split("\n") for s in _SPLIT.split(line) if s and s.strip()):
        seg_f = fold(seg)
        _check_numbers(seg, seg_f, facts, rep, prev_tickers)
        prev_tickers = tuple(dict.fromkeys(a.key for a in _find_anchors(seg_f, facts) if a.kind == "ticker")) or prev_tickers
        _check_class_inclusion(seg, seg_f, facts, rep)
        _check_esg_semantics(seg, seg_f, facts, rep, prev_f)
        prev_f = seg_f
        _check_tech_conflict(seg, seg_f, facts, rep)
        _check_persona(seg, seg_f, facts, named_in_text, rep)
    seen, uniq = set(), []
    for v in rep.violations:
        k = (v.category, v.message, v.excerpt)
        if k not in seen:
            seen.add(k)
            uniq.append(v)
    rep.violations = uniq
    return rep
