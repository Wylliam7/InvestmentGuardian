# Investment Guardian

Investment Guardian est une application Streamlit éducative pour explorer les
compromis entre rendement historique, volatilité, drawdown, concentration et
adéquation à un profil d'investisseur. Elle a été développée pour le Datathon
AlphaForge AI 2026.

> **Simulation éducative uniquement.** L'application ne fournit pas de conseil
> financier personnalisé et n'exécute aucune transaction.

## Démo

**Application publique :** [investment-guardian.streamlit.app](https://investment-guardian.streamlit.app/)

**Code source :** [github.com/Wylliam7/InvestmentGuardian](https://github.com/Wylliam7/InvestmentGuardian)

## Problème et solution

Les indicateurs de rendement seuls peuvent donner une vision incomplète d'un
portefeuille. Un investissement historiquement performant peut aussi avoir
connu une forte baisse, être concentré ou être incohérent avec l'horizon et la
tolérance au risque d'un investisseur.

Investment Guardian propose un parcours guidé :

1. choisir un profil et un ou deux portefeuilles fictifs ;
2. modifier les pondérations et analyser une allocation personnalisée ;
3. comprendre les métriques et les alertes du Guardian Check ;
4. comparer deux allocations sur la même période historique ;
5. examiner séparément les préférences ESG ;
6. poser une question à l'assistant IA et consulter les faits et les outils
   réellement utilisés.

## Fonctionnalités

### Profils et portefeuilles

Les profils fictifs du cas officiel sont :

- **Robert** : risque faible à modéré, horizon de 3 à 5 ans ;
- **Mateo** : risque modéré, horizon de 8 à 12 ans et préférences ESG déclarées ;
- **Amira** : risque élevé, horizon de 15 ans ou plus.

Pour chaque profil, l'utilisateur peut charger des scénarios prédéfinis,
modifier les actifs et les pondérations, ou construire un portefeuille
personnalisé. Les validations de saisie vérifient notamment les actifs connus,
les doublons, les poids non négatifs et le total de 100 %.

### Analyse financière

L'application présente notamment :

- rendement cumulé et annualisé ;
- volatilité annualisée ;
- plus forte baisse historique (drawdown) ;
- concentration et nombre effectif de positions ;
- allocation et évolution historique ;
- comparaison des portefeuilles A et B sur une grille de dates commune ;
- graphiques interactifs Plotly.

### Guardian Check

Le Guardian Check confronte les résultats calculés au profil sélectionné et
affiche les statuts **Conforme**, **Attention**, **Conflit** ou **Information**.
Ses seuils sont des heuristiques pédagogiques configurées dans
`config/guardian_rules.yaml`, et non des normes financières.

### ESG

L'analyse ESG est distincte du risque financier. Elle utilise les préférences
ESG déclarées par Mateo et des informations documentées dans
`config/esg_sources.yaml`.

Elle présente la couverture, les informations documentées, les références et
les cas d'information insuffisante. Aucun score ESG global n'est calculé et
les résultats ESG ne sont jamais additionnés au Guardian Check.

### Assistant IA

L'assistant IA V5 est disponible dans l'onglet **Assistant IA** et pour
l'explication des risques. Il peut répondre aux questions sur le portefeuille,
le profil, la comparaison A/B et les préférences ESG lorsque les outils
nécessaires sont disponibles.

L'accès à Bedrock dépend d'une authentification AWS valide. Si Bedrock est
indisponible, les calculs financiers, graphiques, portefeuilles, Guardian Check
et analyse ESG restent disponibles.

## Architecture agentique

La pile principale est :

- **Streamlit** pour l'interface ;
- **Python** pour le chargement des données, les calculs financiers, le
  Guardian Check et l'ESG déterministe ;
- **Strands Agents** pour l'orchestration de l'agent ;
- **Claude Haiku 4.5** via **Amazon Bedrock** pour le modèle V5 ;
- **Plotly** pour les graphiques.

Le modèle choisit les outils à appeler à partir de la question. Les outils
Strands exécutent ensuite les calculs Python correspondants. Python ne
préexécute pas une réponse pour l'agent et ne remplace pas ses appels d'outils
par une réponse calculée en silence.

Les outils disponibles pour V5 couvrent :

- le profil ;
- l'évaluation d'un portefeuille ;
- les contraintes du Guardian Check ;
- la comparaison A/B ;
- les préférences ESG.

Le modèle utilisé par l'application est :

```text
global.anthropic.claude-haiku-4-5-20251001-v1:0
```

## Explicabilité et provenance

L'application sépare clairement :

- le texte libre généré par le modèle ;
- les faits vérifiés repris des résultats d'outils ;
- les statuts du Guardian Check ;
- les références ESG structurées ;
- les erreurs et appels d'outils ;
- la trace Strands complète.

Chaque appel V5 conserve notamment le nom de l'outil, ses arguments, son
`toolUseId`, son statut, sa durée et son résultat. La trace de la session peut
être exportée en JSON depuis l'interface.

Cette provenance permet de vérifier quels calculs ont réellement été exécutés.
Elle ne signifie pas que toute phrase générée par le modèle est automatiquement
vraie : les résultats structurés et les limites affichées doivent être
privilégiés.

## Données, période et hypothèses

Les trois fichiers officiels du starter kit sont inclus dans le dépôt :

- `Datathon2026/alphaforge_starter/assets_universe.csv` ;
- `Datathon2026/alphaforge_starter/prices_daily.csv` ;
- `Datathon2026/alphaforge_starter/fx_usdcad_daily.csv`.

La période historique utilisée par l'application va du **2021-11-12 au
2026-11-12**. Elle contient 31 actifs, dont des actions, FNB, obligations,
matières premières et cryptoactifs.

Sources et conventions principales :

- prix ajustés issus du jeu de données du Datathon, basé sur Yahoo Finance ;
- taux USD/CAD issus de la Banque du Canada ;
- conversion des actifs USD en CAD avec le taux disponible à la date ;
- report vers l'avant du dernier taux de change connu lorsqu'un taux manque ;
- grille commune TSX/États-Unis pour les calculs comparables ;
- rééquilibrage mensuel vers les poids cibles au dernier jour de grille du mois ;
- utilisation de `adj_close`, qui suppose le réinvestissement des distributions.

Les calculs n'intègrent pas les impôts, frais, commissions, spreads, liquidité
ou contraintes d'exécution. Les FNB ne sont pas décomposés en titres
sous-jacents.

## Limites importantes

- Les résultats sont historiques et ne garantissent aucun rendement futur.
- Il n'y a aucune transaction réelle et aucune recommandation d'achat ou de
  vente.
- La fenêtre d'environ cinq ans ne représente pas tous les régimes de marché.
- Les données peuvent comporter un biais de survivant et ne sont pas une
  validation ligne par ligne par les bourses.
- L'effet de change CAD/USD peut augmenter ou réduire les résultats.
- La couverture ESG est partielle, datée et limitée aux sources enregistrées ;
  une information absente ne prouve pas l'absence de controverse.
- Le Guardian Check utilise des seuils heuristiques pédagogiques.
- L'assistant IA peut être indisponible lorsque les identifiants AWS sont
  absents, expirés, refusés ou soumis à une limite de service.
- Les réponses du modèle ne sont pas garanties exactes à 100 %.

## Installation locale

### Prérequis

- Python **3.11 ou plus récent** ;
- Git ;
- des identifiants AWS disposant de l'accès Bedrock si l'assistant IA doit
  être utilisé.

### Installation

```powershell
git clone https://github.com/Wylliam7/InvestmentGuardian.git
cd InvestmentGuardian
```

Puis, depuis la racine du dépôt :

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Les CSV officiels doivent rester à leur emplacement par défaut :

```text
Datathon2026/alphaforge_starter/
```

Un autre dossier peut être utilisé avec `GUARDIAN_DATA_DIR`, à condition de
contenir les trois fichiers avec leurs noms exacts.

## Configuration AWS et Bedrock

Ne commitez jamais de clé ou de jeton AWS. Boto3 utilise sa chaîne standard
de credentials : rôle IAM, profil AWS local ou variables d'environnement.

Variables utiles :

```powershell
$env:AWS_REGION = "us-east-1"
$env:GUARDIAN_MAX_TOKENS = "1500"
```

L'application Streamlit sélectionne explicitement le modèle Claude Haiku 4.5
indiqué plus haut. `BEDROCK_MODEL_ID` peut être utilisé lors d'une
initialisation directe de `AgentV5`, mais ne doit pas servir à remplacer le
modèle de la démo sans validation.

Pour Streamlit Community Cloud, renseignez les paramètres nécessaires dans la
section **Secrets** de l'application, jamais dans GitHub. Les identifiants
temporaires AWS Workshop Studio devront être remplacés lorsqu'ils expirent.

## Lancement de l'application

Depuis la racine du dépôt :

```powershell
.venv\Scripts\Activate.ps1
streamlit run app/app.py
```

L'application sera généralement disponible à l'adresse :

```text
http://localhost:8501
```

## Tests hors AWS

La suite hors AWS peut être exécutée avec :

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Les tests marqués `live` nécessitent un accès réel à Bedrock et sont
volontairement séparés de la validation hors AWS.

## Licence et contexte du Datathon

Investment Guardian est un prototype éducatif réalisé pour le Datathon
AlphaForge AI 2026. Les données du starter kit sont utilisées selon
l'autorisation de l'organisation du Datathon pour l'hébergement de cette
application.

Les informations ESG sont des extraits documentés et attribués. Elles ne
constituent ni une notation ESG universelle ni une certification.
