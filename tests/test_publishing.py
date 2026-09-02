from scripts.config import load_channel_config
from scripts.publishing import (
    AI_DISCLOSURE,
    build_youtube_description,
    confirm_public_publish,
    generate_seo_metadata,
    prepare_and_upload_drafts,
)
from scripts.topic_analysis import STATUS_PENDING_VALIDATION, STATUS_PUBLISHED, STATUS_SCRIPT_GENERATED


def test_youtube_description_has_ai_and_opposite_language():
    text = build_youtube_description("Un pitch.", "FR")
    assert AI_DISCLOSURE in text
    assert "English subtitles available" in text
    text_en = build_youtube_description("A pitch.", "EN")
    assert "Sous-titres français disponibles" in text_en


def test_seo_dry_run_is_in_video_language():
    config = load_channel_config("currenttoons")
    row = {
        "Langue (FR/EN)": "FR",
        "Titre Vidéo Suggéré": "Budget théâtre",
        "Script Vidéo Généré": "{}",
    }
    meta, cost = generate_seo_metadata(row, config=config, video_format="Court", dry_run=True)
    assert meta["contains_synthetic_media"] is True
    assert "#Shorts" in meta["title"]
    assert AI_DISCLOSURE in meta["description"]
    assert cost == 0


def test_draft_upload_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.publishing.PROJECT_ROOT", tmp_path)
    config = load_channel_config("currenttoons")
    assert config.get("x_auto_publish") is False
    row = {
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
        "Format Vidéo (Court/Long)": "Court",
        "Langue (FR/EN)": "FR",
        "Titre Vidéo Suggéré": "Budget",
        "Script Vidéo Généré": "{}",
        "URL Vidéo Finale": "",
        "Vidéo Montée": True,
        "Publiée": False,
        "Coût Estimé (€)": 0.2,
    }
    payload = prepare_and_upload_drafts(row, config=config, channel="currenttoons", row_id="2", dry_run=True)
    assert payload["status"] == STATUS_PENDING_VALIDATION
    assert payload["youtube"]["privacy"] == "unlisted"
    assert payload["youtube"]["containsSyntheticMedia"] is True
    assert payload["tiktok"]["privacy_level"] == "SELF_ONLY"
    assert payload["instagram"]["published"] is False
    assert payload["twitter"].get("skipped") is True
    assert payload["telegram"]["dry_run"] is True


def test_confirm_publish_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.publishing.PROJECT_ROOT", tmp_path)
    config = load_channel_config("second_channel")
    row = {
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
        "Format Vidéo (Court/Long)": "Long",
        "Langue (FR/EN)": "EN",
        "Titre Vidéo Suggéré": "Sleep",
        "Script Vidéo Généré": "{}",
        "Vidéo Montée": True,
        "Publiée": False,
    }
    prepare_and_upload_drafts(row, config=config, channel="second_channel", row_id="9", dry_run=True)
    confirmed = confirm_public_publish(config=config, channel="second_channel", row_id="9", dry_run=True)
    assert confirmed["status"] == STATUS_PUBLISHED
    assert confirmed["youtube"]["privacy"] == "public"


def test_skips_if_already_waiting():
    config = load_channel_config("currenttoons")
    row = {"Vidéo Montée": True, "Publiée": False, "Statut (À Revoir/Accepté/Rejeté)": STATUS_PENDING_VALIDATION}
    try:
        prepare_and_upload_drafts(row, config=config, channel="currenttoons", row_id="1", dry_run=True)
        assert False
    except ValueError as exc:
        assert "waiting" in str(exc).lower()
