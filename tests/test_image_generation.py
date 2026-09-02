from scripts.config import load_channel_config
from scripts.image_generation import generate_images_for_row, is_flag_checked
from scripts.image_providers import CARICATURE_PROMPT, generate_image
from scripts.script_generation import format_script_cell
from scripts.topic_analysis import STATUS_SCRIPT_GENERATED


def _row(fmt="Court", images_done=False):
    scenes = [
        {"shot": i + 1, "visual": f"Caricature de Emmanuel Macron, plan {i + 1}.", "dialogue": "x"}
        for i in range(4 if fmt == "Court" else 10)
    ]
    script = {
        "title": "t",
        "format": fmt,
        "aspect_ratio": "9:16" if fmt == "Court" else "16:9",
        "characters": ["Emmanuel Macron"],
        "scenes": scenes,
    }
    return {
        "URL Article": "https://dry-run.local/budget",
        "Personnages Identifiés": "Emmanuel Macron",
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
        "Format Vidéo (Court/Long)": fmt,
        "Script Vidéo Généré": format_script_cell(script),
        "Images Générées": images_done,
    }


def test_caricature_prompt_is_exact():
    assert CARICATURE_PROMPT.startswith("Transform this photo into a realistic 3D caricature.")
    assert "high-end animated film look" in CARICATURE_PROMPT


def test_generate_image_dry_run_preview():
    result = generate_image("a desk", "9:16", quality="preview", dry_run=True)
    assert result["dry_run"] is True
    assert result["quality"] == "preview"
    assert result["url"].startswith("https://dry-run.local/images/")


def test_currenttoons_preview_reuses_caricature(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.character_bank.CHARACTERS_DIR", tmp_path)
    config = load_channel_config("currenttoons")
    payload = generate_images_for_row(_row("Court"), config=config, dry_run=True)
    assert payload["aspect_ratio"] == "9:16"
    assert 3 <= len(payload["images"]) <= 5
    assert payload["caricatures"]["Emmanuel Macron"].startswith("https://dry-run.local/characters/")
    refs = {img["reference_image_url"] for img in payload["images"]}
    assert refs == {payload["caricatures"]["Emmanuel Macron"]}
    assert all(img["quality"] == "preview" for img in payload["images"])


def test_long_format_reuses_same_face(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.character_bank.CHARACTERS_DIR", tmp_path)
    config = load_channel_config("currenttoons")
    payload = generate_images_for_row(_row("Long"), config=config, dry_run=True)
    assert payload["aspect_ratio"] == "16:9"
    assert len(payload["images"]) >= 8
    urls = {img["reference_image_url"] for img in payload["images"]}
    assert len(urls) == 1


def test_second_channel_skips_character_bank():
    config = load_channel_config("second_channel")
    payload = generate_images_for_row(_row("Court"), config=config, dry_run=True)
    assert payload["caricatures"] == {}
    assert all(img["reference_image_url"] is None for img in payload["images"])


def test_skips_when_images_already_checked():
    config = load_channel_config("currenttoons")
    try:
        generate_images_for_row(_row(images_done=True), config=config, dry_run=True)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "already checked" in str(exc)


def test_checkbox_helper():
    assert is_flag_checked(True)
    assert is_flag_checked("TRUE")
    assert not is_flag_checked("")
    assert not is_flag_checked(False)
