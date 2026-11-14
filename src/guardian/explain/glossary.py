"""Définitions courtes pour les débutants et info-bulles des indicateurs (noms techniques conservés dans les info-bulles)."""

TERMS = {
    "Actif": "Un investissement que l'on peut détenir : une action, un fonds, une obligation, de l'or ou une cryptomonnaie.",
    "Pondération": "La part de votre argent fictif placée dans un actif, en pourcentage. Toutes les pondérations doivent totaliser 100 %.",
    "FNB": "Fonds négociés en bourse. Un seul FNB détient souvent des dizaines ou des centaines d'investissements, ce qui répartit déjà le risque.",
    "Allocation": "La manière dont votre argent est réparti entre les différents actifs.",
    "Portefeuille fictif": "Une simulation : aucun argent réel n'est utilisé et aucune transaction n'est effectuée.",
}

METRIC_HELP = {
    "return": "Rendement historique (rendement cumulé) : de combien aurait varié la valeur du portefeuille simulé entre le début et la fin de la "
              "période observée. C'est un fait passé, pas un rendement attendu dans le futur.",
    "volatility": "Fluctuations du portefeuille (volatilité annualisée) : l'ampleur typique des hausses et des baisses de la valeur du portefeuille, "
                  "ramenée sur un an. Plus elle est élevée, plus la valeur a varié.",
    "drawdown": "Plus forte baisse historique (drawdown maximal) : la plus grande baisse de valeur observée entre un sommet et le creux qui a suivi.",
    "diversification": "Répartition de mon portefeuille (nombre effectif de positions, 1/HHI) : le nombre de positions de poids égal qui donnerait la même "
                       "diversification. Cette mesure ne tient pas entièrement compte des liens entre actifs ni du contenu des fonds.",
    "annualized": "Rendement annualisé historique : le rendement cumulé ramené à une année (moyenne géométrique). Un fait passé, pas une prévision.",
}

DIVERSIFICATION_HELP = ("Le nombre d'actifs est le nombre de lignes de votre portefeuille. Le nombre équivalent de positions de poids égal résume "
                        "à quel point l'argent est réparti : 3 actifs très inégaux équivalent à moins de 3 positions. Ce n'est pas le nombre "
                        "d'entreprises sous-jacentes, et la mesure ne tient pas entièrement compte des corrélations ni de la diversification interne des fonds (FNB).")
