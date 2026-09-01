"""Topic collectors driven by channel config. Quota-aware, no paid LLM here."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus
from xml.etree.ElementTree import ParseError

import requests

USER_AGENT = "currenttoons-pipeline/0.1 (topic-monitoring)"
NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_HEADLINES_URL = "https://newsapi.org/v2/top-headlines"


def normalize_item(
    *,
    title: str,
    url: str,
    source: str,
    excerpt: str,
) -> dict[str, str]:
    return {
        "title": (title or "").strip(),
        "url": (url or "").strip(),
        "source": (source or "").strip(),
        "excerpt": (excerpt or "").strip()[:800],
    }


def combine_newsapi_query(keywords: list[str]) -> str:
    parts = []
    for raw in keywords:
        word = raw.strip()
        if not word:
            continue
        if " " in word and not (word.startswith('"') and word.endswith('"')):
            parts.append(f'"{word}"')
        else:
            parts.append(word)
    return " OR ".join(parts)


def _request_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
    max_attempts: int = 3,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code in {429, 500, 502, 503, 504}:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 1.5 * (attempt + 1)
                time.sleep(min(wait, 8))
                last_error = RuntimeError(f"HTTP {response.status_code} for {url}")
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Request failed after {max_attempts} attempts: {last_error}")


def collect_newsapi(config: dict[str, Any], api_key: str) -> list[dict[str, str]]:
    monitoring = config.get("monitoring") or {}
    news = monitoring.get("newsapi") or {}
    keywords = news.get("keywords") or []
    query = combine_newsapi_query(keywords)
    if not query:
        raise ValueError("monitoring.newsapi.keywords is empty")
    max_topics = int(monitoring.get("max_topics") or news.get("page_size") or 8)
    page_size = min(int(news.get("page_size") or max_topics), max_topics, 20)
    max_requests = max(1, int(monitoring.get("max_requests_per_run") or 1))

    params = {
        "q": query,
        "language": news.get("language") or "fr",
        "sortBy": news.get("sort_by") or "publishedAt",
        "pageSize": page_size,
        "page": 1,
        "apiKey": api_key,
    }
    headers = {"User-Agent": USER_AGENT, "X-Api-Key": api_key}
    try:
        response = _request_with_retry(NEWSAPI_URL, params=params, headers=headers)
        payload = response.json()
    except RuntimeError:
        if max_requests < 2:
            raise
        headline_params = {
            "country": news.get("country") or "fr",
            "pageSize": page_size,
            "apiKey": api_key,
        }
        q = keywords[0] if keywords else None
        if q:
            headline_params["q"] = q
        response = _request_with_retry(NEWSAPI_HEADLINES_URL, params=headline_params, headers=headers)
        payload = response.json()

    if payload.get("status") != "ok":
        raise RuntimeError(payload.get("message") or "NewsAPI error")

    items = []
    for article in payload.get("articles") or []:
        url = article.get("url") or ""
        if not url:
            continue
        source = (article.get("source") or {}).get("name") or "NewsAPI"
        excerpt = article.get("description") or article.get("content") or ""
        items.append(
            normalize_item(
                title=article.get("title") or "",
                url=url,
                source=source,
                excerpt=excerpt,
            )
        )
        if len(items) >= max_topics:
            break
    return items


def _parse_feed_xml(xml_text: str, source_fallback: str, limit: int) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ParseError:
        return []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items: list[dict[str, str]] = []

    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        excerpt = (item.findtext("description") or "").strip()
        if title and url:
            items.append(normalize_item(title=title, url=url, source=source_fallback, excerpt=excerpt))
        if len(items) >= limit:
            return items

    for entry in root.findall("atom:entry", ns) or root.findall("{http://www.w3.org/2005/Atom}entry"):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link = entry.find("{http://www.w3.org/2005/Atom}link")
        url = (link.get("href") if link is not None else "") or ""
        excerpt = (
            entry.findtext("{http://www.w3.org/2005/Atom}summary")
            or entry.findtext("{http://www.w3.org/2005/Atom}content")
            or ""
        )
        if title and url:
            items.append(normalize_item(title=title, url=url, source=source_fallback, excerpt=excerpt))
        if len(items) >= limit:
            break
    return items


def collect_rss(feeds: list[str], *, limit_per_feed: int = 3) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for feed in feeds:
        try:
            response = _request_with_retry(feed, headers={"User-Agent": USER_AGENT})
        except RuntimeError:
            continue
        items.extend(_parse_feed_xml(response.text, feed, limit_per_feed))
    return items


def collect_reddit(subreddits: list[str], *, limit_per_sub: int = 3) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    headers = {"User-Agent": USER_AGENT}
    for sub in subreddits:
        url = f"https://www.reddit.com/r/{quote_plus(sub)}/hot.json"
        try:
            response = _request_with_retry(
                url,
                params={"limit": limit_per_sub, "raw_json": 1},
                headers=headers,
            )
            children = (response.json().get("data") or {}).get("children") or []
        except (RuntimeError, ValueError):
            continue
        for child in children:
            data = child.get("data") or {}
            if data.get("stickied"):
                continue
            permalink = data.get("permalink") or ""
            article_url = f"https://www.reddit.com{permalink}" if permalink else (data.get("url") or "")
            items.append(
                normalize_item(
                    title=data.get("title") or "",
                    url=article_url,
                    source=f"reddit/r/{sub}",
                    excerpt=data.get("selftext") or "",
                )
            )
    return items


def collect_google_trends(geo: str, rss_url: str | None, *, limit: int = 4) -> list[dict[str, str]]:
    url = rss_url or f"https://trends.google.com/trending/rss?geo={geo}"
    try:
        response = _request_with_retry(url, headers={"User-Agent": USER_AGENT})
    except RuntimeError:
        return []
    return _parse_feed_xml(response.text, f"Google Trends {geo}", limit)


def collect_web_sources(config: dict[str, Any]) -> list[dict[str, str]]:
    monitoring = config.get("monitoring") or {}
    collectors = monitoring.get("collectors") or ["rss", "reddit", "google_trends"]
    max_topics = int(monitoring.get("max_topics") or 8)
    items: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    def extend(batch: list[dict[str, str]]) -> None:
        for item in batch:
            url = item.get("url") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            items.append(item)

    if "rss" in collectors:
        extend(collect_rss(monitoring.get("rss_feeds") or [], limit_per_feed=3))
    if "reddit" in collectors:
        reddit = monitoring.get("reddit") or {}
        extend(
            collect_reddit(
                reddit.get("subreddits") or [],
                limit_per_sub=int(reddit.get("limit_per_sub") or 3),
            )
        )
    if "google_trends" in collectors:
        trends = monitoring.get("google_trends") or {}
        extend(
            collect_google_trends(
                trends.get("geo") or "FR",
                trends.get("rss_url"),
                limit=int(trends.get("limit") or 4),
            )
        )
    return items[:max_topics]


DRY_RUN_SAMPLES = {
    "newsapi": [
        normalize_item(
            title="Le gouvernement présente un budget rectificatif",
            url="https://dry-run.local/fr/budget",
            source="Le Journal Factice",
            excerpt="Emmanuel Macron et la Première ministre détaillent des mesures économiques devant l'Assemblée.",
        )
    ],
    "web": [
        normalize_item(
            title="Cinq habitudes pour mieux dormir",
            url="https://dry-run.local/wellbeing/sleep",
            source="dry-run-rss",
            excerpt="Un article sur le sommeil, sans personnalité publique.",
        )
    ],
}


def collect_topics_for_channel(config: dict[str, Any], *, dry_run: bool, newsapi_key: str | None) -> list[dict[str, str]]:
    monitoring = config.get("monitoring") or {}
    provider = (monitoring.get("provider") or "newsapi").lower()
    if dry_run:
        return list(DRY_RUN_SAMPLES.get(provider, DRY_RUN_SAMPLES["web"]))
    if provider == "newsapi":
        if not newsapi_key:
            raise RuntimeError("NEWSAPI_KEY is not set")
        return collect_newsapi(config, newsapi_key)
    if provider == "web":
        return collect_web_sources(config)
    raise ValueError(f"Unknown monitoring.provider: {provider}")
