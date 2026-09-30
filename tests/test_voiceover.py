from scripts.config import load_channel_config
from scripts.script_generation import format_script_cell
from scripts.topic_analysis import STATUS_SCRIPT_GENERATED
from scripts.voiceover import (
    _first_http_url,
    extract_voiceover_text,
    generate_voiceover,
    generate_voiceover_for_row,
    opposite_language,
    segments_to_srt,
    srt_timestamp,
)


def test_aimlapi_tts_json_url_shapes():
    assert _first_http_url({"url": "https://s3.aimlapi.com/files/abc"}) == "https://s3.aimlapi.com/files/abc"
    assert _first_http_url({"audio": {"url": "https://s3.aimlapi.com/files/abc"}}) == "https://s3.aimlapi.com/files/abc"


def test_opposite_language():
    assert opposite_language("FR") == "EN"
    assert opposite_language("en") == "FR"


def test_extract_voiceover_concatenates_dialogues():
    script = {
        "scenes": [
            {"shot": 1, "visual": "ignore", "dialogue": "Bonjour."},
            {"shot": 2, "visual": "ignore", "dialogue": "Le budget passe."},
        ]
    }
    extracted = extract_voiceover_text(script)
    assert extracted["text"] == "Bonjour. Le budget passe."
    assert len(extracted["segments"]) == 2


def test_srt_timestamp_and_cues():
    assert srt_timestamp(0) == "00:00:00,000"
    assert srt_timestamp(65.5) == "00:01:05,500"
    srt = segments_to_srt(
        [{"text": "Hello there", "start": 0, "end": 1.2}, {"text": "Next", "start": 1.2, "end": 2}]
    )
    assert "00:00:00,000 --> 00:00:01,200" in srt
    assert "Hello there" in srt
    assert "Next" in srt


def test_generate_voiceover_dry_run_has_word_timestamps():
    result = generate_voiceover("Bonjour le monde", "elevenlabs", "voice", "FR", dry_run=True)
    assert result["dry_run"] is True
    assert result["words"]
    assert result["words"][0]["word"] == "Bonjour"
    assert result["words"][-1]["end"] > result["words"][0]["start"]
    assert result["words"][-1]["end"] < 1.0


def test_scale_word_times_speeds_up_alignment():
    from scripts.voiceover import _scale_word_times

    scaled = _scale_word_times([{"word": "a", "start": 0.0, "end": 1.0}], 0.5)
    assert scaled[0]["end"] == 0.5


def test_row_pipeline_fr_subtitles_en(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.voiceover.PROJECT_ROOT", tmp_path)
    config = load_channel_config("currenttoons")
    script = {
        "scenes": [
            {"shot": 1, "dialogue": "Le budget est une pièce."},
            {"shot": 2, "dialogue": "Tout le monde applaudit."},
        ]
    }
    row = {
        "URL Article": "https://dry-run.local/x",
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
        "Langue (FR/EN)": "FR",
        "Script Vidéo Généré": format_script_cell(script),
        "Images Générées": True,
        "Voix-off Générée": False,
    }
    payload = generate_voiceover_for_row(row, config=config, channel="currenttoons", row_id="2", dry_run=True)
    assert payload["provider"] == "elevenlabs"
    assert payload["language"] == "FR"
    assert payload["subtitle_language"] == "EN"
    assert payload["translated_segments"][0]["text"].startswith("[EN]")
    assert "-->" in payload["srt"]
    assert payload["audio_url"].startswith("https://dry-run.local/")


def test_habitlens_uses_openai_tts():
    config = load_channel_config("habitlens")
    row = {
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
        "Langue (FR/EN)": "EN",
        "Script Vidéo Généré": format_script_cell({"scenes": [{"dialogue": "Sleep is a skill."}]}),
        "Images Générées": True,
        "Voix-off Générée": False,
    }
    payload = generate_voiceover_for_row(
        row, config=config, channel="habitlens", row_id="9", dry_run=True
    )
    assert payload["provider"] == "openai"
    assert payload["subtitle_language"] == "FR"


def test_elevenlabs_payment_error_falls_back_to_aimlapi(monkeypatch):
    monkeypatch.setenv("AIMLAPI_KEY", "aiml-test")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")

    def boom(*_args, **_kwargs):
        raise RuntimeError("ElevenLabs TTS failed: 402 Client Error: Payment Required")

    monkeypatch.setattr("scripts.voiceover._elevenlabs_with_timestamps", boom)
    monkeypatch.setattr(
        "scripts.voiceover._openai_tts_then_align",
        lambda text, voice, lang, model: {
            "audio_bytes": b"id3",
            "words": [{"word": "Hi", "start": 0.0, "end": 0.4}],
            "alignment_source": "whisper",
        },
    )
    result = generate_voiceover("Hi there", "elevenlabs", "Hy28", "FR", dry_run=False)
    assert result["provider"] == "openai"
    assert result["voice_id"] == "nova"
    assert result["audio_bytes"] == b"id3"


def test_requires_images_checked():
    config = load_channel_config("currenttoons")
    row = {
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
        "Langue (FR/EN)": "FR",
        "Script Vidéo Généré": format_script_cell({"scenes": [{"dialogue": "Hi"}]}),
        "Images Générées": False,
    }
    try:
        generate_voiceover_for_row(row, config=config, channel="currenttoons", row_id="1", dry_run=True)
        assert False
    except ValueError as exc:
        assert "Images Générées" in str(exc)
