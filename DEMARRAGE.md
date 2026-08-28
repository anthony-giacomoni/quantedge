# QuantEdge — Guide de démarrage (Anaconda / Spyder)

## Étape 1 — Copier le projet

Crée un dossier `quantedge` quelque part sur ton ordinateur (ex: Bureau, Documents).
Copie-y tous les fichiers du projet en respectant exactement cette structure :

```
quantedge/
├── app.py
├── config.py
├── requirements.txt
├── DEMARRAGE.md
├── data/              ← dossier vide, créé automatiquement
├── modules/
│   ├── __init__.py
│   └── portfolio.py
└── utils/
    ├── __init__.py
    ├── db.py
    ├── market_data.py
    └── seed_trades.py
```

## Étape 2 — Installer les bibliothèques

Ouvre le **Terminal** sur ton Mac :
- Appuie sur **Cmd + Espace**, tape "Terminal", appuie sur Entrée

Dans le Terminal, tape cette commande et appuie sur Entrée :
```
pip install streamlit yfinance pandas plotly anthropic python-dotenv
```

Attends que tout s'installe (1-2 minutes). Tu verras défiler du texte, c'est normal.

## Étape 3 — Lancer le dashboard

Toujours dans le Terminal, navigue vers ton dossier.
Par exemple si tu l'as mis sur le Bureau :
```
cd ~/Desktop/quantedge
```
(ou `cd ~/Documents/quantedge` selon où tu l'as mis)

Puis lance :
```
streamlit run app.py
```

Une page web va s'ouvrir automatiquement sur `http://localhost:8501` avec ton dashboard !

## Ce que tu vas voir

- **KPIs** : P&L total, win rate, meilleur trade, positions ouvertes
- **Equity curve** : ta progression dans le temps
- **P&L par trade** : barres vertes/rouges
- **Répartition sectorielle** : donut chart
- **Tableau complet** : tes 28 trades filtrables

## Tes stats calculées automatiquement

| Métrique | Valeur |
|---|---|
| Trades totaux | 28 |
| Trades clôturés | 26 |
| Positions ouvertes | 2 (Netflix, Aon) |
| **Win rate** | **96%** (24/25 trades comptabilisés) |
| **P&L cumulé clôturé** | **+2 210€** |
| Meilleur trade | +527.5€ (Veeva) |
| Pire trade | -95.76€ (UNH long) |
| Gain moyen | +96.10€ |
| Profit factor | 24.02x |
| Durée moy. trade | 12.6 jours |

## En cas de problème

**"streamlit n'est pas reconnu"** → relance le Terminal et réinstalle : `pip install streamlit`

**"Module not found"** → vérifie que tu es bien dans le dossier quantedge (`cd ~/Desktop/quantedge`)

**Page blanche** → attends 10-15 secondes, les prix se chargent depuis internet (yfinance)
