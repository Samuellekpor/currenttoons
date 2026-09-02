from scripts.collectors import combine_newsapi_query, collect_topics_for_channel
from scripts.config import load_channel_config
from scripts.topic_analysis import TOPIC_SHEET_COLUMNS, analyze_topic, delivery_options_from_row, to_sheet_row


def test_newsapi_query_combines_phrases():
    query = combine_newsapi_query(["actualité France", "gouvernement", "économie française"])
    assert '"actualité France"' in query
    assert "gouvernement" in query
    assert " OR " in query


def test_channel_monitoring_providers():
    current = load_channel_config("currenttoons")
    second = load_channel_config("habitlens")
    assert current["monitoring"]["provider"] == "newsapi"
    assert second["monitoring"]["provider"] == "web"
    assert current["topic_analysis_prompt_path"].endswith("currenttoons_topic_analysis.md")


def test_collect_dry_run_is_local(monkeypatch):
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    config = load_channel_config("currenttoons")
    items = collect_topics_for_channel(config, dry_run=True, newsapi_key=None)
    assert items
    assert items[0]["url"].startswith("https://dry-run.local/")
    assert "title" in items[0] and "excerpt" in items[0]


def test_analyze_dry_run_extracts_public_figures():
    config = load_channel_config("currenttoons")
    item = {
        "title": "Allocution d'Emmanuel Macron",
        "url": "https://dry-run.local/macron",
        "source": "test",
        "excerpt": "Emmanuel Macron s'exprime sur le budget.",
    }
    result = analyze_topic(item, config=config, dry_run=True)
    assert result["mentions_public_figures"] is True
    assert "Emmanuel Macron" in result["public_figures"]
    assert result["suggested_video_title"]
    row = to_sheet_row(result, today="2026-09-01")
    assert row["Statut (À Revoir/Accepté/Rejeté)"] == "À Revoir"
    assert row["Format Vidéo (Court/Long)"] == ""
    assert row["Langue (FR/EN)"] == ""
    assert list(row.keys()) == TOPIC_SHEET_COLUMNS


def test_delivery_options_only_when_accepted():
    row = to_sheet_row(
        {
            "title": "x",
            "url": "https://example.com",
            "angle": "a",
            "suggested_video_title": "t",
            "public_figures": [],
            "source": "s",
            "cost_eur": 0,
        }
    )
    try:
        delivery_options_from_row(row)
        assert False, "expected ValueError"
    except ValueError:
        pass
    row["Statut (À Revoir/Accepté/Rejeté)"] = "Accepté"
    row["Format Vidéo (Court/Long)"] = "Court"
    row["Langue (FR/EN)"] = "FR"
    assert delivery_options_from_row(row) == {"format": "Court", "language": "FR"}
