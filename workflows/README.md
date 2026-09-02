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
- `scripts/collect_topics.py --channel habitlens`

Each run collects sources, calls `gpt-4o-mini` for angle + public figures, then appends rows to the channel Google Sheet tab `Sujets` with status `À Revoir`. Format and language stay empty until you set the status to `Accepté`.

## Script generation (n8n)

Import `workflows/script-generation.json`.

**Trigger:** Google Sheets `rowUpdate` on tab `Sujets` (poll every minute). Runs only if statut = `Accepté`, format + langue renseignés, et `Script Vidéo Généré` encore vide.

**Action:** `scripts/generate_script.py --channel <channel> --row-id <id>`

Set `PIPELINE_ROOT`, `CURRENTTOONS_SHEET_ID`, `HABITLENS_SHEET_ID`, and the Google Sheets OAuth credential in n8n. `--row-id` is the sheet row number (or the article URL).

Dry-run:

```bash
.venv/bin/python scripts/generate_script.py --channel currenttoons --row-id 2 --dry-run
```

## Image generation (n8n)

Import `workflows/image-generation.json`.

**Trigger:** Google Sheets `rowUpdate` when statut = `Script Généré` and `Images Générées` is not checked.

**Action:** `scripts/generate_images.py --channel <channel> --row-id <id>`

Preview images only. Upscale later with `--upscale` on retained URLs (montage step).

```bash
.venv/bin/python scripts/generate_images.py --channel currenttoons --row-id 2 --dry-run
```

## Voiceover (n8n)

Import `workflows/voiceover.json`.

**Trigger:** statut `Script Généré` + `Images Générées` coché, `Voix-off Générée` non coché.

**Action:** `scripts/generate_voiceover.py --channel <channel> --row-id <id>`

Audio + timestamps JSON + `.srt` (langue opposée) dans `output/<channel>/<row-id>/`.

```bash
.venv/bin/python scripts/generate_voiceover.py --channel currenttoons --row-id 2 --dry-run
```

## Video assembly (n8n)

Import `workflows/video-assembly.json`.

**Trigger:** `Script Généré` + `Images Générées` + `Voix-off Générée`, `Vidéo Montée` non coché.

**Action:** `scripts/assemble_video.py --channel <channel> --row-id <id>`

Requires **ffmpeg** on the host. Output: `output/<channel>/<row-id>/final.mp4` (+ `chapters.txt` for long videos). Work files in `assets_temp/assembly/` are deleted after export.

```bash
.venv/bin/python scripts/assemble_video.py --channel currenttoons --row-id 2 --dry-run
```

## Publish drafts + Telegram gate (n8n)

Import `workflows/publish-draft.json` and `workflows/publish-confirmed.json`.

**Draft trigger:** `Vidéo Montée` coché, `Publiée` non coché, statut ≠ `En Attente de Validation`.

**Action:** `scripts/publish_video.py --channel <channel> --row-id <id>`

Uploads YouTube **unlisted** (`containsSyntheticMedia` when the API accepts it), TikTok **inbox / SELF_ONLY**, Instagram Reels **container without `media_publish`**. X posts only if `x_auto_publish` is true in the channel config (default false). Then Telegram (or `NOTIFY_EMAIL`) with a button hitting the `publish_confirmed` webhook.

**Confirm webhook:** GET `publish_confirmed?channel=&row_id=&secret=` → `scripts/confirm_publish.py`. Sheet status becomes `Publiée`.

`PUBLISH_WEBHOOK_URL` must be HTTPS (Telegram URL buttons). Set `PUBLISH_WEBHOOK_SECRET`. Host the MP4 at `PUBLIC_ASSET_BASE_URL` for Instagram.

```bash
.venv/bin/python scripts/publish_video.py --channel currenttoons --row-id 2 --dry-run
.venv/bin/python scripts/confirm_publish.py --channel currenttoons --row-id 2 --dry-run
```

Dry-run (no paid APIs, no Sheet write):

```bash
.venv/bin/python scripts/collect_topics.py --channel currenttoons --dry-run
```
