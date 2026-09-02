from pathlib import Path

from scripts.config import load_channel_config
from scripts.script_generation import FORMAT_SPECS
from scripts.topic_analysis import STATUS_SCRIPT_GENERATED
from scripts.video_assembly import (
    assemble_video_for_row,
    chapters_from_clips,
    parse_image_list,
    plan_clips,
    youtube_chapters_text,
    Clip,
)


def test_resolutions():
    assert FORMAT_SPECS["Court"]["width"] == 1080
    assert FORMAT_SPECS["Court"]["height"] == 1920
    assert FORMAT_SPECS["Long"]["width"] == 1920
    assert FORMAT_SPECS["Long"]["height"] == 1080


def test_parse_image_list_json():
    items = parse_image_list('[{"shot": 1, "url": "https://x/a.png"}, {"shot": 2, "url": "https://x/b.png"}]')
    assert len(items) == 2
    assert items[0]["shot"] == 1


def test_plan_clips_follows_timestamps(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    clips = plan_clips(
        [(1, a), (2, b)],
        {"segments": [{"start": 0, "end": 2}, {"start": 2, "end": 6}]},
        audio_duration=6,
    )
    assert len(clips) == 2
    assert abs(sum(c.duration for c in clips) - 6) < 0.01
    assert clips[0].shot == 1


def test_long_chapters_group_shots():
    clips = [
        Clip(path=Path("a"), start=0, duration=2, shot=1, title="Hook"),
        Clip(path=Path("b"), start=2, duration=2, shot=2),
        Clip(path=Path("c"), start=4, duration=2, shot=3),
        Clip(path=Path("d"), start=6, duration=2, shot=4),
    ]
    chapters = chapters_from_clips(clips, "Long")
    assert len(chapters) == 2
    text = youtube_chapters_text(chapters)
    assert text.startswith("0:00")


def test_assemble_dry_run_writes_video(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.video_assembly.PROJECT_ROOT", tmp_path)
    config = load_channel_config("currenttoons")
    row = {
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
        "Format Vidéo (Court/Long)": "Court",
        "Images Générées": True,
        "Voix-off Générée": True,
        "Vidéo Montée": False,
        "URLs Images": "[]",
        "URL Voix-off": "",
        "URL Timestamps": "",
        "URL Sous-titres (langue opposée)": "",
        "Script Vidéo Généré": "{}",
    }
    payload = assemble_video_for_row(row, config=config, channel="currenttoons", row_id="2", dry_run=True)
    assert payload["width"] == 1080
    assert payload["height"] == 1920
    assert payload["subtitles_burned"] is True
    assert payload["video_url"].endswith("final.mp4")
    video = tmp_path / "output" / "currenttoons" / "2" / "final.mp4"
    assert video.exists()
    assert not (tmp_path / "assets_temp" / "assembly" / "currenttoons" / "2").exists()


def test_requires_voiceover_checked():
    config = load_channel_config("currenttoons")
    row = {
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
        "Images Générées": True,
        "Voix-off Générée": False,
    }
    try:
        assemble_video_for_row(row, config=config, channel="currenttoons", row_id="1", dry_run=True)
        assert False
    except ValueError as exc:
        assert "Voix-off" in str(exc)
