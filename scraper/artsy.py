"""Artsy GraphQL API scraper.

Artsy's Metaphysics v2 GraphQL API is publicly accessible and provides
real auction results with hammer prices, estimates, dates, and house names.
No authentication required. This is our primary data source.

API endpoint: https://metaphysics-production.artsy.net/v2
"""

import re
import time
import random
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

ARTSY_API = "https://metaphysics-production.artsy.net/v2"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept": "application/json",
}


def slugify(name):
    """Convert artist name to Artsy slug format: 'Issy Wood' -> 'issy-wood'."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug


def fetch_artist_results(artist_name, max_results=50):
    """
    Fetch auction results for an artist from Artsy's GraphQL API.

    Returns:
        dict with artist info and list of auction result dicts, or None if not found
    """
    slug = slugify(artist_name)

    query = """
    query($artistId: String!, $first: Int!) {
      artist(id: $artistId) {
        name
        nationality
        birthday
        deathday
        slug
        image {
          cropped(width: 100, height: 100) {
            url
          }
        }
        auctionResultsConnection(first: $first, sort: DATE_DESC) {
          totalCount
          edges {
            node {
              internalID
              title
              organization
              saleDate
              priceRealized {
                display
                centsUSD
              }
              estimate {
                display
              }
              mediumText
              dimensionText
              saleTitle
              lotNumber
              images {
                thumbnail {
                  url
                  cropped(width: 50, height: 50) {
                    url
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    variables = {"artistId": slug, "first": max_results}

    try:
        resp = requests.post(
            ARTSY_API,
            json={"query": query, "variables": variables},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Artsy API error for {artist_name}: {e}")
        return None

    artist_data = data.get("data", {}).get("artist")
    if not artist_data:
        logger.debug(f"Artist not found on Artsy: {artist_name} (slug: {slug})")
        return None

    results = []
    edges = (
        artist_data.get("auctionResultsConnection", {}).get("edges", [])
    )
    total = artist_data.get("auctionResultsConnection", {}).get("totalCount", 0)

    for edge in edges:
        node = edge.get("node", {})
        price_realized = node.get("priceRealized", {})
        estimate = node.get("estimate", {})
        images = node.get("images", {})
        thumbnail = images.get("thumbnail", {}) if images else {}

        cents_usd = price_realized.get("centsUSD")
        hammer_price_usd = cents_usd / 100.0 if cents_usd else None

        # Parse estimate range
        est_low, est_high = _parse_estimate(estimate.get("display", ""))

        result = {
            "artist_name": artist_data["name"],
            "title": node.get("title", ""),
            "medium": node.get("mediumText", ""),
            "dimensions": node.get("dimensionText", ""),
            "sale_date": _parse_date(node.get("saleDate", "")),
            "auction_house": node.get("organization", ""),
            "lot_number": str(node.get("lotNumber", "")),
            "estimate_low": est_low,
            "estimate_high": est_high,
            "hammer_price": hammer_price_usd,
            "hammer_price_usd": hammer_price_usd,
            "currency": "USD",
            "sold": 1 if hammer_price_usd and hammer_price_usd > 0 else 0,
            "sale_url": _build_sale_url(
                artist_data.get("slug", slug),
                node.get("internalID", ""),
                node.get("organization", ""),
            ),
            "image_url": (thumbnail.get("cropped", {}) or {}).get("url", "") or thumbnail.get("url", "") if thumbnail else "",
            "source_id": f"artsy-{slugify(artist_data['name'])}-{_parse_date(node.get('saleDate', ''))}-{node.get('lotNumber', '')}",
        }
        results.append(result)

    # Artist portrait image
    artist_image = artist_data.get("image", {})
    artist_image_url = ""
    if artist_image:
        cropped = artist_image.get("cropped", {})
        if cropped:
            artist_image_url = cropped.get("url", "")

    artist_info = {
        "name": artist_data["name"],
        "nationality": artist_data.get("nationality", ""),
        "birth_year": _parse_year(artist_data.get("birthday", "")),
        "death_year": _parse_year(artist_data.get("deathday", "")),
        "total_auction_results": total,
        "image_url": artist_image_url,
    }

    return {"artist": artist_info, "results": results}


def fetch_all_artists(artist_names, max_results_per=50, delay=1.0):
    """
    Fetch auction results for multiple artists.

    Args:
        artist_names: list of artist name strings
        max_results_per: max results per artist
        delay: seconds between API calls

    Returns:
        dict with 'results' (list of auction result dicts) and
        'artist_info' (list of artist info dicts with image_url)
    """
    all_results = []
    all_artist_info = []
    artists_found = 0
    artists_not_found = []

    for i, name in enumerate(artist_names):
        logger.info(f"Artsy: fetching {name} ({i+1}/{len(artist_names)})")

        data = fetch_artist_results(name, max_results=max_results_per)

        if data:
            artists_found += 1
            all_artist_info.append(data["artist"])
            results = data["results"]
            # Keep all results with actual prices (no cap — filter in UI)
            with_prices = [
                r for r in results
                if r["hammer_price_usd"] is not None
                and r["hammer_price_usd"] > 0
            ]
            all_results.extend(with_prices)
            total = data["artist"]["total_auction_results"]
            logger.info(
                f"  {name}: {total} total results, {len(results)} fetched, "
                f"{len(with_prices)} with prices"
            )
        else:
            artists_not_found.append(name)

        # Rate limit
        time.sleep(delay + random.uniform(0, 0.5))

    logger.info(
        f"\nArtsy complete: {artists_found}/{len(artist_names)} artists found, "
        f"{len(all_results)} results with prices"
    )
    if artists_not_found:
        logger.info(f"Not found: {', '.join(artists_not_found)}")

    return {"results": all_results, "artist_info": all_artist_info}


def _build_sale_url(artist_slug, internal_id, organization):
    """Build a URL to view the auction result.

    Primary link goes to the Artsy auction result page.
    """
    if internal_id:
        return f"https://www.artsy.net/auction-result/{internal_id}"
    return ""


def _parse_estimate(est_str):
    """Parse estimate string like 'US$20,000–US$30,000' into (low, high)."""
    if not est_str:
        return None, None

    # Find all numbers
    numbers = re.findall(r"[\d,]+", est_str.replace(".", ""))
    if len(numbers) >= 2:
        try:
            low = float(numbers[0].replace(",", ""))
            high = float(numbers[1].replace(",", ""))

            # Convert from other currencies if needed
            if "£" in est_str or "GBP" in est_str:
                low *= 1.27
                high *= 1.27
            elif "€" in est_str or "EUR" in est_str:
                low *= 1.09
                high *= 1.09
            elif "CHF" in est_str:
                low *= 1.13
                high *= 1.13
            elif "HK$" in est_str or "HKD" in est_str:
                low *= 0.13
                high *= 0.13

            return round(low, 2), round(high, 2)
        except ValueError:
            pass
    return None, None


def _parse_date(date_str):
    """Parse ISO date string to YYYY-MM-DD."""
    if not date_str:
        return None
    return date_str[:10]


def _parse_year(year_str):
    """Parse year from birthday/deathday string."""
    if not year_str:
        return None
    match = re.search(r"\d{4}", str(year_str))
    return int(match.group()) if match else None


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    from database import init_db, get_db, find_or_create_artist, insert_auction_result
    init_db()

    # Get all tracked artists
    with get_db() as db:
        rows = db.execute("SELECT name FROM artists ORDER BY name").fetchall()
        artist_names = [r["name"] for r in rows]

    if not artist_names:
        print("No artists in database. Run seed_artists.py first.")
        sys.exit(1)

    print(f"Fetching auction results for {len(artist_names)} artists from Artsy...\n")
    all_results = fetch_all_artists(artist_names, max_results_per=50, delay=1.0)

    # Save to database
    new_count = 0
    with get_db() as db:
        for r in all_results:
            artist_name = r.pop("artist_name")
            artist_id = find_or_create_artist(
                db, artist_name,
                first_seen_date=datetime.now().strftime("%Y-%m-%d"),
                first_seen_source="artsy",
            )
            if insert_auction_result(db, artist_id, **r):
                new_count += 1

    print(f"\nDone! {len(all_results)} results fetched, {new_count} new records saved.")
