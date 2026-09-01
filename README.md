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
workflows/         n8n / CI (à venir)
characters/        Cache local des caricatures (gitignoré, miroir de la banque)
assets_temp/       Fichiers de travail (gitignoré)
output/            Exports vidéo (gitignoré)
templates/         En-têtes Sheets (Personnages + Vidéos)
supabase/          Schéma SQL alternatif pour la banque
```

Flux prévu :

1. Script / actualité → Google Sheet vidéo de la chaîne.
2. Génération d'images : si `uses_caricatures`, **toujours** `get_or_create_caricature` avant un appel Replicate/FAL.
3. TTS, montage, publication.
4. Chaque étape incrémente `Coût Estimé (€)` à partir de `scripts/pricing.json`.

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

Sur chaque Sheet **vidéo** de chaîne, ajouter la colonne `Coût Estimé (€)` (voir `templates/video_sheet_headers.csv`).

**Supabase** — exécuter `supabase/personnages.sql` dans l'éditeur SQL.

## Ajouter une chaîne

1. Copier `channels/currenttoons.config.json` → `channels/<slug>.config.json`.
2. Ajouter les prompts sous `prompts/<slug>/`.
3. Créer le Google Sheet (colonne `Coût Estimé (€)`).
4. Renseigner `google_sheet_id`, voix ElevenLabs, `uses_caricatures`.
5. Lancer : `python scripts/run_pipeline.py --channel <slug> --dry-run`.

## Lancer les scripts

Toujours tester en dry-run (aucun appel payant) :

```bash
source .venv/bin/activate
python scripts/run_pipeline.py --channel currenttoons --dry-run
python scripts/generate_images.py --channel currenttoons --dry-run --person "Jean Exemple"
python scripts/generate_images.py --channel second_channel --dry-run
pytest
```

Sans `--dry-run`, les scripts visent les APIs réelles (génération d'image pas encore branchée : `NotImplementedError` volontaire jusqu'à la partie 2.1).

## Coûts

Les montants dans `scripts/pricing.json` sont **approximatifs** (EUR), pour repérer les dérives — ce n'est pas la facturation provider.
