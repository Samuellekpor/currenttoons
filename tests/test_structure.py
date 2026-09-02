from scripts.character_bank import get_or_create_caricature
from scripts.config import load_channel_config
from scripts.costs import estimate_cost, load_pricing


def test_currenttoons_uses_caricatures():
    config = load_channel_config("currenttoons")
    assert config["uses_caricatures"] is True
    assert config["default_language"] == "fr"
    assert "fr" in config["elevenlabs_voice_id"]


def test_habitlens_skips_caricatures():
    config = load_channel_config("habitlens")
    assert config["uses_caricatures"] is False
    assert config["channel_name"] == "HabitLens"
    assert config["tts_provider"] == "openai"
    assert config["tts_voice_id"]["fr"] == "nova"
    assert config["background_music_url"].endswith("habitlens-bed.wav")
    from pathlib import Path
    from scripts.cli import PROJECT_ROOT

    assert (PROJECT_ROOT / config["background_music_url"]).exists()


def test_pricing_has_defaults():
    pricing = load_pricing()
    assert "caricature_generation" in pricing["defaults"]
    assert estimate_cost("caricature_generation") > 0


def test_get_or_create_caricature_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.character_bank.CHARACTERS_DIR", tmp_path)
    first = get_or_create_caricature("Jean Exemple", "https://example.com/a.jpg", dry_run=True)
    assert first["dry_run"] is True
    assert first["created"] is True
    assert first["Caricature URL"].startswith("https://dry-run.local/")
    second = get_or_create_caricature("Jean Exemple", "https://example.com/a.jpg", dry_run=True)
    assert second["created"] is False
    assert int(second["Nb Utilisations"]) == 2
