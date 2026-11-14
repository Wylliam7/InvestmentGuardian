# DATA_AUDIT — Jeu de départ AlphaForge AI

Audit réalisé le 2026-11-14 en **lecture seule** sur `Datathon2026/alphaforge_starter/`. Aucun fichier source n'a été modifié. Les contrôles ont été exécutés avec pandas dans un environnement temporaire hors projet. Les chiffres ci-dessous sont mesurés, sauf mention « README » (affirmation de l'éditeur que nous n'avons pas pu vérifier autrement).

## 1. Inventaire

| Fichier | Lignes de données | Colonnes | SHA-256 (version auditée) |
|---|---|---|---|
| `assets_universe.csv` | 31 | `asset_id, ticker, name, asset_class, market, currency, sector` | `f78de8ec…0755467d` |
| `prices_daily.csv` | 40 049 | `date, ticker, open, high, low, close, adj_close, volume, currency` | `ff2a3f2d…0e8a569d` |
| `corporate_actions.csv` | 658 | `ex_date, ticker, action, value, unit` | `37d99f14…0d8312b1` |
| `fx_usdcad_daily.csv` | 1 245 | `date, usdcad, cadusd` | `f04e218a…cb8972b3` |
| `macro_rates.csv` | 8 281 | `date, series_id, value, unit, frequency, label, source` | `2c04b0ca…0375c73e` |
| `sources_metadata.csv` | 6 | `file, content, source, source_url, retrieved_on, coverage, frequency, processing, limitations, terms_of_use` | `7ff17052…fe531bdf` |
| `data_quality_warnings.txt` | — | « No warnings. » (généré le 2026-11-13) | — |
| `build_dataset.py` | 209 lignes | Régénère les 5 CSV de données (`yfinance`, API Valet, FRED) ; utilise `auto_adjust=False` | — |

Les empreintes complètes sont à recalculer par `sha256sum` ; elles serviront à prouver quelle version des données a produit une analyse (champ `data_version` de la fiche de provenance).

**Types** : `date` lue comme texte ISO (à convertir en `datetime64`) ; prix en `float64` ; `volume` entier ; autres champs texte.

## 2. Univers (`assets_universe.csv`)

31 actifs, 31 présents dans les prix, aucun écart de ticker, devise du fichier de prix = devise de l'univers (0 incohérence).

| Classe | n | Actifs |
|---|---|---|
| `equity` CAD (TSX) | 10 | RY, TD, MFC, ENB, CNQ, CNR, FTS, ATD, SHOP, CSU (`.TO`) |
| `equity` USD | 10 | AAPL, MSFT, NVDA, GOOGL, AMZN, TSLA, JPM, JNJ, PG, XOM |
| `etf_equity` | 5 | XIU.TO (CAD) ; SPY, QQQ, ESGV (USD) ; QQQ est étiqueté « growth/tech-heavy » |
| `etf_bond` | 4 | XBB.TO, ZST.TO (CAD) ; AGG, TLT (USD) |
| `etf_commodity` | 1 | GLD (USD) |
| `crypto` | 2 | BTC-USD, ETH-USD (USD) |

Au total : 14 actifs cotés en CAD (10 actions + XIU + XBB + ZST), 17 en USD (dont 2 cryptos). **Nuance :** l'exposition économique d'un actif coté en CAD peut être étrangère (ex. SHOP, CSU) ; la devise de cotation n'est pas la devise d'exposition.

Secteurs : étiquettes simplifiées attribuées par les organisateurs (GICS approximatif). Les ETF portent un « secteur » qui décrit l'exposition. **Pas de look-through** : un FNB QQQ n'est pas décomposé en ses titres ; l'exposition technologique réelle d'un portefeuille contenant QQQ est donc sous-estimée si l'on utilise uniquement le champ `sector`.

## 3. Prix (`prices_daily.csv`)

- **Période** : 2021-11-12 → 2026-11-12 pour les 31 actifs (même première et dernière date).
- **Lignes par actif** : 1 255 pour chaque action et FNB (TSX et marchés américains) ; 1 827 pour BTC-USD et ETH-USD.
- **Valeurs manquantes** : 0 dans toutes les colonnes. **Doublons** (`date, ticker`) : 0.
- **Cohérence OHLC** : 0 cas `high < low`, 0 `close > high`, 0 prix ≤ 0.
- **Mouvements journaliers extrêmes** (rendement sur `adj_close`) : aucun > 25 % en valeur absolue (cohérent avec `data_quality_warnings.txt`). Extrêmes : NVDA +24,4 %, SHOP +23,2 %, ETH +21,8 %, SHOP −19,6 %, ETH −17,5 %, NVDA −17,0 %. Ils ressemblent à de vrais épisodes de marché ; rien ne justifie de les supprimer ou de les écrêter.
- **Écarts de calendrier** : aucun trou > 5 jours dans les séries d'un actif.
- **ZST.TO** : une ligne à volume nul le 2022-07-06 (OHLC identiques 48,81). Confirmé. Elle est conservée (le prix est plausible) et signalée. Le prix de `close` de ZST est très stable (305 jours sans variation), le rendement vient des distributions : **utiliser `adj_close`, jamais `close`**.
- **`adj_close` / `close`** : de 0,74 (ENB) à 1,00. Pour BTC, ETH, SHOP, TSLA, AMZN : rapport max = 1 (peu ou pas de dividendes). Les prix `close` sont ajustés pour les fractionnements seulement.
- **Cryptos** : jours civils UTC, 7 jours sur 7 (1 827 lignes ; 1 826 jours + 1 inclusif sur 5 ans), `adj_close = close`.

## 4. Devises et FX (`fx_usdcad_daily.csv`)

- 1 245 jours ouvrables canadiens, 2021-11-12 → 2026-11-12, sans valeur manquante ni doublon. `usdcad` va de 1,2451 à 1,4603. Variation journalière max 1,77 %.
- `usdcad × cadusd ≈ 1` (écart max 7 × 10⁻⁷ : arrondi à 6 décimales du fichier).
- Source : Banque du Canada, série `FXUSDCAD`, taux unique quotidien publié vers 16 h 30 ET (README et métadonnées). Les clôtures américaines sont à 16 h 00 ET : décalage de ~30 min, négligeable pour un usage quotidien, mais à documenter.

**Jours sans taux de change**
- 10 jours où la TSX **et** les marchés américains ont des prix, mais pas de taux : 2022-09-30, 2022-11-11, 2023-10-02, 2023-11-13, 2024-09-30, 2024-11-11, 2025-09-30, 2025-11-11, 2026-09-30, 2026-11-11. Ce sont des jours fériés fédéraux canadiens où la TSX est ouverte. **Impact direct sur notre calendrier commun** : le dernier taux connu doit être reporté (jamais le suivant). Écart maximal de report : 1 jour de FX publié manquant (3 jours calendaires autour d'un week-end).
- 27 jours ouverts aux États-Unis seulement (fériés canadiens), sans taux : sans importance si l'on exclut ces dates (voir §7).

## 5. Calendriers

| Groupe | Jours |
|---|---|
| TSX (actifs `.TO`) | 1 255 |
| États-Unis (autres actions/FNB) | 1 255 |
| Union TSX ∪ US | 1 282 |
| Intersection TSX ∩ US | **1 228** |
| Jours TSX seulement (fériés américains) | 27 |
| Jours US seulement (fériés canadiens) | 27 |
| Cryptos | 1 827 (dont 545 hors jours de négociation d'actions, dont 23 en semaine) |

Les 27 + 27 écarts sont des fériés (Thanksgiving, 4 juillet, fête de la Reine/Victoria, Civic Holiday, etc.). L'absence de remplissage est confirmée : aucune date inventée.

## 6. Opérations sur titres (`corporate_actions.csv`)

- 658 lignes : 651 dividendes, 7 fractionnements, 0 doublon. Unités : `CAD per share`, `USD per share`, `split ratio (new:old)`.
- Fractionnements : AMZN 20:1 (2022-06-06), GOOGL 20:1 (2022-07-18), SHOP.TO 10:1 (2022-06-29), TSLA 3:1 (2022-08-25), NVDA 10:1 (2024-06-10), CNQ.TO 2:1 (2024-06-11) et **CNQ.TO « 1,021 » (2022-08-22)**.
- **Anomalie CNQ** : le ratio 1,021 coïncide avec un dividende de 0,75 CAD ; CNQ n'a pas fractionné à ce ratio (README). C'est probablement une distribution spéciale. Aucun effet sur nos calculs si on utilise `adj_close` sans réappliquer les événements. Le ratio de 1,021 reste signalé comme non vérifié.
- 28 tickers sur 31 ont des lignes. **BTC-USD, ETH-USD et GLD n'en ont aucune** (normal : pas de dividendes).
- Les prix sont **déjà ajustés des fractionnements** : ne pas réappliquer. Les distributions des FNB peuvent être incomplètes (métadonnées).
- Utilisation prévue : référence et affichage ; **aucun recalcul de rendement à partir de ce fichier**.

## 7. Macro (`macro_rates.csv`)

9 séries, format long, aucune valeur manquante (les manquantes ont été retirées à la source), aucun doublon `(date, série)`.

| Série | Lignes | Début → Fin | Fréquence | Plage |
|---|---|---|---|---|
| V39079 (taux cible BdC) | 1 293 | 2021-11-12 → 2026-11-12 | quotidien (change à l'annonce) | 0,25–5,00 % |
| BD.CDN.2YR.DQ.YLD | 1 245 | idem | jours ouvrables | 0,90–4,97 % |
| BD.CDN.10YR.DQ.YLD | 1 245 | idem | jours ouvrables | 1,32–4,26 % |
| DFF (fonds fédéraux US) | 1 826 | → 2026-11-11 | quotidien | 0,07–5,33 % |
| DGS2 / DGS10 | 1 248 | → 2026-11-10 | jours ouvrables | 0,50–5,19 % / 1,35–5,31 % |
| CPIAUCSL (IPC US, indice) | 59 | 2021-11-01 → 2026-10-01 | mensuel | 278,9–337,5 |
| STATIC_TOTALCPICHANGE (IPC Canada, % a/a) | 58 | 2021-12-01 → 2026-09-01 | mensuel | 1,6–8,1 % |
| UNRATE (chômage US) | 59 | 2021-11-01 → 2026-10-01 | mensuel | 3,4–4,5 % |

**Pièges de cohérence temporelle** : les séries mensuelles sont datées au **mois de référence**, publiées plusieurs semaines après ; les valeurs FRED sont les dernières révisées. Utiliser une valeur à sa date de référence dans une analyse « à la date t » créerait une **fuite d'information future**. Les séries se terminent à des dates différentes (DGS jusqu'au 10 nov., DFF jusqu'au 11 nov.).
**Décision proposée** : le MVP n'utilise pas les séries macro dans les calculs ni dans les règles. Elles servent éventuellement à un contexte descriptif (taux au 2022, par ex.) avec avertissement. Un taux sans risque pour un ratio de Sharpe est exclu du MVP.

## 8. Indications de risque observées (contrôle de plausibilité, non des résultats de l'application)

Calculées sur les 1 218 jours de l'intersection TSX ∩ US ∩ FX, en CAD, `adj_close`, volatilité annualisée avec √252. **Ces valeurs servent de contrôle croisé pour les futurs tests ; elles dépendront des choix de calendrier et d'annualisation définitifs.**

| Actif | Vol. annualisée | Rendement annualisé (CAD) | Max drawdown |
|---|---|---|---|
| ZST.TO | 0,6 % | 3,4 % | −0,4 % |
| XBB.TO | 6,8 % | 0,7 % | −15,5 % |
| XIU.TO | 13,2 % | 13,7 % | −16,4 % |
| SPY | 16,9 % | 14,5 % | −22,2 % |
| TLT | 16,2 % | −5,9 % | −39,7 % |
| QQQ | 23,1 % | 15,3 % | −31,7 % |
| AAPL / MSFT | 28,3 % / 28,5 % | 22,4 % / 12,9 % | −34,0 % / −34,3 % |
| **NVDA** | **51,5 %** | **44,2 %** | **−63,5 %** |
| **TSLA** | **59,6 %** | 5,5 % | −69,8 % |
| BTC-USD | 51,5 % | 4,8 % | −73,7 % |
| ETH-USD | 68,9 % | −13,3 % | −77,2 % |
| SHOP.TO | 65,7 % | 0,0 % | −83,5 % |

Corrélations (rendements quotidiens, CAD) : NVDA–QQQ 0,76, NVDA–SPY 0,68, NVDA–BTC 0,31, NVDA–XBB 0,04, XBB–TLT 0,77.
Épisode 2022 (SPY, XBB, TLT, AGG, ZST ; du 1ᵉʳ au dernier jour de bourse de 2022, en CAD) : SPY −13,3 %, XBB −10,5 %, TLT −24,4 %, AGG −6,7 %, ZST +1,2 % : actions et obligations baissent ensemble, ce qui est utile pour la pédagogie (les obligations ne sont pas « sans risque »).

**Lecture critique pour la démo** : NVDA affiche un rendement historique annualisé élevé (44 %) *et* un drawdown de −63 %. Présenter seulement le rendement conduirait à valider la demande de Robert ; présenter seulement le risque ignorerait l'information. L'application doit montrer les deux, rappeler le biais du survivant (NVDA est choisi en 2026 parce qu'elle est aujourd'hui grande) et le rappel officiel : le passé ne prédit pas l'avenir.

## 9. Limites et risques de qualité

1. **Biais du survivant** (README) : univers choisi en 2026 parmi des grands noms actuels.
2. **Fenêtre unique de 5 ans** : un seul cycle (inflation/hausse de taux 2022, rebond IA). Les résultats dépendent fortement des dates de début et de fin. Les rendements annualisés sont des *descriptions historiques*, pas des espérances.
3. **Données non certifiées** : Yahoo Finance via `yfinance`, non certifié par les bourses ; `adj_close` est rétro-ajusté et change si les données sont retéléchargées → **ne pas retélécharger** pendant le projet ; figer la version (SHA-256).
4. **Licence** : « libre d'utilisation dans le cadre du Datathon » ; les conditions Yahoo restreignent probablement la redistribution. **Ne pas publier les CSV dans un dépôt GitHub public** sans l'avoir confirmé auprès des organisateurs [À CONFIRMER] ; le README du dépôt indiquera où placer les fichiers.
5. **Pas de fondamentaux, pas d'ESG, pas de nouvelles, pas de composition de FNB** : exclut Mateo, l'analyse par titre sous-jacent de QQQ/SPY/XIU et toute étude d'événement.
6. **Décalage de fuseaux** : crypto UTC (clôture 24 h UTC) contre actions (16 h ET) : jusqu'à ~3-4 h de décalage. Impact limité en rendements quotidiens, mais réel sur les corrélations quotidiennes crypto-actions (légèrement sous-estimées).
7. **Dividendes** : `adj_close` suppose le réinvestissement des dividendes ; pas d'impôt ni de retenue, pas de frais, pas d'écart achat-vente.
8. **FX** : les rendements en CAD d'actifs USD incluent l'effet de change (non couvert). Un gain en USD peut être réduit ou amplifié en CAD ; cet effet est visible sur les données (par ex. TLT ou SPY : volatilité en CAD différente de la volatilité native).
9. **Macro** : voir §7.
10. **Exhaustivité de l'audit** : les fichiers ont été audités en structure et plausibilité, pas comparés à une source externe. Les prix ne sont pas validés ligne par ligne contre les bourses.

## 10. Écarts entre les documents

- Le tableau d'actifs *illustratifs* du PDF (page 10) cite BMO.TO, CP.TO, META, COST, VTI, XLF, XLK, XLV, XIC.TO, ZSP.TO, BND, IEF, ZAG.TO, IAU, qui **ne figurent pas** dans le jeu de départ ; à l'inverse, ESGV et ZST.TO sont dans le jeu mais pas dans le tableau. Le PDF précise que ce tableau n'est pas un univers obligatoire. Nous nous limitons aux 31 actifs fournis.
- Le README annonce « 31 actifs, ~40 000 lignes, ~660 actions, ~1 250 FX, ~8 300 macro » : cohérent avec les comptes mesurés (31 ; 40 049 ; 658 ; 1 245 ; 8 281).
- Le README affirme 1 827 lignes crypto contre 1 255 pour les actions : confirmé.
- Les versions FR/EN du PDF et du PPT ont un contenu équivalent sur les critères et pondérations.

## 11. Choix de nettoyage et de préparation recommandés

| # | Décision proposée | Raison |
|---|---|---|
| D1 | Utiliser `adj_close` pour tous les rendements ; ignorer `corporate_actions.csv` dans les calculs | Évite le double ajustement |
| D2 | Conserver ZST.TO 2022-07-06 ; l'indiquer dans la fiche qualité | Prix plausible, effet nul sur le rendement |
| D3 | Ne supprimer ni écrêter aucun mouvement extrême | Épisodes de marché plausibles |
| D4 | Calendrier de calcul : **intersection TSX ∩ US** (1 228 jours), cryptos échantillonnées à ces dates | Aucune date inventée ; aucun rendement artificiel à zéro ; les rendements multi-jours après un férié conservent la valeur cumulative |
| D5 | FX : dernier taux publié ≤ date (report vers l'avant uniquement, jamais vers l'arrière) | Évite la fuite d'information ; 10 jours concernés dans la grille |
| D6 | Conversion : prix `adj_close` en USD × USDCAD(t) → série CAD ; rendements calculés **après** conversion | Capture l'effet de change |
| D7 | Facteur d'annualisation observé : (nombre de périodes − 1) / durée en années de la grille commune (≈ 245,6), affiché ; le facteur 252 reste en option | Évite une annualisation trompeuse quand la grille n'a pas 252 jours/an |
| D8 | Même grille et même fenêtre pour toute comparaison de portefeuilles (intersection des périodes disponibles) | Pas de comparaison sur des périodes différentes |
| D9 | Macro exclue du MVP | Risque de fuite temporelle, pas de besoin immédiat |
| D10 | Données sources en lecture seule ; chargement par un module qui calcule les SHA-256 et refuse les fichiers modifiés (ou le signale) | Reproductibilité |
| D11 | Stocker les données dérivées (grille CAD) en mémoire ou en cache local `parquet/csv` régénérable, jamais à la place des originaux | Séparation brut/dérivé |
