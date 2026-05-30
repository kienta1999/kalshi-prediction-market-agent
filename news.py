"""News LINKS (not article bodies) for the past N days. Prints JSON.

Returns links from yfinance plus a Google News RSS query. The invest skill reads
the actual article content with the WebFetch tool — this tool only finds URLs.

Usage:
  python news.py AAPL --days 7
  python news.py "S&P 500" --days 3 --query   # free-text query instead of ticker
"""

import argparse
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser


def _within(ts, cutoff) -> bool:
    if ts is None:
        return True  # keep undated rather than drop
    return ts >= cutoff


def _from_yfinance(ticker: str, cutoff) -> list[dict]:
    import yfinance as yf

    out = []
    try:
        items = yf.Ticker(ticker).news or []
    except Exception:  # noqa: BLE001
        return out
    for it in items:
        # yfinance >=0.2.40 nests fields under "content"
        c = it.get("content", it)
        title = c.get("title")
        url = (c.get("canonicalUrl") or {}).get("url") if isinstance(
            c.get("canonicalUrl"), dict) else c.get("link") or it.get("link")
        pub = c.get("pubDate") or c.get("providerPublishTime")
        ts = None
        if isinstance(pub, (int, float)):
            ts = datetime.fromtimestamp(pub, tz=timezone.utc)
        elif isinstance(pub, str):
            try:
                ts = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            except ValueError:
                ts = None
        if url and _within(ts, cutoff):
            out.append({"title": title, "url": url,
                        "published": ts.isoformat() if ts else None,
                        "source": "yfinance"})
    return out


def _from_google_news(query: str, days: int, cutoff) -> list[dict]:
    url = (f"https://news.google.com/rss/search?q={quote_plus(query)}+when:{days}d"
           "&hl=en-US&gl=US&ceid=US:en")
    feed = feedparser.parse(url)
    out = []
    for e in feed.entries:
        ts = None
        if getattr(e, "published_parsed", None):
            ts = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        if _within(ts, cutoff):
            out.append({"title": e.get("title"), "url": e.get("link"),
                        "published": ts.isoformat() if ts else None,
                        "source": "google_news"})
    return out


def fetch(term: str, days: int = 7, is_query: bool = False) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    links: list[dict] = []
    if not is_query:
        links += _from_yfinance(term, cutoff)
    links += _from_google_news(term, days, cutoff)
    # de-dupe by url
    seen, deduped = set(), []
    for l in links:
        if l["url"] and l["url"] not in seen:
            seen.add(l["url"])
            deduped.append(l)
    return {"term": term, "days": days, "count": len(deduped), "links": deduped}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="News links for past N days (JSON)")
    p.add_argument("term", help="ticker (default) or free-text with --query")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--query", action="store_true",
                   help="treat term as a free-text search, skip yfinance")
    args = p.parse_args(argv)
    try:
        out = fetch(args.term, args.days, args.query)
    except Exception as exc:  # noqa: BLE001
        out = {"term": args.term, "error": str(exc)}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
