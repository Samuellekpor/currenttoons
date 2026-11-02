from pathlib import Path

from scripts.config import load_channel_config
from scripts.script_generation import FORMAT_SPECS
from scripts.topic_analysis import STATUS_SCRIPT_GENERATED
from scripts.video_assembly import (
    assemble_video_for_row,
    chapters_from_clips,
    clip_zoom_expr,
    parse_image_list,
    parse_srt_cues,
    plan_clips,
    spoken_caption_segments,
    youtube_chapters_text,
    Clip,
    TRANSITION_S,
)


def test_parse_srt_and_spoken_captions():
    srt = "1\n00:00:00,000 --> 00:00:01,200\nLe hook explose\n\n2\n00:00:01,200 --> 00:00:02,000\nChute\n"
    cues = parse_srt_cues(srt)
    assert cues[0]["text"] == "Le hook explose"
    assert abs(cues[0]["end"] - 1.2) < 0.001
    spoken = spoken_caption_segments(
        {"segments": [{"start": 0, "end": 1, "text": "Bonjour"}, {"start": 1, "end": 1, "text": ""}]}
    )
    assert len(spoken) == 1
    assert spoken[0]["end"] > spoken[0]["start"]
    chunked = spoken_caption_segments(
        {
            "segments": [
                {
                    "text": "Mes chers compatriotes il est temps",
                    "words": [
                        {"word": "Mes", "start": 0.0, "end": 0.2},
                        {"word": "chers", "start": 0.2, "end": 0.4},
                        {"word": "compatriotes", "start": 0.4, "end": 0.8},
                        {"word": "il", "start": 0.8, "end": 1.0},
                        {"word": "est", "start": 1.0, "end": 1.2},
                        {"word": "temps", "start": 1.2, "end": 1.5},
                        {"word": "de", "start": 1.5, "end": 1.7},
                    ],
                }
            ]
        }
    )
    assert len(chunked) == 2
    assert chunked[0]["text"].startswith("Mes chers")


def test_clip_motion_alternates_zoom_direction():
    assert "zoom+0.004" in clip_zoom_expr(1)
    assert "zoom-0.004" in clip_zoom_expr(2)
    assert TRANSITION_S <= 0.08
    assert FORMAT_SPECS["Court"]["width"] == 1080
    assert FORMAT_SPECS["Court"]["height"] == 1920
    assert FORMAT_SPECS["Long"]["width"] == 1920
    assert FORMAT_SPECS["Long"]["height"] == 1080


def test_parse_image_list_json():
    items = parse_image_list('[{"shot": 1, "url": "https://x/a.png"}, {"shot": 2, "url": "https://x/b.png"}]')
    assert len(items) == 2
    assert items[0]["shot"] == 1
    messy = parse_image_list(
        '[{"shot": "Plan rapproché", "url": "https://x/a.png"}, {"shot": 2, "url": "https://x/b.png"}]'
    )
    assert messy[0]["shot"] == 1
    assert messy[1]["shot"] == 2


def test_plan_clips_cycles_images_quickly(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    clips = plan_clips(
        [(1, a), (2, b)],
        {"segments": [{"start": 0, "end": 2}, {"start": 2, "end": 6}]},
        audio_duration=6,
    )
    assert abs(sum(c.duration for c in clips) - 6) < 0.05
    assert max(c.duration for c in clips) <= 1.5
    assert len(clips) >= 4


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
    assert payload["caption_method"] in {"srt", "subtitles", "drawtext", "overlay"}
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
