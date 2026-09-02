from scripts.config import load_channel_config
from scripts.script_generation import generate_script, normalize_format, normalize_language
from scripts.topic_analysis import STATUS_ACCEPTED, STATUS_SCRIPT_GENERATED


def test_normalize_language_and_format():
    assert normalize_language("fr") == "FR"
    assert normalize_language("English") == "EN"
    assert normalize_format("short") == "Court"
    assert normalize_format("16:9") == "Long"


def test_generate_script_dry_run_short_fr_names_characters():
    config = load_channel_config("currenttoons")
    row = {
        "Titre Article Original": "Budget",
        "URL Article": "https://dry-run.local/budget",
        "Angle Proposé": "Théâtre",
        "Titre Vidéo Suggéré": "La pièce",
        "Personnages Identifiés": "Emmanuel Macron",
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_ACCEPTED,
        "Format Vidéo (Court/Long)": "Court",
        "Langue (FR/EN)": "FR",
    }
    payload = generate_script(row, config=config, dry_run=True)
    assert payload["language"] == "FR"
    assert payload["format"] == "Court"
    assert payload["aspect_ratio"] == "9:16"
    assert 3 <= len(payload["scenes"]) <= 5
    joined_visuals = " ".join(scene["visual"] for scene in payload["scenes"])
    joined_dialogue = " ".join(scene["dialogue"] for scene in payload["scenes"])
    assert "Emmanuel Macron" in joined_visuals
    assert "Réplique" in joined_dialogue


def test_generate_script_dry_run_long_en():
    config = load_channel_config("habitlens")
    row = {
        "Titre Article Original": "Sleep habits",
        "URL Article": "https://dry-run.local/sleep",
        "Angle Proposé": "Five habits",
        "Titre Vidéo Suggéré": "Sleep better",
        "Personnages Identifiés": "",
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_ACCEPTED,
        "Format Vidéo (Court/Long)": "Long",
        "Langue (FR/EN)": "EN",
    }
    payload = generate_script(row, config=config, dry_run=True)
    assert payload["language"] == "EN"
    assert payload["format"] == "Long"
    assert payload["aspect_ratio"] == "16:9"
    assert len(payload["scenes"]) >= 8
    assert all("16:9" in scene["visual"] for scene in payload["scenes"])


def test_generate_script_rejects_wrong_status():
    config = load_channel_config("currenttoons")
    row = {
        "Statut (À Revoir/Accepté/Rejeté)": "À Revoir",
        "Format Vidéo (Court/Long)": "Court",
        "Langue (FR/EN)": "FR",
    }
    try:
        generate_script(row, config=config, dry_run=True)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Accepté" in str(exc)


def test_status_constant_for_sheet_update():
    assert STATUS_SCRIPT_GENERATED == "Script Généré"
