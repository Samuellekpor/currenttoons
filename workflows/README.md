# Workflows

## Topic monitoring (n8n)

Import `workflows/topic-monitoring.json` into a **self-hosted** n8n (the Execute Command node is not available on n8n Cloud).

1. On the host, set `PIPELINE_ROOT` to this repo (the directory that contains `scripts/` and `.venv/`).
2. The venv must already exist (`python3 -m venv .venv && pip install -r requirements.txt`).
3. `.env` must contain `NEWSAPI_KEY`, `OPENAI_API_KEY`, `GOOGLE_SHEETS_CREDENTIALS_PATH`.
4. Replace `google_sheet_id` in each channel config.
5. Import the workflow, then activate it.

**Trigger:** Schedule-Based, every day at 07:00 Europe/Paris.

**Actions:**

- `scripts/collect_topics.py --channel currenttoons`
- `scripts/collect_topics.py --channel second_channel`

Each run collects sources, calls `gpt-4o-mini` for angle + public figures, then appends rows to the channel Google Sheet tab `Sujets` with status `À Revoir`. Format and language stay empty until you set the status to `Accepté`.

## Script generation (n8n)

Import `workflows/script-generation.json`.

**Trigger:** Google Sheets `rowUpdate` on tab `Sujets` (poll every minute). Runs only if statut = `Accepté`, format + langue renseignés, et `Script Vidéo Généré` encore vide.

**Action:** `scripts/generate_script.py --channel <channel> --row-id <id>`

Set `PIPELINE_ROOT`, `CURRENTTOONS_SHEET_ID`, `SECOND_CHANNEL_SHEET_ID`, and the Google Sheets OAuth credential in n8n. `--row-id` is the sheet row number (or the article URL).

Dry-run:

```bash
.venv/bin/python scripts/generate_script.py --channel currenttoons --row-id 2 --dry-run
```


Dry-run (no paid APIs, no Sheet write):

```bash
.venv/bin/python scripts/collect_topics.py --channel currenttoons --dry-run
```
