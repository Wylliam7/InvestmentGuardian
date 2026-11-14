# DECISIONS — Investment Guardian

Statut : décisions techniques **tirées de votre brief** (validées par vous) ; décisions financières **proposées** (à valider) ; hypothèses **à confirmer**.

## 0. Mise à jour du 2026-11-14 (validation du participant et phase 0)

**Validé par le participant** : architecture à un agent Strands + Bedrock ; modèle `global.amazon.nova-2-lite-v1:0` en `us-east-1` ; moteur financier indépendant de l'IA ; Guardian Check déterministe ; traces réelles des outils ; Streamlit ; Robert et Amira ; **hypothèses financières du §2.2, dont le rééquilibrage mensuel (F-06) et la grille commune TSX ∩ US (F-04)**. Les hypothèses H-05 et H-06 sont donc **confirmées**.

**Changements de périmètre (échéances officielles)**
- Échéances : GitHub + application dimanche 2026-11-15 23 h 59 ; vidéo, one pager et documentation technique lundi 2026-11-16 14 h ; pitch des finalistes vendredi 2026-11-20. H-01 est **résolue**.
- **MVP réduit** : 4 portefeuilles, 5 règles (R1, R2, R4, R5, R7), **4 outils** (`get_profile`, `evaluate_portfolio`, `check_profile_constraints`, `compare_scenarios`). **P-01 est modifiée** : `analyze_asset` et `sensitivity_sweep` passent après le MVP.
- **Ordre de développement** : tranche verticale d'abord (Robert, un portefeuille, calculs vérifiés, mini-interface, agent avec vrai outil, trace), puis enrichissement.
- P-08 (mode sans AWS) : le MVP ne garde que le **message d'erreur explicite** et le moteur indépendant d'AWS ; relecture de traces et rapport par gabarits passent après le MVP.

**Politique sur les seuils (nouvelle règle, valide pour F-15)**
1. Les seuils sont fixés et gelés **avant** d'exécuter les portefeuilles de démo.
2. Aucun seuil n'est modifié pour forcer une conclusion prédéterminée. Si un diagnostic surprend, il est conservé et expliqué.
3. Toute modification ultérieure est consignée ici avec une raison indépendante du résultat souhaité.
4. Chaque règle est justifiée, configurable et étiquetée **heuristique** (aucune ne provient d'une norme réglementaire).

**Mesure effectuée en V0 (écart crypto grille commune vs série complète, en USD, adj_close).** BTC-USD : drawdown maximal −75,9 % (1 827 jours) contre −75,4 % (grille) ; volatilité 50,8 % (365 j/an) contre 51,1 % (grille). ETH-USD : −78,7 % contre −77,8 % ; volatilité 68,5 % contre 68,4 %. L'écart est inférieur à 1 point de drawdown et à 0,4 point de volatilité, avec un sens attendu (la grille sous-estime légèrement le drawdown). Les limites affichées dans l'application restent valides.

**Calendrier commun et cryptos (précision de F-04).** La grille TSX ∩ US retire les mouvements des week-ends et des jours fériés où une crypto est négociée : 545 des 1 827 jours crypto, dont 23 en semaine, ne sont pas observés individuellement. Les rendements des jours conservés restent exacts, car le prix du jour suivant incorpore le cumul. La volatilité et le drawdown crypto peuvent être légèrement sous-estimés. Mesure indicative de l'audit : volatilité du BTC 50,8 % sur la base de ses 365 jours/an, contre 51,5 % sur la grille commune (écart faible, mais pas nul ; le drawdown n'a pas été comparé). V0 mesurera l'écart sur le drawdown, et la **fiche de limites de l'interface le mentionnera**.

**Distinction faits / scénarios.** Les résultats historiques (2021-11-12 → 2026-11-12) sont des *faits descriptifs*. Les scénarios (« NVDA à 40 % ») sont des *simulations sur cette même période*, jamais une prévision. L'interface et le prompt de l'agent portent cette distinction ; l'agent ne formule aucune projection de rendement futur.

**Environnement (H-10, H-11 résolues).** Workspace `/workshop` sur Linux. Python 3.9.25 insuffisant ; **Python 3.11.18 via `uv`** dans `/workshop/.venv` ; `strands-agents 1.65.0`, `boto3 1.44.3`. Identifiants AWS : rôle d'instance `WSParticipantRole` (type `iam-role`), vérifiés sans affichage de secrets ; à revérifier à chaque session. Aucune clé IAM créée.

**Résultat du test de fumée (T-A résolu).** `BedrockModel` accepte l'identifiant `global.amazon.nova-2-lite-v1:0` tel quel ; un appel d'outil réel fonctionne. Deux incidents ont conduit à deux règles (détail dans ARCHITECTURE.md §13) :
- **D-01** : tout décorateur d'outil utilise `functools.wraps` (sinon le schéma d'outil est faux).
- **D-02** : le prompt exige de signaler l'échec d'un outil plutôt que de calculer soi-même, et les chiffres affichés proviennent des objets d'outils.

**Hypothèses restant à confirmer** : H-02 (règles techniques AWS officielles), H-03 (publication des CSV), H-04 (langue : français par défaut), H-07 (seuils : valeurs de départ du PROJECT_SPEC §7, à geler en V1), H-08 (quatre portefeuilles, voir ci-dessous), H-09, H-12, H-13, et le fuseau horaire des échéances (Montréal supposé).

**Quatre portefeuilles prédéfinis proposés (H-08)** — composition indicative, à geler en V1 sans optimisation sur les résultats :
1. *Robert prudent* : XBB.TO, ZST.TO, XIU.TO, RY.TO, JNJ, GLD ; poids défensifs majoritaires.
2. *Robert tenté par NVDA* : NVDA 40 %, le reste réparti entre XBB.TO, XIU.TO, RY.TO, ZST.TO.
3. *Amira croissance diversifiée* : QQQ, SPY, XIU.TO, NVDA, SHOP.TO, BTC-USD (petite part), XBB.TO.
4. *Amira tech et crypto concentrée* : NVDA, TSLA, BTC-USD, ETH-USD, QQQ dominants.

## 1. Décisions techniques validées (issues du brief)

| Id | Décision | Raison |
|---|---|---|
| T-01 | Langage Python ; interface Streamlit ; graphiques Plotly | Imposé par le brief ; rapide pour un développeur solo |
| T-02 | pandas + NumPy ; autres bibliothèques seulement si nécessaires | Peu de dépendances, installation fiable |
| T-03 | Amazon Bedrock + Strands Agents, un agent principal | Contribution AWS réelle (critère qualifiant) ; simplicité |
| T-04 | Modèle `global.amazon.nova-2-lite-v1:0`, région `us-east-1` | Test CLI réussi selon vous ; **compatibilité Strands à vérifier** (T-A) |
| T-05 | Identifiants via l'environnement, jamais dans le code ni dans git | Sécurité ; jetons temporaires |
| T-06 | Architecture en quatre couches (UI / finance / règles / agent) | Testabilité ; moteur utilisable sans AWS |
| T-07 | Aucune transaction, aucun levier, aucune vente à découvert | Cadre officiel (simulation) |
| T-08 | CAD comme devise de référence | Brief ; coût de conversion maîtrisé par les données FX fournies |
| T-09 | Robert et Amira dans le MVP ; Mateo plus tard | Brief ; extensibilité prévue |

## 2. Décisions proposées (à valider)

### 2.1 Architecture

| Id | Proposition | Raison | Compromis |
|---|---|---|---|
| P-01 | **Un agent**, **quatre outils au MVP** (`get_profile`, `evaluate_portfolio`, `check_profile_constraints`, `compare_scenarios`) ; `analyze_asset` et `sensitivity_sweep` après MVP. *(Version initiale : six outils.)* | `get_profile` évite de passer le profil en texte libre ; la sensibilité est explicitement valorisée par le guide officiel | Deux outils de plus ; chacun reste mince |
| P-02 | La **gouvernance est déterministe** (Guardian Check en Python), pas un agent | Règles testables, reproductibles, vérifiables ; clarté du rôle de l'agent | Moins « multi-agent » en apparence ; le jury valorise la clarté, pas le nombre |
| P-03 | **Explicabilité = trace réelle + provenance + contrôle numérique**, sans second modèle | « Fidèle aux actions observables » ; pas d'explication inventée a posteriori | Le contrôle numérique ne vérifie pas le sens des phrases |
| P-04 | Le portefeuille courant est injecté côté serveur dans les outils | Moins de risques de chiffres mal recopiés par le modèle | Le modèle ne voit les poids qu'au travers des résultats d'outils |
| P-05 | Aucun service AWS autre que Bedrock dans le MVP | Brief et règles : ne pas multiplier les services | Contribution AWS limitée à Bedrock ; la qualité d'intégration doit être démontrée par la trace, la sécurité et la gestion d'erreurs |
| P-06 | Exécution **locale** ; pas d'hébergement cloud | Compte temporaire ; coût ; temps | Pas de démonstration « déployée » ; remplacé par README et vidéo |
| P-07 | Bedrock Guardrails en **P2**, seulement si valeur démontrée | Crée une ressource AWS ; hors de cette étape | Garde-fous portés par le code et le prompt |
| P-08 | Mode sans AWS : rapport par gabarits ; relecture d'une trace **réelle** étiquetée | Honnêteté ; résilience après suppression du compte | La relecture n'est pas interactive |
| P-09 | Python 3.11 ou 3.12 installé via `uv` ; dépôt compatible Windows/Linux (`pathlib`) | La machine actuelle a Python 3.9.25 ; Strands demande probablement plus récent | Étape d'installation de plus |
| P-10 | Profils et règles en **YAML**, validés par schéma | Ajouter Mateo sans toucher au code | Un peu de code de validation |

### 2.2 Finance

| Id | Proposition | Raison | Risque / limite |
|---|---|---|---|
| F-01 | Rendements sur `adj_close`, jamais sur `close` ; `corporate_actions.csv` non utilisé en calcul | Évite le double ajustement ; inclut les dividendes | Rétro-ajustement : valeurs changent si re-téléchargées (données figées par SHA-256) |
| F-02 | Convertir en CAD **avant** de calculer les rendements : prix USD × USDCAD(t) | Capture le risque de change réel pour un investisseur canadien | Aucune couverture de change ; l'effet FX est un risque réel affiché |
| F-03 | Taux de change : dernier taux publié ≤ t (report vers l'avant seulement) | Pas de fuite d'information ; la README recommande le report | 10 jours de grille concernés ; décalage 16 h 00/16 h 30 ET négligé et documenté |
| F-04 | **Grille de calcul = intersection des jours TSX et US (1 228 jours)** ; cryptos prises aux mêmes dates | Aucune donnée inventée ni rendement artificiel de 0 % les jours fériés ; les rendements multi-jours préservent le cumul | Perte de 54 jours d'information (≈ 4 %) ; les mouvements de crypto du week-end ne sont pas observés individuellement, ce qui peut **sous-estimer** la volatilité et les drawdowns crypto (documenté) |
| F-05 | Alternative écartée : union des calendriers avec report des prix | Fabrique des rendements nuls qui réduisent artificiellement volatilité et corrélations | — |
| F-06 | **Rééquilibrage mensuel** vers les poids cibles (dernier jour de grille du mois), sans frais, sans impôts | Hypothèse réaliste et simple ; les poids affichés restent proches des poids cibles | Alternative « achat et conservation » proposée comme option distincte ; jamais mélangée dans une comparaison |
| F-07 | Rendements **simples** quotidiens ; rendement annualisé **géométrique** `(V_fin/V_début)^(1/années) − 1` | Cohérent avec un portefeuille ; évite de sommer des rendements | Les années sont mesurées en jours calendaires/365,25 |
| F-08 | Volatilité annualisée = σ(rendements journaliers) × √(facteur observé ≈ 245,6) ; 252 en option | Évite une annualisation trompeuse | Les rendements après férié couvrent plusieurs jours (hétéroscédasticité légère) |
| F-09 | Fenêtre par défaut = période complète (2021-11-12 → 2026-11-12) ; annualisation non présentée si < 1 an | Évite des annualisations extrapolées | Une seule fenêtre de 5 ans ; sous-périodes en sensibilité |
| F-10 | **Même grille, même fenêtre** dans toute comparaison | Évite les comparaisons sur périodes différentes | Un actif plus récent réduirait la fenêtre commune (non applicable ici : tous les actifs couvrent 5 ans) |
| F-11 | Aucun Sharpe/Sortino/alpha/bêta dans le MVP | Exigerait un taux sans risque et de la modélisation ; risque d'être trompeur | Moins de ratios classiques ; remplacé par volatilité, drawdown, contribution au risque |
| F-12 | Macro (`macro_rates.csv`) hors calculs du MVP | Fuite temporelle (mois de référence vs publication) ; peu de valeur pour la décision étudiée | Pas de lecture « régime économique » ; envisageable comme contexte descriptif |
| F-13 | Concentration : poids max, top-3, HHI, N effectif = 1/HHI, contribution au risque (Euler) | Mesures simples et auditables | Le secteur provient d'étiquettes simplifiées ; pas de look-through des FNB |
| F-14 | Actifs « volatils » = volatilité historique annualisée > 35 % **ou** crypto ; actifs « défensifs » = FNB obligataires | Définitions explicites ; le seuil de 35 % est une heuristique | Dépend de la fenêtre ; documentée et affichée |
| F-15 | Seuils du Guardian Check = **heuristiques pédagogiques**, jamais présentées comme normes | Exigence du brief et du cadre officiel | Peuvent sembler arbitraires ; atténué par la transparence et la configurabilité |
| F-16 | Pas de note globale agrégée ; décompte des constats par statut | Un score unique cache des seuils arbitraires | Moins d'impact visuel ; compensé par cartes de statut claires |
| F-17 | Les comparaisons n'emploient pas « meilleur/pire » ; elles énumèrent écarts, avantages et contreparties | Exigence du brief ; cadre officiel | Peut paraître moins tranché |
| F-18 | Un capital fictif de 100 000 CAD sert uniquement à la visualisation | Lisibilité | Aucun sens économique propre |
| F-19 | Biais du survivant, fenêtre unique et « passé ≠ avenir » affichés dans l'interface | Exigence officielle sur l'honnêteté | Texte supplémentaire à l'écran |
| F-20 | Règle de renormalisation des scénarios (« porter NVDA à 40 % ») : les autres poids sont réduits **au prorata** | Règle simple, déterministe, affichée | Le choix des positions réduites influence le résultat ; l'utilisateur peut éditer manuellement |

## 3. Hypothèses à confirmer

| Id | Question | Pourquoi c'est important | Ma recommandation par défaut |
|---|---|---|---|
| H-01 | **Quelle est la date limite de soumission et la plateforme de dépôt ?** | Toute la planification | Demander aux organisateurs ; plan modulaire |
| H-02 | Existe-t-il des **règles techniques officielles AWS** au-delà de la diapositive 7 (services imposés ou interdits, compte, région) ? | Admissibilité | Demander ; on suppose Bedrock suffisant |
| H-03 | Les CSV peuvent-ils être publiés sur un **GitHub public** ? | Conditions Yahoo/Valet | Ne pas les publier ; README explicite |
| H-04 | Langue de l'application et de la vidéo (français, anglais, bilingue) ? Le PDF et le PPT existent dans les deux langues | UX, jury | Interface et agent en **français**, noms de métriques EN/FR clairs ; à confirmer |
| H-05 | Rééquilibrage mensuel (F-06) acceptable ? | Tous les résultats | Oui, option « achat et conservation » en second plan |
| H-06 | Grille TSX ∩ US (F-04) acceptable malgré la perte des week-ends crypto ? | Volatilité crypto | Oui, avec note ; une analyse de sensibilité en phase 2 mesurera l'écart |
| H-07 | Seuils initiaux de PROJECT_SPEC §7 | Diagnostics | Valider après avoir vu les résultats réels sur 3 portefeuilles ; ajustement documenté |
| H-08 | Portefeuilles prédéfinis : lesquels ? | Démo | Proposition : « Robert prudent », « Robert tenté par NVDA (40 %) », « Amira croissance diversifiée », « Amira tech + crypto concentrée » |
| H-09 | Indiquer l'intention de l'investisseur par champs structurés (objectif, perte maximale acceptable) plutôt que par texte libre | Qualité du Guardian Check | Champs structurés + note libre pour l'agent |
| H-10 | Environnement : votre brief indique Windows/PowerShell, la session Kiro actuelle est sous **Linux** avec Python 3.9.25 | Reproductibilité | Code portable ; Python 3.11/3.12 via `uv` ; confirmer la machine de démo |
| H-11 | L'identité d'accès AWS (jetons manuels ou rôle) sur la machine de démo | Phase 0 | Vérifier en phase 0 sans copier de secret |
| H-12 | Budget d'inférence acceptable pour les tests | Contrôle des coûts | Plafonds de jetons et d'appels ; quelques dizaines de requêtes |
| H-13 | Autoriser l'ajout de données publiques (ESG, FNB look-through) hors jeu de départ ? | Post-MVP | Non pour le MVP |

## 4. Compromis d'architecture

| Compromis | Option choisie | Gain | Perte |
|---|---|---|---|
| Un agent vs plusieurs | Un | Clarté, fiabilité, solo | Impression d'architecture plus modeste |
| Gouvernance déterministe vs LLM | Déterministe | Reproductibilité ; testabilité | Moins de flexibilité de langage naturel (compensée par l'agent pour l'explication) |
| Local vs cloud | Local | Simplicité, coût | Pas de URL publique |
| CSV vs base | CSV en mémoire | Aucune infrastructure | Limite d'échelle (hors sujet ici) |
| Trace maison vs hooks du SDK | Wrappers maison | Indépendance de la version du SDK ; preuve d'exécution réelle | Un peu de code |
| Précision vs lisibilité des seuils | Seuils simples, affichés | Compréhension par le jury | Granularité limitée |
| Outils nombreux vs peu | 6 | Couverture de scénarios | Risque de mauvais choix d'outil par le modèle ; atténué par descriptions précises et tests |

## 5. Critique de notre concept initial

**Points forts** : question claire (cohérence décision/profil) ; remet en question la demande de Robert, ce qui est précisément le test officiel ; moteur déterministe séparé ; explicabilité observable plutôt que raisonnement supposé ; honnêteté sur les limites ; mode sans AWS honnête.

**Lacunes et corrections apportées**
1. *One pager absent du brief* → ajouté.
2. *Objectif de Robert simplifié en « préservation »* : le PDF indique « préserver le capital tout en maintenant un potentiel de croissance » → les règles ne poussent pas vers 100 % d'obligations.
3. *Amira et diversification* : le PDF précise « éviter de miser exclusivement sur les technologies » → règle sectorielle R8 et règle crypto R3 propres à Amira.
4. *Sensibilité* absente des outils prévus alors que le guide la recommande → `sensitivity_sweep`.
5. *Qualité d'intégration AWS (15 %)* reposant sur Bedrock seul → la démonstration doit montrer clairement les appels, la sécurité, la gestion d'erreurs et le rôle effectif du modèle ; pas de services ajoutés par décor.
6. *Risque de « score » opaque dans le Guardian Check* → pas de note globale.
7. *Rendement historique de NVDA très élevé* (44 %/an dans les données) : un affichage naïf valide la demande de Robert ; les rendements sont donc présentés avec le drawdown, la durée sous l'eau et l'avertissement de biais du survivant.
8. *Annualisation et calendrier* non spécifiés → F-04, F-07, F-08.

**Risques restants** : compatibilité Strands/Nova 2 Lite non testée ; compte AWS temporaire ; date limite inconnue ; seuils à calibrer ; fenêtre historique unique.
