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

## 0 bis. Mise à jour V1 (2026-11-14, branche locale `feature/v1`, départ du commit V0 `ba8dfcf`)

**Profils et règles**
- **Amira** ajoutée depuis le cas officiel (p. 5) : 26 ans, risque élevé, horizon 15 ans ou plus (`horizon_years_max: null`), objectif de croissance, intérêt pour la technologie, l'IA et les cryptos, volonté d'éviter une concentration exclusivement technologique.
- **Seuils** : ceux de PROJECT_SPEC §7, repris tels quels. **Aucun seuil de Robert n'a changé** ; un test de gel vérifie l'ensemble (R1, R2, R4, R5, R7 × Robert, Amira). Version de configuration : `0.2-v1`.
- **R7** = nombre effectif de positions `1/HHI`, définition de PROJECT_SPEC §7 : Robert attention < 6, conflit < 4 ; Amira attention < 5, conflit < 3. Règle de sens inverse (« min ») : un seuil est franchi quand la mesure lui est strictement inférieure. La mesure est arrondie à 9 décimales avant comparaison, pour qu'une erreur de virgule flottante ne change pas un statut à la frontière.
- **R10** (statut Information, sans seuil) : fenêtre, FNB non décomposés et, pour un profil dont la contrainte qualitative le mentionne (Amira), la part des positions étiquetées « Information Technology » ou « Communication Services », plus le poids de QQQ signalé à part. **R8 n'est pas implémentée** : aucun seuil n'est appliqué à la part technologique en V1.
- **Statuts affichés** : Conforme, Attention, Conflit, Information. Un conflit est présenté comme un *conflit potentiel selon des seuils heuristiques du prototype*, jamais comme une incompatibilité objective.

**Quatre portefeuilles (H-08 résolue)** — compositions fixées avant de consulter les diagnostics, gelées par un test :
1. *Robert — Prudent et diversifié* : XBB.TO 15, ZST.TO 10, AGG 10, XIU.TO 15, SPY 10, RY.TO 5, JNJ 5, PG 5, FTS.TO 5, CNR.TO 5, ENB.TO 5, GLD 10. La liste indicative de H-08 (XBB.TO, ZST.TO, XIU.TO, RY.TO, JNJ, GLD) a été étendue (AGG, SPY, PG, FTS.TO, CNR.TO, ENB.TO) pour obtenir 12 positions réparties entre obligations (35 %), actions d'entreprises établies, FNB larges et or, sans crypto, conformément au persona (stabilité, entreprises établies, peu d'intérêt pour les cryptos).
2. *Robert — Tentation Nvidia* : NVDA 40, XBB.TO 35, XIU.TO 25 (inchangé depuis V0).
3. *Amira — Croissance diversifiée* : QQQ 20, SPY 20, XIU.TO 15, NVDA 10, SHOP.TO 5, BTC-USD 5, XBB.TO 10, RY.TO 5, JNJ 5, XOM 5.
4. *Amira — Concentration technologie et crypto* : NVDA 25, TSLA 15, QQQ 25, SHOP.TO 5, BTC-USD 20, ETH-USD 10.
Tous les actifs existent dans `assets_universe.csv` ; chaque total vaut exactement 100 (entiers). Ce sont des simulations éducatives.

**Diagnostics observés après figement** (mêmes mesures pour les deux profils ; statuts R1 / R2 / R4 / R5 / R7) :

| Portefeuille | Robert | Amira |
|---|---|---|
| Robert prudent | Attention / OK / OK / OK / OK | OK / OK / OK / OK / OK |
| Robert Nvidia 40 % | Conflit ×5 | Conflit / Attention / OK / OK / Conflit |
| Amira croissance | Attention / Attention / Conflit / Conflit / OK | OK ×5 |
| Amira tech et crypto | Conflit ×4 / Attention | Attention / Conflit / Conflit / Conflit / OK |

Aucun seuil n'a été modifié après ces résultats. **Limite constatée** : R1 traite un FNB diversifié comme une action individuelle (XBB.TO à 15 % donne « Attention » pour Robert dans son portefeuille prudent). C'est une limite connue de R1 (affichée dans ses limites), pas un motif de changer le seuil ; un raffinement éventuel (R1 sur titres individuels seulement) serait une décision de V2, à justifier indépendamment du résultat souhaité.

**Constructeur de portefeuille** : poids saisis jamais modifiés silencieusement ; poids négatif, nul, non numérique, actif inconnu, doublon, somme ≠ 100 % (tolérance 0,01 point) → erreur explicite, aucun calcul tant que ce n'est pas corrigé. La normalisation proportionnelle existe, mais seulement par un bouton explicite ; les poids réellement analysés sont toujours affichés.

**Comparaison A/B** : même fenêtre, même grille (1 228 dates communes), même devise (CAD), même rééquilibrage mensuel ; la comparaison échoue si les grilles diffèrent. Les compromis sont rédigés sans « meilleur / pire / gagnant / recommandé » (test automatique). Exemple (A = Nvidia 40 %, B = prudent, profil Robert) : rendement cumulé 180,9 % contre 62,9 % ; annualisé 22,9 % contre 10,3 % ; volatilité 22,3 % contre 6,9 % ; drawdown maximal −36,1 % contre −8,4 % ; nombre effectif de positions 2,9 contre 10,0.

**Agent**
- Quatre outils : `get_profile`, `evaluate_portfolio`, `check_profile_constraints`, `compare_scenarios`. Les deux premiers outils de V0 acceptent maintenant `portfolio` ("A" ou "B") ; `check_profile_constraints` accepte un `profile_id` (profil actif par défaut) et retourne aussi les métriques.
- **Contexte reconstruit à chaque requête** : une note courte (profil actif, A défini, B défini ou non) précède la question. Elle ne contient ni poids ni résultat ; le modèle doit les obtenir par les outils. Sans cette note, le test live montrait que le modèle ne savait pas qu'un B existait et n'appelait pas `compare_scenarios`.
- **Faits du persona** : le test live a révélé une hallucination (horizon « 5-10 ans » et objectif inventé pour Robert, sans appel de `get_profile`). Mesures : le profil officiel est retourné par `check_profile_constraints` et `compare_scenarios` ; le prompt impose de ne citer que ce champ ; une **vérification déterministe** retient toute réponse qui cite un horizon (« a à b ans », « n ans ou plus ») ne correspondant à aucun profil officiel. Limite : seuls les horizons sont contrôlés ; les autres affirmations sur le persona ou les chiffres cités dans le texte ne sont pas vérifiés automatiquement (V2).
- Protections de V0 inchangées : requête indépendante, verrou, trace par requête, réponses rejetées non affichées.

**Langage** : prompt restructuré en quatre parties (faits historiques calculés / seuils heuristiques et constats / objectifs déclarés / interprétation), formulations prudentes imposées, « seuils recommandés » et « normes » interdits, aucune prévision, aucun verdict « meilleur ».

### Corrections finales V1 après revue visuelle (2026-11-14)

1. **Conflit entre le profil sélectionné et la question.** Détection déterministe (nom d'affichage ou identifiant, insensible à la casse et aux accents, mots entiers) *avant* tout appel au modèle. Règle : si la question nomme au moins un profil et ne nomme pas le profil actif de l'interface, l'application répond par une demande de précision (« sélectionnez X ou reformulez ») avec un bouton de sélection du profil ; aucun appel à Bedrock ni aux outils. Si le profil actif est nommé (seul ou avec un autre), la requête est analysée ; sans profil nommé, c'est le profil actif qui s'applique. Garde-fou côté outils : pour chaque requête, seuls le profil actif et les profils nommés par l'utilisateur sont autorisés ; un outil appelé avec un autre `profile_id` échoue et la réponse est retenue, donc le modèle ne peut pas choisir seul un autre profil. Conséquence assumée : « Cette allocation serait-elle évaluée différemment pour Amira ? » avec Robert sélectionné demande maintenant de sélectionner Amira ; le tableau « Même portefeuille, autre profil » du tableau de bord reste disponible, et une question qui nomme les deux profils est acceptée.
2. **Scénarios par profil.** `config/presets.yaml` contient `profile_defaults` (Robert : A = Tentation Nvidia, B = Prudent ; Amira : A = Concentration technologie et crypto, B = Croissance diversifiée). Au changement de profil : si l'utilisateur n'a encore rien choisi ni modifié, les scénarios du profil sont chargés, avec un bouton « Revenir à mon allocation précédente » ; sinon ils sont seulement proposés et ne se chargent que sur clic, dans les emplacements qui sont des préréglages intacts. **Un portefeuille personnalisé ou en cours d'édition n'est jamais remplacé.** Le menu des préréglages place en premier, avec ★, les scénarios du profil sélectionné, et toute allocation reste évaluable pour tout profil. Correction d'un défaut : changer de préréglage réutilisait le numéro de version de l'éditeur, donc d'anciennes modifications pouvaient réapparaître ; la version est désormais incrémentée à chaque remplacement. Aucune allocation prédéfinie ni aucun seuil n'a été modifié.
3. **Lisibilité.** Thème `.streamlit/config.toml` (police de base 17 px, titres plus grands, valeurs de métriques agrandies), titre à 3,4 rem, mise en page pleine largeur, espacement et taille des onglets améliorés. Non vérifié visuellement par moi (aucun navigateur sur la machine).
4. **Preuve de `compare_scenarios`.** Chaque requête affiche la liste des outils réellement exécutés (nom, numéro d'appel, durée, arguments, erreur éventuelle) à partir du journal de notre code, une ligne explicite « compare_scenarios : appelé avec succès (appel n° N) » **ou** « non appelé pendant cette requête » **ou** « appelé mais en échec », et la façon d'ouvrir la trace détaillée ; la ligne de trace de `compare_scenarios` de la dernière requête est dépliée.

## 0 ter. Mise à jour V2 — refonte UX, accessibilité et explications agentiques (2026-11-14, branche locale `feature/v2-ux`, départ du commit V1 `e5044f8`)

**Périmètre et garde-fous.** Aucune modification du moteur financier, des règles, des seuils, des profils, des données ni des allocations prédéfinies : un test compare les métriques, seuils et statuts des 4 portefeuilles pour les 2 profils à une référence figée sur V1 (`tests/golden/v1_baseline.json`) et vérifie par `git diff` que `src/guardian/{finance,rules,data}` et la configuration des règles sont identiques à `e5044f8`. Aucun service AWS ni second agent n'a été ajouté.

**Parcours et vocabulaire.** Quatre onglets : *Mon portefeuille*, *Comprendre mes risques*, *Comparer deux choix*, *Assistant IA*. Sous-titre « Comprenez les risques de vos décisions d'investissement » ; la signature anglaise est conservée en légende. Les noms techniques restent dans les info-bulles et les sections avancées.

**Barre latérale.** Par défaut : nom, profil actif, disponibilité du moteur et de l'assistant (détection locale des identifiants, mise en cache 5 minutes, aucun appel Bedrock), mention de simulation. Le reste (région, identifiant exact du modèle, type d'authentification, test de connexion, simulation de panne, compteurs de session) est dans « Paramètres avancés et diagnostic technique », fermé par défaut ; aucune valeur d'identifiant n'est affichée.

**Guardian Check présenté en français simple.** Chaque carte répond à : quel problème ? quel chiffre ? pourquoi pour ce profil ? quel niveau de vigilance ? comment est-ce calculé ? Niveaux affichés : « Risque important à examiner » (statut interne CONFLIT), « Point de vigilance » (ATTENTION), « Aucun dépassement détecté selon ce critère » (OK), « Information complémentaire » (INFO) ; les statuts internes, les identifiants de règles, les seuils, les formules et la version de configuration restent dans « Détails techniques ». Les textes sont produits par du code déterministe (`src/guardian/explain/cards.py`) à partir des mesures du moteur ; le modèle n'intervient jamais dans la valeur, le repère ou le statut. Les limites scientifiques sont conservées et reformulées (par exemple : un fonds peut être plus diversifié qu'une action individuelle, même si R1 applique le même repère).

**Résumé prioritaire (sans IA).** Les règles corrélées sont regroupées en trois thèmes : concentration (R1, R7), actifs très fluctuants (R2), fluctuations et baisses historiques (R4, R5). Seuls les thèmes dont une règle franchit un repère apparaissent ; le texte annonce exactement leur nombre (un, deux ou trois) et ajoute une note de recoupement lorsque la plus grande position est aussi un actif très fluctuant. Cinq règles dépassées sur Nvidia à 40 % donnent donc trois éléments, jamais « cinq risques ».

**Diversification.** L'interface distingue le nombre réel d'actifs et le nombre équivalent de positions de poids égal (1/HHI), sans changer le calcul, et rappelle que cette mesure ne tient pas entièrement compte des corrélations ni du contenu des fonds.

**Bouton « Explique-moi mes risques avec l'IA ».** Même agent Strands et même mécanisme que l'assistant (`GuardianAgent.ask`), avec une consigne interne (`task`) et des outils obligatoires (`evaluate_portfolio`, `check_profile_constraints`) : si l'un manque, la réponse est retenue. Profil actif et portefeuille A effectivement analysé, requête indépendante avec son propre numéro, trace propre. L'explication n'est affichée que si elle correspond au profil et au portefeuille actuels. Les « faits historiques utilisés » sont repris des résultats d'outils, pas du texte du modèle. Limite constatée en test live : le modèle présente parfois trois critères liés comme trois risques distincts malgré la consigne ; le résumé déterministe de l'application ne le fait pas.

**Explicabilité à deux niveaux.** Niveau 1 : phrases simples sur ce que l'assistant a réellement fait, produites uniquement à partir des appels journalisés (aucune phrase pour un outil non exécuté), avec période, devise, provenance et deux mentions fixes : les outils financiers ont été exécutés par le code Python ; le texte de l'IA est une interprétation non vérifiée phrase par phrase (jamais « entièrement vérifié »). Niveau 2 : section fermée « Voir les détails techniques de l'analyse » qui conserve tout (noms exacts, arguments JSON, statut, durée, empreintes, références de données, résultat complet).

**Comparaison.** Compromis en phrases avec les valeurs exactes avant les tableaux ; aucun portefeuille n'est désigné comme meilleur.

**Confirmation d'analyse.** Le bouton « Analyser ce portefeuille » recalcule réellement (sans appel Bedrock) avant de confirmer ; le message de réussite nomme le portefeuille et renvoie à l'onglet des résultats ; il disparaît si les pondérations changent et n'apparaît jamais si la validation ou le calcul échoue.

**Lisibilité.** Dates en français dans les cartes ; rappel court du profil dans chaque carte et profil complet affiché une fois au-dessus des cartes.

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
