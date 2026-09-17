import requests

from scripts.collectors import (
    combine_newsapi_query,
    collect_newsapi,
    collect_reddit,
    collect_topics_for_channel,
)
from scripts.config import load_channel_config
from scripts.topic_analysis import TOPIC_SHEET_COLUMNS, analyze_topic, delivery_options_from_row, rejected_row_indexes, to_sheet_row


class _FakeResponse:
    def __init__(self, status_code, payload=None, text="", url="https://example.com"):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.url = url
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code}")
            error.response = self
            raise error


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
    assert "celebrity" in current["monitoring"]["newsapi"]["keywords"]
    assert "bizarre" in current["monitoring"]["newsapi"]["keywords"]
    assert "nottheonion" in current["monitoring"]["reddit"]["subreddits"]
    assert current["monitoring"]["collectors"] == ["reddit"]
    assert current["monitoring"]["newsapi"]["sort_by"] == "publishedAt"
    assert "politique française" not in current["monitoring"]["newsapi"]["keywords"]


def test_collect_dry_run_is_local(monkeypatch):
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    config = load_channel_config("currenttoons")
    items = collect_topics_for_channel(config, dry_run=True, newsapi_key=None)
    assert items
    assert items[0]["url"].startswith("https://dry-run.local/")
    assert "title" in items[0] and "excerpt" in items[0]
    assert any("seagulls" in item["title"].lower() for item in items)


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


def test_rejected_rows_are_listed_bottom_up_ready():
    records = [
        {"Statut (À Revoir/Accepté/Rejeté)": "À Revoir"},
        {"Statut (À Revoir/Accepté/Rejeté)": "Rejeté"},
        {"Statut (À Revoir/Accepté/Rejeté)": "Accepté"},
        {"Statut (À Revoir/Accepté/Rejeté)": "Rejeté"},
    ]
    indexes = rejected_row_indexes(records)
    assert indexes == [3, 5]
    assert sorted(indexes, reverse=True) == [5, 3]


def test_newsapi_falls_back_when_popularity_returns_empty_articles(monkeypatch):
    config = {
        "monitoring": {
            "max_topics": 4,
            "newsapi": {"keywords": ["celebrity"], "sort_by": "popularity", "page_size": 4},
        }
    }
    calls = []

    def fake_get(url, params=None, headers=None, timeout=20):
        calls.append((url, (params or {}).get("sortBy")))
        if (params or {}).get("sortBy") == "popularity":
            return _FakeResponse(200, {"status": "ok", "totalResults": 99, "articles": []})
        return _FakeResponse(
            200,
            {
                "status": "ok",
                "articles": [
                    {
                        "title": "Fresh celebrity story",
                        "url": "https://news.example/fresh",
                        "description": "A new item",
                        "source": {"name": "Desk"},
                    }
                ],
            },
        )

    monkeypatch.setattr("scripts.collectors.requests.get", fake_get)
    items = collect_newsapi(config, "test-key")
    assert [item["url"] for item in items] == ["https://news.example/fresh"]
    assert calls[0][1] == "popularity"
    assert calls[1][1] == "publishedAt"


def test_reddit_uses_rss_when_json_is_forbidden(monkeypatch):
    atom = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Seagull heist</title>
        <link href="https://www.reddit.com/r/nottheonion/comments/abc/seagull/"/>
        <summary>Birds took lunch.</summary>
      </entry>
    </feed>
    """

    def fake_get(url, params=None, headers=None, timeout=20):
        if url.endswith(".json"):
            return _FakeResponse(403, url=url)
        return _FakeResponse(200, text=atom, url=url)

    monkeypatch.setattr("scripts.collectors.requests.get", fake_get)
    items = collect_reddit(["nottheonion"], limit_per_sub=1)
    assert items
    assert items[0]["title"] == "Seagull heist"
    assert "reddit/r/nottheonion" in items[0]["source"]
