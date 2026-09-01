# CurrentToons pipeline

Pipeline local (Python) pour produire des shorts d'actualité sur plusieurs chaînes YouTube / réseaux, avec une **banque de personnages** (caricature une fois, réutilisation ensuite) et un **suivi de coût estimé** par vidéo.

## Architecture

```
channels/          Config JSON par chaîne (ton, Sheet, TTS, langues, caricatures)
prompts/           Prompts système et style image, référencés par la config
scripts/           CLI Python (tous acceptent --dry-run)
  character_bank.py   get_or_create_caricature()
  costs.py            tarifs scripts/pricing.json + colonne Coût Estimé (€)
  sheets.py           Google Sheets
workflows/         n8n (veille quotidienne)
characters/        Cache local des caricatures (gitignoré, miroir de la banque)
assets_temp/       Fichiers de travail (gitignoré)
output/            Exports vidéo (gitignoré)
templates/         En-têtes Sheets (Personnages + Vidéos)
supabase/          Schéma SQL alternatif pour la banque
```

Flux prévu :

1. Veille quotidienne (`collect_topics.py`) → onglet `Sujets` (statut `À Revoir`).
2. Tu passes une ligne à `Accepté` **et** tu choisis `Format Vidéo (Court/Long)` + `Langue (FR/EN)` — ces deux champs pilotent la suite.
3. Génération d'images : si `uses_caricatures`, **toujours** `get_or_create_caricature` avant un appel Replicate/FAL.
4. TTS, montage, publication.
5. Chaque étape incrémente `Coût Estimé (€)` à partir de `scripts/pricing.json`.

## Prérequis

- Python 3.10+
- Compte Google (Sheet + service account) **ou** projet Supabase
- Clés API listées dans `.env.example`

## Setup local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Renseigner `.env`. Placer le JSON du service account Google hors git, chemin dans `GOOGLE_SHEETS_CREDENTIALS_PATH`.

### Banque Personnages

Deux backends (le code choisit `CHARACTER_BANK_BACKEND`, sinon Supabase si `SUPABASE_URL` est défini, sinon Google Sheets) :

**Google Sheets** — créer un classeur, importer `templates/personnages.csv` (onglet `Personnages`) :

| Nom | Photo Référence URL | Caricature URL | Date Génération | Nb Utilisations |
| --- | --- | --- | --- | --- |

Mettre l'ID dans `PERSONNAGES_SHEET_ID`.

Importer `templates/video_sheet_headers.csv` comme onglet `Sujets` (créé aussi automatiquement au premier run live). Colonnes : Date, article, angle, titre suggéré, personnages, statut, **format et langue vides jusqu'à Accepté**, coût, commentaires.

**Supabase** — exécuter `supabase/personnages.sql` dans l'éditeur SQL.

## Ajouter une chaîne

1. Copier `channels/currenttoons.config.json` → `channels/<slug>.config.json`.
2. Ajouter les prompts sous `prompts/<slug>/`.
3. Créer le Google Sheet (onglet `Sujets`, voir `templates/video_sheet_headers.csv`).
4. Ajouter `monitoring` + `topic_analysis_prompt_path` (`newsapi` ou `web`).
5. Renseigner `google_sheet_id`, voix ElevenLabs, `uses_caricatures`.
6. Lancer : `python scripts/collect_topics.py --channel <slug> --dry-run`.

## Lancer les scripts

Toujours tester en dry-run (aucun appel payant) :

```bash
source .venv/bin/activate
python scripts/run_pipeline.py --channel currenttoons --dry-run
python scripts/collect_topics.py --channel currenttoons --dry-run
python scripts/collect_topics.py --channel second_channel --dry-run
python scripts/analyze_topics.py --channel currenttoons --dry-run --title "Test" --url "https://example.com" --excerpt "Emmanuel Macron"
python scripts/generate_images.py --channel currenttoons --dry-run --person "Jean Exemple"
pytest
```

Sans `--dry-run`, les scripts visent les APIs réelles (génération d'image pas encore branchée : `NotImplementedError` volontaire jusqu'à la partie 2.1).

## Veille

- CurrentToons : un seul appel NewsAPI (`everything`) avec les mots-clés du config combinés en `OR`, retry léger sur 429/5xx, pas de pagination.
- Second channel : RSS + Reddit (JSON public) + Google Trends RSS, listés dans le config.
- Analyse : `prompts/<channel>_topic_analysis.md` via `gpt-4o-mini` (angle, titre, personnages publics).
- n8n : voir `workflows/README.md`.

## Coûts

Les montants dans `scripts/pricing.json` sont **approximatifs** (EUR), pour repérer les dérives — ce n'est pas la facturation provider.
