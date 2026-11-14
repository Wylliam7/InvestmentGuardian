# IMPLEMENTATION_PLAN — Investment Guardian (v2, révisé le 2026-11-14)

Statut : **phase 0 et V0 terminées** (2026-11-14, ~18 h 50 UTC). **V1 n'est pas commencée : en attente de validation du participant.**
Remplace la v1 (51–68 h), jugée trop ambitieuse pour un développeur solo.

## Avancement V2 (2026-11-14, branche locale `feature/v2-ux`, non publiée)

**V2 terminée, en attente de validation.** Départ du commit V1 `e5044f8` ; `main` et `feature/v1` n'ont pas été modifiées ; aucun `git push`. Les changements de V2 ne sont pas commités.

- **Ajouts** : couche d'explications déterministes (`src/guardian/explain/`), composants et réorganisation de l'interface (`app/components.py`, `app/app.py`), bouton « Explique-moi mes risques avec l'IA » (même agent), traçabilité à deux niveaux, barre latérale simplifiée, comparaison simplifiée, confirmation d'analyse, glossaire et info-bulles.
- **Inchangés (vérifié par test)** : moteur financier, règles, seuils, profils, données, allocations prédéfinies.
- **Tests** : 225 tests hors AWS réussis, 8 tests live ignorés par défaut ; 3 requêtes agent réelles contre Bedrock pour valider le bouton IA (Robert, Amira, puis Robert après resserrage de la consigne).
- **Reste à faire** (hors V2, après votre validation) : revue visuelle dans le navigateur, README, dépôt, livrables de soumission (vidéo, documentation technique, one pager) avant lundi 14 h.

## Avancement V1 (2026-11-14, branche locale `feature/v1`, non publiée)

**V1 terminée, en attente de validation.** Départ du commit V0 `ba8dfcf` ; `main` n'a pas été modifiée ; aucun `git push`. Les changements de V1 ne sont pas encore commités.

- **Ajouts** : profil Amira ; règle R7 et information R10 ; quatre portefeuilles prédéfinis ; constructeur de portefeuille (ajout, retrait, modification, validation, normalisation explicite) ; comparaison A/B ; outils `get_profile` et `compare_scenarios` ; note de contexte par requête ; vérification déterministe des horizons cités ; interface en quatre onglets (Portfolio Builder, Risk Dashboard, Comparaison A/B, AI Guardian & Explicabilité).
- **Tests** : 143 tests hors AWS réussis, 5 tests live ignorés par défaut ; 5 requêtes agent réelles contre Bedrock pendant V1 (voir DECISIONS.md section 0 bis pour les résultats).
- **Corrections finales après revue visuelle (même jour)** : conflit profil/question (clarification sans appel au modèle + garde-fou des outils), scénarios par profil sans écrasement, thème et mise en page plus lisibles, preuve visible des outils appelés (dont `compare_scenarios`). Détail dans DECISIONS.md, « Corrections finales V1 ». 181 tests hors AWS réussis, 5 tests live ignorés par défaut ; 3 requêtes agent supplémentaires contre Bedrock pour la validation.
- **Reste pour V2 et la démonstration** : voir la fin de ce document (« Reste à faire »).

## Avancement réel (V0)

| Phase | État | Notes |
|---|---|---|
| 0 | ✅ Terminée | Voir ARCHITECTURE.md §13 |
| **V0** | ✅ Terminée (à valider) | Moteur, Guardian Check (R1, R2, R4, R5), agent Bedrock réel avec 2 outils, trace, page Streamlit, 68 tests hors AWS + 2 tests live |
| V1 | ⏳ Non commencée | Voir « À développer en V1 » ci-dessous |

**Fichiers V0** : `src/guardian/{data/loader.py, finance/{panel,portfolio,metrics,analysis}.py, rules/engine.py, agent/{service,tools,tracer,agent,aws_status}.py}` · `app/{app.py,charts.py}` · `config/{profiles,guardian_rules,presets,data_manifest}.yaml` · `tests/{conftest,test_metrics,test_panel_portfolio,test_real_data,test_rules,test_agent_offline,test_charts_app,test_live_bedrock}.py` · `requirements.txt`, `pyproject.toml`, `.gitignore`, `.env.example`.

**Correctif V0 du 2026-11-14 (validation des appels d'outils).** « Tour N » comptait les requêtes utilisateur (N-ième appel de `GuardianAgent.ask()`), pas les cycles internes de Strands. L'agent conservait l'historique : à la requête 2, le modèle réutilisait les résultats d'outils de la requête 1 sans rappeler d'outil, et la validation (qui n'accepte que les outils de la requête courante) retenait la réponse à raison. Corrections : chaque requête repart d'une conversation vide ; un verrou sérialise les requêtes ; l'interface affiche toutes les requêtes et utilise « Requête n° N » ; 12 tests de régression dans `tests/test_request_scoping.py` + 1 test live. Limite assumée : pas de mémoire de conversation entre requêtes en V0.

**Lancer l'application** (depuis `/workshop`) :
```bash
.venv/bin/streamlit run app/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true --server.enableCORS false --server.enableXsrfProtection false
```
URL dans Kiro Web : `https://dubujj7yle6l0.cloudfront.net/proxy/8501/` (valeur de `VSCODE_PROXY_URI`, port 8501), ouverte dans le navigateur où votre session Kiro Web est connectée.

**Tests** : `.venv/bin/python -m pytest -q` (hors AWS) ; `RUN_LIVE=1 .venv/bin/python -m pytest -m live -s` (appels Bedrock réels).

**À développer en V1** (proposition) : Amira (profil + seuils par profil pour R1, R2, R4, R5) ; règle R7 ; quatre portefeuilles prédéfinis et éditeur de poids ; outils `get_profile` et `compare_scenarios` ; vue de comparaison ; mise en page en trois vues ; contrôle numérique automatique si le temps le permet.

## 1. Contraintes de calendrier [OFFICIEL, selon les consignes logistiques]

| Échéance | Livrable | Temps restant depuis cette session* |
|---|---|---|
| **Dim. 2026-11-15, 23 h 59** | GitHub (code, README) + application | ≈ 34 h |
| **Lun. 2026-11-16, 14 h** | Vidéo, one pager, documentation technique | ≈ 48 h |
| Ven. 2026-11-20 | Pitch des finalistes | — (si sélectionné) |

\*Session démarrée le samedi 14 nov. à 18 h 38 UTC (13 h 38 à Montréal, si les échéances sont à l'heure de Montréal : **à confirmer**). Après sommeil et pauses, il reste réalistement **≈ 18–22 h de travail effectif avant le gel de dimanche** et **≈ 5–6 h lundi matin** pour la vidéo et les documents.

Le compte AWS est temporaire : **la démonstration Bedrock doit être enregistrée tôt**, pas lundi à 13 h.

## 2. Principes

1. **Tranche verticale d'abord** (V0), puis enrichissement par couches. L'interface n'est pas repoussée à la fin.
2. **Chaque phase se termine par quelque chose qui tourne** et qu'on peut montrer.
3. **Tests** : ciblés sur les calculs critiques (valeurs connues), pas de couverture exhaustive.
4. **Gel des fonctionnalités dimanche 18 h** (locale) : après, uniquement correctifs, README, enregistrement.
5. **Honnêteté** : ce qui n'est pas fait est listé comme limite, pas simulé.

## 3. Périmètre MVP (validé)

Robert et Amira ; **4 portefeuilles prédéfinis** ; rendement, volatilité, drawdown, concentration ; conversion CAD et grille commune ; **5 contrôles Guardian (R1, R2, R4, R5, R7)** ; tableau de bord Streamlit ; agent Strands réel avec **4 outils** (`get_profile`, `evaluate_portfolio`, `check_profile_constraints`, `compare_scenarios`) ; comparaison de deux allocations ; trace des outils, sources, hypothèses.

**Hors MVP (seulement si stable)** : `analyze_asset`, `sensitivity_sweep`, contrôle numérique automatique, relecture de traces, rapport par gabarits, corrélations/contribution au risque (si non faites dans le noyau), R3/R6/R8/R9, fenêtres glissantes.

## 4. Phases

| Phase | Contenu | Effort | Livrable testable |
|---|---|---|---|
| **0** ✅ | Dépôt Git local, `.gitignore`, Python 3.11, Strands + Bedrock + outil jouet | fait | Aller-retour avec appel d'outil observé |
| **V0** | **Tranche verticale** : Robert, un portefeuille, calculs vérifiés, mini-interface, agent Bedrock + vrai outil, trace | 4–5 h | Démo minimale enregistrable |
| **V1** | Guardian Check (5 règles) + 4 préréglages + Amira | 3–4 h | Même portefeuille : métriques identiques, constats différents |
| **V2** | Comparaison A/B + `compare_scenarios` + vue Risk Dashboard complète | 3–4 h | Scénario Robert 40 % → 10 % de bout en bout |
| **V3** | Provenance, limites, erreurs AWS, README, dépôt prêt | 2–3 h | Un tiers peut lancer l'application |
| **Gel** | Dimanche 18 h (locale), push **après approbation du participant** | | |
| **V4** | Vidéo (Bedrock en ligne), one pager, documentation technique | 5–6 h (lundi matin, mais **enregistrement dès dimanche soir**) | Trois livrables du lundi 14 h |
| Après MVP | Éléments du §3 « hors MVP », selon le temps et la sélection de finaliste | variable | |

Total MVP ≈ **12–16 h** de développement + 5–6 h de livrables.

### V0 — Tranche verticale (4–5 h)
- **Données** : lecture de `prices_daily.csv`, `fx_usdcad_daily.csv`, `assets_universe.csv` depuis `Datathon2026/…` (chemin configurable, lecture seule) ; calcul des SHA-256 ; grille TSX ∩ US ; FX reporté vers l'avant ; prix en CAD.
- **Calcul** : portefeuille à rééquilibrage mensuel ; rendement cumulé et annualisé, volatilité (facteur observé), max drawdown, poids max, HHI, N effectif ; objet `Provenance`.
- **Tests à valeur connue** (peu nombreux, ciblés) : drawdown de 100→120→60→90 = −50 % ; HHI de poids égaux = 1/n ; actif USD à prix constant = rendement du change ; rendement composé d'un +1 %/jour ; refus de Σ ≠ 100 %, poids négatifs, ticker inconnu ; absence de report FX vers l'arrière ; grille de 1 228 jours et 10 jours FX reportés.
- **Profil** : `config/profiles.yaml` avec Robert (Amira ajoutée en V1).
- **Agent** : `get_profile` et `evaluate_portfolio` ; décorateur de traçage avec `functools.wraps` ; prompt système avec consigne d'échec explicite d'outil.
- **Interface** : une page Streamlit : choix du profil, un portefeuille préréglé (NVDA 40 %), tableau de métriques, zone de chat, panneau de trace.
- **Critère de sortie** : question « Pourquoi ce portefeuille est-il risqué pour Robert ? » → l'agent appelle réellement `get_profile` puis `evaluate_portfolio`, la trace s'affiche, les chiffres correspondent aux valeurs de contrôle de DATA_AUDIT.md §8 (écart < 0,5 point sur l'actif unique NVDA avec les mêmes conventions).
- **Sauvegarde immédiate** : exporter une trace JSON réelle dans `traces/` (hors git par défaut) et enregistrer un court écran de secours.

### V1 — Guardian Check, préréglages, Amira (3–4 h)
- `config/guardian_rules.yaml` : R1, R2, R4, R5, R7 avec seuils par profil, justification, étiquette « heuristique », version. **Seuils figés avant d'exécuter les portefeuilles de démo** (voir DECISIONS.md F-15 et politique du PROJECT_SPEC §7).
- Fonctions pures par règle ; constat : statut, valeur mesurée, seuil, formule, profil.
- Tests : un cas par règle et par statut ; même portefeuille → mêmes métriques pour Robert et Amira ; changement de seuil → changement de statut.
- Outil `check_profile_constraints`.
- **Quatre portefeuilles** (H-08) définis dans `config/presets.yaml`.
- Liste d'informations manquantes et limites (R10), statique et affichée.

### V2 — Comparaison et tableau de bord (3–4 h)
- `compare_scenarios` : portefeuille B = A modifié (`set_weight`, renormalisation au prorata, règle affichée) ; même grille et même fenêtre ; écarts de rendement, volatilité, drawdown, concentration ; texte neutre, **aucun « meilleur »**.
- Interface en trois vues (`st.tabs` ou pages) : **Portfolio Builder**, **Risk Dashboard** (métriques, performance normalisée, drawdown, répartition par classe, cartes Guardian), **AI Guardian & Explainability** (chat, trace, provenance, limites).
- Tests : comparaison d'un portefeuille avec lui-même = écarts nuls ; erreur si les fenêtres diffèrent ; test sur l'absence de libellés « meilleur » dans les gabarits.

### V3 — Robustesse et dépôt (2–3 h)
- Messages d'erreur AWS explicites (jetons expirés, accès refusé, throttling, modèle introuvable) ; chat désactivé sans perturber le reste.
- Fiche de provenance dépliable ; bandeau « simulation, pas un conseil » ; avertissements (biais du survivant, fenêtre unique, passé ≠ avenir, **calendrier commun**).
- README : installation (`uv`, Python 3.11+), emplacement des données (non publiées), variables d'environnement, lancement, tests, reproduction du scénario de démo.
- Vérification de secrets : `git grep` sur motifs de clés AWS ; relecture de `git status` ; **aucun push sans approbation**.

### V4 — Livrables du lundi 14 h
- **Vidéo (≈ 5 min)** : plan de PROJECT_SPEC / ancien §4 ; enregistrée avec Bedrock en ligne ; si possible dès dimanche soir, avec reprise lundi si nécessaire.
- **Documentation technique** : consolidation des cinq documents (méthodes, sources, traitements, hypothèses, explicabilité avec exemple conclusion → trace → donnée, validations, limites, améliorations).
- **One pager** (1 page max) : problème, approche agentique, originalité, données, explicabilité, valeur.
- Préparer un **plan B** : si Bedrock tombe lundi, utiliser la trace et la vidéo déjà enregistrées, avec mention explicite.

## 5. Planification horaire indicative (à ajuster selon votre disponibilité)

| Créneau | Travail |
|---|---|
| Sam. soir | V0 (données, calculs, tests, agent, mini-UI), trace de secours |
| Sam. nuit / dim. matin | V1 |
| Dim. après-midi | V2, premier enregistrement vidéo brut |
| Dim. fin d'après-midi | V3 ; **gel 18 h** ; push après approbation (la limite officielle est 23 h 59) |
| Dim. soir | Enregistrement final de la démo ; ébauche one pager |
| Lun. matin | Documentation technique, one pager, montage, soumission avant 14 h |

## 6. Règles de coupe (si le temps manque)

Ordre de suppression : (1) tout le « hors MVP » ; (2) graphique de corrélations ; (3) préréglages 3 et 4 ; (4) règle R7 ; (5) mise en forme avancée. **Ne jamais retirer** : calculs testés, Guardian Check (≥ R1, R2, R4), agent réel avec trace, avertissements, README.

## 7. Risques restants

| Risque | Réponse |
|---|---|
| Expiration/suppression du compte AWS avant l'enregistrement | Enregistrer une trace réelle dès V0 ; vidéo dès que V2 tourne |
| Le modèle contourne un outil en échec (observé en phase 0) | Prompt strict ; statut d'erreur visible ; chiffres affichés depuis les objets d'outils ; test manuel de ce cas |
| Schémas d'outils plus riches mal gérés par Nova 2 Lite | Tester `compare_scenarios` dès qu'il existe ; garder des paramètres simples (listes plates, enums) |
| Erreur financière subtile | Tests à valeur connue ; contrôle croisé avec DATA_AUDIT.md §8 |
| CSV non redistribuables, alors que le jury doit lancer l'application | README précis ; interroger les organisateurs ; le jury dispose du ZIP officiel |
| Fatigue / sous-estimation | Gel dimanche 18 h ; règles de coupe ; jalons visibles |
| Calendrier commun : perte des mouvements crypto du week-end | Documenté (DECISIONS F-04) ; mesure de l'écart sur BTC/ETH dans V0 et affichage dans les limites |
| Fuseau horaire des échéances | À confirmer (Montréal supposé) |


## Reste à faire après V1 (proposition, à valider)

**Échéances rappelées** : GitHub + application dimanche 2026-11-15 23 h 59 ; vidéo, one pager et documentation technique lundi 2026-11-16 14 h ; pitch des finalistes vendredi 2026-11-20.

**Indispensable avant le gel**
1. Seconde revue visuelle après les corrections de lisibilité (la première revue a été faite par vous ; je n'ai pas de navigateur).
2. README (installation, emplacement des données officielles non publiées, variables d'environnement, lancement, tests, reproduction du scénario de démonstration).
3. Confirmation avec les organisateurs que les CSV ne peuvent pas être publiés ; le README indique où placer les fichiers.
4. Fusion de `feature/v1` dans `main` et publication, **sur votre autorisation**.

**Démonstration (vidéo d'environ 5 minutes)** — enregistrer tant que Bedrock fonctionne : Robert + « Tentation Nvidia » → analyse et conflits potentiels → comparaison avec « Prudent et diversifié » → même portefeuille pour Amira (mêmes mesures, statuts différents) → question à l'agent (comparaison) avec la trace des outils → limites et mode sans AWS.

**Livrables du lundi** : documentation technique (à partir de ces documents), one pager, vidéo.

**Améliorations possibles (V2, seulement si le temps le permet)**
- Contrôle automatique des chiffres cités par le modèle contre les résultats d'outils (badge « chiffres vérifiés ») ; contrôle élargi des faits du persona.
- Raffinement discuté de R1 (FNB diversifiés vs titres individuels), à décider avec une justification indépendante du résultat.
- R3, R6, R8, R9 ; `sensitivity_sweep` et `analyze_asset` ; export du rapport ; relecture d'une trace réelle enregistrée.
- Mémoire de suivi reconstruite explicitement (sans réinjecter de résultats d'outils anciens).
