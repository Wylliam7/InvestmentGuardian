### Faits historiques calculés
Sur la période **2021-11-12 au 2026-11-12** (CAD, simulation historique), les trois plus grosses positions du portefeuille A sont :
| Rang | Ticker | Nom | Type | Poids (%) |
|------|--------|-----|---------------|-----------|
| 1 | NVDA | NVIDIA | Action individuelle | 25,0 % |
| 2 | QQQ | Invesco QQQ Trust (Nasdaq-100) | FNB d'actions | 25,0 % |
| 3 | BTC-USD | Bitcoin | Cryptoactif | 20,0 % |
Ces trois positions représentent **70 % du portefeuille**.
### Seuils heuristiques et constats du Guardian Check
Pour le profil **Amira** (26 ans, horizon 15 ans ou plus, niveau de risque élevé), les seuils heuristiques du prototype sont :
- **Plus grande position** : vigilance si > 20 %, conflit si > 35 %.
- **Nombre effectif de positions** : vigilance si < 5, conflit si < 3.
Le portefeuille présente :
- Plus grande position à **25 %** : **vigilance** (au-dessus du seuil de vigilance mais en dessous du seuil de conflit).
- Nombre effectif de positions (lignes) : **5,0** : **OK** (au-dessus du seuil de vigilance).
### Objectifs déclarés du persona Amira
- **Âge** : 26 ans
- **Niveau de risque** : Élevé
- **Horizon** : 15 ans ou plus
### Interprétation
Ces **70 %** de concentration sur trois lignes indiquent une **faible diversification** du portefeuille. Bien qu’aucun seuil de conflit ne soit franchi selon les seuils heuristiques du prototype, cette concentration expose le portefeuille à un **risque de performance corrélée** : une baisse simultanée de ces trois actifs aurait un impact majeur sur la valeur totale du portefeuille.
Le portefeuille inclut un **FNB (QQQ)**, mais la diversification sous-jacente des FNB n’est pas mesurée ici. Par conséquent, le nombre effectif de positions (5) ne reflète pas le nombre réel d’entreprises détenues.
**Limites de l’analyse** :
- Biais du survivant : l’univers de titres a été choisi en 2026 parmi ceux qui sont aujourd’hui importants.
- Fenêtre unique de cinq ans : les résultats dépendent des dates de début et de fin.
- Les données sont une simulation historique ; elles ne prédisent pas les performances futures.
