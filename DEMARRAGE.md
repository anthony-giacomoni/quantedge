# QuantEdge — Démarrage local

## Prérequis

- Python **3.11 ou 3.12**
- Git optionnel
- Clés API personnelles dans `.env` pour EODHD / Anthropic

## Installation

```bash
cd ~/Downloads/quantedge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
cp .env.example .env
```

Renseigner ensuite les clés dans `.env`. Ce fichier est ignoré par Git.

## Vérification

```bash
python -m compileall -q .
pytest -q
```

## Lancement

```bash
streamlit run app.py
```

## Données locales et mode démo

- `data/quantedge.db` est créé localement et alimenté par le seed de **27 trades taggés stratégie** : 25 clôturés et 2 ouverts.
- Les classeurs personnels `data/simu_invest.xlsm` / `data/simu_invest.xlsx` sont privés et ignorés par Git; les uploads sont validés avant remplacement.
- En son absence, l'application utilise `examples/simu_invest_demo.xlsx`, clairement identifié comme dataset de démonstration.
- Le seed stratégie contient 24 trades gagnants et 1 perdant parmi les 25 clôturés, pour **+2 210,61 €** de P&L réalisé sur ce dataset.

## Important

QuantEdge est un dashboard de recherche/analytics. Il ne réalise aucune exécution automatique et ne revendique ni flux streaming ni P&L temps réel. Les cours sont rafraîchis à la demande à partir des dernières données disponibles.

## News & Catalysts

- Les calendriers EODHD sont utilisés uniquement si la clé locale possède l’entitlement correspondant.
- En cas de 403, le macro US/EU bascule vers les calendriers officiels BLS / Federal Reserve / ECB. Les autres régions sélectionnées restent explicitement indisponibles sans EODHD.
- Les earnings/news de watchlist peuvent basculer vers yfinance avec cache et circuit-breaker sur HTTP 429.
- Aucun calendrier futur manuel n’est livré avec le projet et aucune date de remplacement n’est inventée.


## Export public

Ne jamais zipper directement le dossier local `quantedge/` : il contient volontairement `.env`, `.venv` et `data/`. Construire l’artefact public via l’allowlist :

```bash
python scripts/build_public_release.py /tmp/quantedge_public
python /tmp/quantedge_public/scripts/validate_public_repo.py /tmp/quantedge_public
```
