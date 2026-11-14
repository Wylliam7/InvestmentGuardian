# PROJECT_SPEC — Investment Guardian

*Your decisions. Your risks. Explained.*

Statut : **proposition en attente de validation** (aucun code applicatif écrit).
Date de rédaction : 2026-11-14.

Convention de lecture : chaque point est étiqueté
**[OFFICIEL]** (présent dans les documents du Datathon), **[CHOIX]** (notre décision de conception) ou **[À CONFIRMER]**.

---

## 0. Ce que disent réellement les sources officielles

Sources lues : `Datathon - Case Officiel 2026 FR.pdf` (19 pages, la version ENG a été comparée), `Presentation_AlphaForge_AI_Participants.pptx` (12 diapositives, versions FR et EN V2), `alphaforge_starter/README.md`, `sources_metadata.csv`, `data_quality_warnings.txt`.

### 0.1 Objectif officiel [OFFICIEL]
- Concevoir une **solution agentique auto-explicative** qui exploite des données financières publiques pour éclairer une décision d'investissement selon différents profils.
- L'objectif n'est **pas** de trouver le portefeuille au meilleur rendement. La valeur globale prime sur la performance historique simulée et sur le nombre de modèles ou d'agents.
- Libres : cas d'usage, actifs, outils, modèles, architecture, nombre d'agents.
- Pistes mentionnées (non imposées) : un agent d'explicabilité, un agent/mécanisme de gouvernance qui vérifie les contraintes de l'investisseur, signale conflits et informations manquantes, et rend les contrôles visibles.
- Démarche suggérée : formuler une question utile, concevoir le rôle des agents, tenir compte du contexte, **mettre les résultats à l'épreuve (sensibilité aux hypothèses, données, scénarios)**, rendre la solution auto-explicative.

### 0.2 Grille d'évaluation [OFFICIEL] (annexe 01 du PDF et diapositive 10)

| # | Critère | Poids |
|---|---|---|
| 1 | Qualité, pertinence et innovation de la solution (+ prototype) | 20 % |
| 2 | Intelligence agentique et explicabilité (architecture) | 20 % |
| 3 | Analyse et traitement des données (rigueur, validation, visualisation) | 20 % |
| 4 | Expérience utilisateur UX/UI | 10 % |
| 5 | Qualité de l'intégration AWS | 15 % |
| 6 | Présentation, valeur d'affaires et marketing | 15 % |

Le PDF précise que seule une grille simplifiée est publique ; la grille complète est réservée au jury.

### 0.3 Exigence AWS [OFFICIEL]
Diapositive 7 : AWS est une **exigence qualifiante**. AWS doit apporter une contribution réelle et démontrable au fonctionnement ; l'absence d'intégration effective rend le projet **non admissible à l'évaluation finale**. Conseils : choisir les services pertinents, montrer leur rôle dans le flux, rendre l'architecture compréhensible, appliquer sécurité/accès/données/efficience, **ne pas multiplier les services pour impressionner**.
Le PDF ajoute que les outils et services restent libres « sauf indication contraire dans les règles techniques officielles » : **ces règles techniques ne figurent pas dans les documents fournis** [À CONFIRMER].

### 0.4 Livrables [OFFICIEL] — quatre, et non trois
1. **Prototype + code source** : cas d'usage complet et démontrable, explication accessible (sources, hypothèses, facteurs, limites) ; dépôt de code + README (dépendances, sources de données, configuration, reproduction).
2. **Vidéo** d'environ 5 minutes : problème, rôle des agents, données et outils, résultat, explication de bout en bout. Deux situations d'investisseurs contrastées recommandées.
3. **Documentation technique** : méthodes/technologies et justification ; sources, actifs, traitements, hypothèses ; **mécanisme d'explicabilité avec un exemple reliant une conclusion aux données ou aux traces d'exécution** ; validations, limites, améliorations.
4. **One pager** (1 page max) : problématique, approche agentique, originalité, sources, explicabilité, bénéfices.

> Écart avec notre brief : le **one pager** n'était pas dans notre liste de documents. Il est ajouté au plan (phase 8). Les cinq fichiers `.md` de conception ne remplacent pas la « documentation technique » officielle, mais en seront la base.

### 0.5 Échéances [OFFICIEL — communiquées par le participant, consignes logistiques]
| Échéance | Livrable |
|---|---|
| **Dimanche 2026-11-15, 23 h 59** | GitHub (code, README) et application |
| **Lundi 2026-11-16, 14 h** | Vidéo, one pager, documentation technique |
| Vendredi 2026-11-20 | Pitch des finalistes |

Le PDF renvoyait ces dates aux consignes logistiques, absentes du dossier ; elles proviennent désormais du participant. Le compte AWS est temporaire : **une vraie démonstration Bedrock doit être enregistrée tant qu'il fonctionne**. Le plan (IMPLEMENTATION_PLAN.md) est donc construit à rebours de ces échéances, avec un MVP restreint.

### 0.6 Encadrement responsable [OFFICIEL]
Simulation uniquement ; aucune transaction réelle ; pas de conseil financier personnalisé ; distinguer faits, hypothèses, scénarios fictifs ; présenter les incertitudes ; explications **synthétiques, vérifiables, fidèles aux actions observables, sans inventer de justification ni exposer les raisonnements internes détaillés du modèle** ; ne pas prédire les rendements futurs à partir du passé ; volatilité = un indicateur parmi d'autres (horizon, diversification et préférences comptent aussi) ; ne pas assimiler automatiquement un profil à un actif.

### 0.7 Personas [OFFICIEL] (PDF pp. 4–7)

| | Amira | Robert | Mateo (hors MVP) |
|---|---|---|---|
| Âge / métier | 26, ingénieure logicielle | 59, professionnel de la santé | 41, gestionnaire des opérations |
| Risque | Élevé | Faible à modéré | Modéré |
| Horizon | 15 ans ou plus | 3 à 5 ans | 8 à 12 ans |
| Objectif | Faire croître le capital à long terme | **Préserver son capital tout en maintenant un potentiel de croissance** | Croissance équilibrée moyen/long terme |
| Préférences | IA/tech émergentes, forte croissance et volatilité acceptées, **intérêt pour les cryptos**, veut une certaine diversification et **éviter de miser exclusivement sur la tech** | Entreprises établies, modèle d'affaires compris, stabilité/qualité, **peu intéressé par les cryptos**, suit les marchés, **peut être tenté par une entreprise très médiatisée plus risquée** | ESG important, éviter controverses, équilibre croissance/stabilité, peu de spéculation |
| Expérience | Intermédiaire | Avancée | Intermédiaire |
| Ce que le persona teste | Le système accepte-t-il tout parce que « risque élevé » ? | Sait-il **remettre en question** une demande incohérente avec le profil ? | Intègre-t-il des critères non financiers ? |

Précisions par rapport à notre brief : l'objectif de Robert n'est pas la préservation pure (il veut aussi « un potentiel de croissance »), donc un portefeuille 100 % obligataire n'est pas la réponse attendue ; Robert est « peu intéressé par les cryptos » (règle crypto à intégrer) ; Amira veut explicitement éviter l'exclusivité technologique.

---

## 1. Problématique [CHOIX]

Un investisseur prend souvent une décision (« je mets 40 % sur NVIDIA ») sans voir si elle contredit son horizon, sa tolérance aux pertes et son objectif. Les outils habituels affichent des rendements passés flatteurs, sans confronter la décision au profil ni expliquer *pourquoi* elle pose problème.

**Question que l'outil éclaire :** « Cette allocation est-elle cohérente avec *mon* profil, et qu'est-ce qui le montre ? »

## 2. Vision produit [CHOIX]

**Investment Guardian** est un copilote d'aide à la décision en simulation. Il :
1. charge un profil (Robert ou Amira) ;
2. analyse un portefeuille fictif (CAD, historique 2021-11-12 → 2026-11-12) ;
3. calcule rendement, risque, concentration, corrélations par un moteur Python déterministe ;
4. exécute le **Guardian Check** : règles transparentes et configurables qui confrontent l'intention déclarée, la composition et le risque mesuré ;
5. compare deux allocations sans déclarer de « gagnante » sur la seule base du rendement passé ;
6. explique en langage naturel via un agent Bedrock qui **appelle** les fonctions de calcul, jamais ne calcule lui-même ;
7. expose outils appelés, paramètres, données, hypothèses et limites.

### Guardian Check — Decision Integrity Engine
Cohérence évaluée sur trois axes : **Déclaré** (profil + intention saisie, ex. « opportunité NVDA », perte maximale acceptable) ↔ **Construit** (poids, classes, secteurs, concentration) ↔ **Mesuré** (volatilité, drawdown, durée sous l'eau, contribution au risque).
Sortie : une liste de constats, chacun avec **statut (Conforme / Attention / Conflit / Information)**, valeur mesurée, seuil, source du seuil, phrase d'explication déterministe et références aux données. **Pas de note globale opaque** : un score unique serait un seuil arbitraire déguisé ; on affiche le décompte des constats par statut.

Le moteur peut dire « non » : un portefeuille 40 % NVDA est un **Conflit** pour Robert et reste signalé pour Amira (concentration mono-titre), car « risque élevé » n'est pas « tout est acceptable ».

## 3. Utilisateurs ciblés [CHOIX, ancré sur OFFICIEL]
- **Utilisateur de démo** : Robert, puis Amira, avec le même portefeuille.
- **Utilisateur réel visé** : investisseur autonome qui veut un second regard, et conseiller souhaitant un support explicatif.
- **Évolutivité** : les profils sont des données (fichier de config), pas du code. Ajouter Mateo = ajouter un profil + un champ d'exclusions ESG (données ESG absentes du jeu de départ).

## 4. Fonctionnalités

> **Révision 2026-11-14 (validation du participant).** Le périmètre est réduit pour tenir les échéances (§0.5) en développement solo. « **MVP** » = obligatoire avant le gel du dimanche 23 h 59. « **Après MVP** » = seulement si le MVP est stable.

### 4.1 Périmètre MVP

1. Robert et Amira (profils en YAML ; Mateo hors périmètre).
2. **Quatre portefeuilles prédéfinis** (voir DECISIONS H-08) ; édition manuelle des poids avec contrôle Σ = 100 %.
3. Analyse : rendement cumulé et annualisé, volatilité annualisée, max drawdown, concentration (poids max, top-3, HHI, N effectif), répartition par classe d'actifs.
4. Conversion en CAD (`adj_close` × USDCAD), grille commune TSX ∩ US, FX reporté vers l'avant.
5. **Cinq contrôles Guardian** : R1 position unique, R2 actifs volatils (crypto incluse), R4 volatilité du portefeuille, R5 perte historique vs tolérance, R7 diversification. R10 (limites et informations manquantes) est affichée comme information, pas comme contrôle.
6. Tableau de bord Streamlit fonctionnel (3 vues, version sobre).
7. Agent Strands + Bedrock réel.
8. **Quatre outils** : `get_profile`, `evaluate_portfolio`, `check_profile_constraints`, `compare_scenarios`.
9. Comparaison de deux allocations, sans verdict « meilleur ».
10. Traçabilité : outils appelés (arguments, durée), sources, hypothèses, limites.
11. Mode sans AWS minimal : le moteur et le Guardian Check fonctionnent ; le chat se désactive avec un message explicite.

| Id | Fonction (voir la liste initiale) | Statut |
|---|---|---|
| A | Investor Profile | **MVP** |
| B | Portfolio Builder (31 actifs, 4 préréglages) | **MVP** |
| C | Analytics Engine (sous-ensemble du §4.1 point 3 ; corrélations et contribution au risque seulement si le temps le permet) | **MVP** (noyau) |
| D | Guardian Check (5 règles) | **MVP** |
| E | Portfolio Comparison | **MVP** |
| F | AI Guardian Assistant | **MVP** |
| G | Explainability : trace + provenance + étiquetage Calcul / Règle / IA | **MVP** |
| H | Sensibilité (`sensitivity_sweep`, sous-périodes) | Après MVP |
| I | Contrôle numérique des réponses IA | Après MVP |
| J | Relecture d'une trace réelle enregistrée ; rapport par gabarits | Après MVP (le message d'erreur explicite est dans le MVP) |
| K | Fenêtres glissantes par horizon | Après MVP, faible puissance statistique |
| L | `analyze_asset`, règles R3, R6, R8, R9 | Après MVP |

## 5. Fonctionnalités exclues (V1)
- Toute transaction réelle, courtage, données bancaires ou clients réels.
- Vente à découvert, levier, dérivés, marge.
- Prévision de rendements futurs, « prix cibles », signaux d'achat/vente.
- Conseil financier personnalisé (le texte de l'application le dit explicitement).
- Mateo et filtres ESG (aucune donnée ESG fournie ; à ajouter plus tard avec source documentée).
- Données de nouvelles, fondamentales, look-through des FNB (non fournies).
- Optimiseur de portefeuille (Markowitz, etc.) : risque d'apparaître comme « allocation recommandée » et hors du sujet « cohérence de la décision ».
- Multi-agents, bases vectorielles, déploiement cloud de l'application, services AWS supplémentaires sans valeur démontrée.
- Authentification et multi-utilisateurs.
- Coûts de transaction, impôts, comptes enregistrés (REER/CELI) : non modélisés, signalés comme limites.

## 6. Parcours utilisateur (démo de 5 minutes) [CHOIX]

1. **Portfolio Builder** : choisir Robert (profil affiché). Charger le portefeuille « Opportunité médiatisée » : NVDA 40 %, reste réparti (ex. XIU.TO, XBB.TO, ZST.TO, RY.TO, JNJ…). Saisir l'intention : « Je veux saisir l'opportunité NVIDIA ».
2. **Risk Dashboard** : métriques en CAD, drawdown, contribution de NVDA au risque, Guardian Check → plusieurs Conflits expliqués.
3. **Réduction** : ramener NVDA à 10 %, redistribuer vers obligations/actions défensives, puis **Comparaison** avant/après : écarts de volatilité, drawdown, concentration ; le rendement historique plus bas est présenté sans conclure à une infériorité.
4. **Même portefeuille évalué pour Amira** : métriques **identiques**, constats **différents** (mono-titre reste signalé, volatilité acceptable, crypto/tech jugées selon ses seuils).
5. **AI Guardian & Explainability** : question « Que se passe-t-il si je porte Nvidia à 40 % ? » → trace visible des outils, provenance, distinction Calcul/Règle/IA, limites.

## 7. Règles initiales du Guardian Check [CHOIX — seuils à valider]

Les seuils sont des **heuristiques pédagogiques** de ce prototype, configurables (YAML), versionnées et affichées à l'écran. Ce ne sont ni des normes réglementaires ni des recommandations universelles.

| Id | Règle | Mesure | Robert (attention / conflit) | Amira (attention / conflit) |
|---|---|---|---|---|
| R1 | Position unique | poids max | > 10 % / > 20 % | > 20 % / > 35 % |
| R2 | Actifs volatils | poids des actifs de volatilité historique > 35 % ou crypto | > 10 % / > 20 % | > 35 % / > 50 % |
| R3 | Cryptoactifs | poids crypto | > 2 % / > 5 % | > 15 % / > 25 % |
| R4 | Volatilité du portefeuille | vol. annualisée | > 10 % / > 14 % | > 25 % / > 35 % |
| R5 | Perte historique vs tolérance déclarée | max drawdown | > 15 % / > 25 % | > 40 % / > 55 % |
| R6 | Horizon vs risque | durée sous l'eau du drawdown max vs horizon | > 25 % de l'horizon / > 50 % | > 25 % / > 50 % |
| R7 | Diversification | N effectif (1/HHI) | < 6 / < 4 | < 5 / < 3 |
| R8 | Concentration sectorielle (IT + Services de communication, étiquettes du jeu de données) | poids | > 30 % / > 50 % | > 50 % / > 70 % |
| R9 | Part défensive (FNB obligataires) | poids | < 30 % / < 15 % | non évaluée |
| R10 | Qualité des données et limites | fenêtre, couverture, look-through absent | Information | Information |

**Règles du MVP : R1, R2, R4, R5, R7.** Les autres (R3, R6, R8, R9) sont décrites ici pour la suite ; R10 est informative.

**Politique sur les seuils (validée le 2026-11-14).**
- Les seuils sont fixés **avant** d'observer les résultats sur les portefeuilles de démo, puis gelés dans `config/guardian_rules.yaml` (versionné).
- Aucun seuil n'est ajusté pour obtenir une conclusion prédéterminée. Si un résultat surprend, on le garde et on le documente ; une modification ultérieure exige une raison écrite dans DECISIONS.md, indépendante du résultat souhaité.
- Chaque règle porte : justification, statut « heuristique » (sauf si elle provient d'une norme, ce qui n'est le cas d'aucune ici) et version.
- Chaque constat affiche : valeur, seuil, profil et formule.

**Informations manquantes signalées** (jamais devinées) : poids de ce portefeuille dans le patrimoine total, besoins de liquidité, comptes enregistrés et fiscalité, revenu à la retraite, positions existantes, préférences ESG (pour Mateo), date réelle de décaissement.

## 8. Critères d'acceptation

**Fonctionnels**
- AC-01 Sélection de Robert/Amira charge profil, horizon, tolérance et seuils depuis la config.
- AC-02 Le builder refuse tout portefeuille dont la somme ≠ 100 % (tolérance 0,01 %), poids négatifs, actif inconnu, doublons.
- AC-03 Mêmes entrées → mêmes sorties (déterminisme) ; résultats indépendants d'AWS.
- AC-04 Le moteur fonctionne sans AWS ; le chat se désactive avec un message d'erreur explicite.
- AC-05 Pour un même portefeuille et une même fenêtre, les métriques sont identiques entre Robert et Amira ; seuls les constats changent.
- AC-06 La comparaison utilise la même période pour les deux allocations et n'emploie aucun libellé « meilleur » fondé sur le seul rendement.
- AC-07 Chaque réponse de l'agent est accompagnée de la liste des outils réellement appelés, avec arguments et durée.
- AC-08 Les chiffres financiers affichés proviennent des objets structurés des outils. MVP : vérification manuelle sur les questions de test ; après MVP : contrôle numérique automatique (badge). *Constat de la phase 0 : face à une erreur d'outil, le modèle a calculé lui-même et répondu quand même ; l'instruction « n'additionne jamais toi-même » ne suffit pas. Le prompt devra exiger de signaler l'échec, et les chiffres seront affichés depuis les résultats d'outils.*
- AC-09 Aucun secret dans le dépôt ; `git grep` sur motifs de clés AWS = 0 résultat.

**Qualité financière**
- AC-10 Tests à résultat connu sur rendement, volatilité, drawdown, HHI, conversion CAD, rééquilibrage, alignement des calendriers.
- AC-11 Fiche de provenance présente sur chaque analyse : fichiers, dates, transformations, hypothèses, limites.
- AC-12 Aucun calcul n'utilise d'information postérieure à la date d'évaluation.

**Démo**
- AC-13 Le scénario de §6 se déroule sans intervention manuelle hors interface et se reproduit à l'identique.
- AC-14 Une session réelle avec Bedrock est enregistrée (vidéo + trace JSON) avant l'expiration du compte AWS.

## 9. Correspondance avec les critères du jury

| Critère (poids) | Ce que nous montrons | Preuves visibles |
|---|---|---|
| Solution (20 %) | Problème net (cohérence décision/profil), remise en question d'une demande (Robert), nuance (Amira), un mécanisme original (Guardian Check) | Scénario Robert→Amira, comparaison, sensibilité NVDA |
| Agentique & explicabilité (20 %) | Un agent au rôle clair (orchestrer outils et expliquer), un mécanisme de gouvernance déterministe, trace observable, contrôle numérique, étiquetage Calcul/Règle/IA | Panneau de trace, étiquetage Calcul/Règle/IA, exemple conclusion → donnée dans la doc (badge de vérification des chiffres si le temps le permet) |
| Données (20 %) | Audit documenté, conversion CAD, politique de calendrier, adj_close, aucune fuite temporelle, tests à valeur connue, limites (biais du survivant) | DATA_AUDIT, tests, fiche de provenance, graphiques |
| UX/UI (10 %) | 3 vues, hiérarchie claire, statuts colorés, langage simple | Démo |
| AWS (15 %) | Bedrock (Nova 2 Lite) via Strands comme moteur de dialogue et de sélection d'outils ; sécurité par chaîne d'identifiants standard, aucun secret ; gestion d'erreurs visible | Trace d'appels, section AWS de la doc, journal d'une session réelle |
| Pitch (15 %) | Récit « 5 minutes », positionnement clair, limites assumées | Vidéo, one pager |

**Point de vigilance AWS** : l'intégration est qualifiante. Il faut que la valeur de Bedrock soit *visible* : l'agent choisit les outils, adapte l'explication au persona, répond en langage naturel à des scénarios non prévus. Une réponse « réussie » sans appel Bedrock ne doit jamais être présentée comme telle.

## 10. Avertissements affichés dans l'application
- « Simulation à des fins éducatives. Aucune transaction. Pas un conseil financier personnalisé. »
- « Résultats historiques (2021-11-12 → 2026-11-12) : ils décrivent le passé et ne prédisent pas l'avenir. »
- « Biais du survivant : l'univers a été choisi en 2026 parmi des titres aujourd'hui importants. »
- « Seuils du Guardian Check : heuristiques de démonstration, modifiables. »
