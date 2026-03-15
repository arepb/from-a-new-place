"""Signal scrapers — editorial mentions, Google Trends, and other leading indicators.

These are non-price signals that often predict price movement:
- Art press coverage (first review → group show → solo show → price spike)
- Google search interest (correlates with collector attention)
"""

import re
import logging
from datetime import datetime

import feedparser

logger = logging.getLogger(__name__)

# Major art publications RSS feeds
DEFAULT_FEEDS = [
    {"name": "Artforum", "url": "https://www.artforum.com/rss"},
    {"name": "Hyperallergic", "url": "https://hyperallergic.com/feed/"},
    {"name": "Frieze", "url": "https://www.frieze.com/rss"},
    {"name": "ARTnews", "url": "https://www.artnews.com/feed/"},
    {"name": "The Art Newspaper", "url": "https://www.theartnewspaper.com/rss"},
]


def scan_editorial_feeds(artist_names, feeds=None):
    """
    Scan RSS feeds for mentions of tracked artists.

    Args:
        artist_names: list of artist name strings to search for
        feeds: list of dicts with 'name' and 'url' keys

    Returns:
        list of signal dicts: {artist_name, signal_type, signal_date, source, details}
    """
    feeds = feeds or DEFAULT_FEEDS
    signals = []

    # Build a lookup: lowercase last name → full name
    name_lookup = {}
    for name in artist_names:
        parts = name.strip().split()
        if parts:
            last = parts[-1].lower()
            name_lookup[last] = name
            # Also index full name lowercase
            name_lookup[name.lower()] = name

    for feed_info in feeds:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:50]:  # Last 50 entries per feed
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                text = f"{title} {summary}".lower()

                for key, full_name in name_lookup.items():
                    if key in text:
                        # Verify it's likely an artist mention, not a coincidence
                        if _is_likely_artist_mention(key, text):
                            pub_date = _parse_feed_date(entry)
                            signals.append({
                                "artist_name": full_name,
                                "signal_type": "editorial_mention",
                                "signal_date": pub_date,
                                "source": feed_info["name"],
                                "details": title[:200],
                            })
                            logger.info(
                                f"Signal: {full_name} mentioned in {feed_info['name']}: {title[:80]}"
                            )
        except Exception as e:
            logger.warning(f"Failed to parse feed {feed_info['name']}: {e}")

    return signals


def _is_likely_artist_mention(name_part, text):
    """Basic heuristic to avoid false positives on common names."""
    # If the name part is very short (< 4 chars), require it to appear
    # near art-related keywords
    if len(name_part) < 4:
        art_words = [
            "artist", "painting", "exhibition", "gallery", "show",
            "sculpture", "work", "piece", "solo", "group", "museum",
            "collection", "auction", "contemporary",
        ]
        # Check if any art word is within 100 chars of the name
        idx = text.find(name_part)
        if idx >= 0:
            context = text[max(0, idx - 100):idx + 100]
            return any(w in context for w in art_words)
        return False
    return True


def _parse_feed_date(entry):
    """Extract and normalize date from feed entry."""
    date_str = entry.get("published", entry.get("updated", ""))
    if not date_str:
        return datetime.now().strftime("%Y-%m-%d")

    # feedparser usually provides published_parsed
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime(*parsed[:3]).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    return datetime.now().strftime("%Y-%m-%d")


def check_google_trends(artist_names, timeframe="today 3-m"):
    """
    Check Google Trends for search interest in artist names.

    Returns list of dicts: {artist_name, interest_score, change_pct}

    Requires pytrends: pip install pytrends
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("pytrends not installed, skipping Google Trends")
        return []

    pytrends = TrendReq(hl="en-US", tz=360)
    results = []

    # Google Trends allows max 5 keywords at once
    for i in range(0, len(artist_names), 5):
        batch = artist_names[i:i + 5]
        try:
            pytrends.build_payload(batch, timeframe=timeframe)
            interest = pytrends.interest_over_time()

            if interest.empty:
                continue

            for name in batch:
                if name in interest.columns:
                    values = interest[name].values
                    if len(values) >= 2:
                        recent = float(values[-1])
                        earlier = float(values[0])
                        change = (
                            ((recent - earlier) / earlier * 100)
                            if earlier > 0 else 0
                        )
                        results.append({
                            "artist_name": name,
                            "interest_score": recent,
                            "change_pct": round(change, 1),
                        })

        except Exception as e:
            logger.warning(f"Google Trends error for batch {batch}: {e}")

    return results
