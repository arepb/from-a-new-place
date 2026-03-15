"""LiveAuctioneers scraper.

Scrapes past auction results from LiveAuctioneers.com by parsing the
embedded window.__data JSON in their React SPA pages.

Data available: hammer prices, estimates, sale dates, auction house,
images, lot URLs. No API key required.
"""

import re
import json
import time
import random
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://www.liveauctioneers.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_artist_results(artist_name, max_results=50):
    """
    Fetch past auction results for an artist from LiveAuctioneers.

    Returns:
        list of auction result dicts, or empty list if not found
    """
    # Use archive search (Price Results tab) — the correct URL pattern
    keyword = requests.utils.quote(artist_name)
    results = []
    page = 1
    per_page = 20  # LA returns ~20 items per page

    while len(results) < max_results:
        page_url = (
            f"{BASE_URL}/search/?keyword={keyword}"
            f"&sort=-relevance&status=archive&page={page}"
        )

        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=15)
            if resp.status_code == 404:
                logger.debug(f"No price results page for {artist_name}")
                break
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"LiveAuctioneers fetch error for {artist_name}: {e}")
            break

        # Extract window.__data JSON
        data = _extract_window_data(resp.text)
        if not data:
            logger.debug(f"No window.__data found for {artist_name}")
            break

        # Get items from itemSummary.byId
        item_summary = data.get("itemSummary", {}).get("byId", {})
        search_data = data.get("search", {})
        item_ids = search_data.get("itemIds", [])

        if not item_ids:
            break

        for item_id in item_ids:
            # Try both string and int keys
            item = item_summary.get(str(item_id), item_summary.get(item_id, {}))
            if not item:
                continue

            sale_price = item.get("salePrice", 0)
            is_sold = item.get("isSold", False)
            currency = item.get("currency", "USD")

            # Convert to USD if needed
            hammer_usd = _to_usd(sale_price, currency, data)

            if not hammer_usd or hammer_usd <= 0:
                continue

            # Parse estimates
            est_low = item.get("lowBidEstimate", None)
            est_high = item.get("highBidEstimate", None)
            if est_low:
                est_low = _to_usd(est_low, currency, data)
            if est_high:
                est_high = _to_usd(est_high, currency, data)

            # Parse date from Unix timestamp
            sale_ts = item.get("saleStartTs", 0)
            sale_date = datetime.fromtimestamp(sale_ts).strftime("%Y-%m-%d") if sale_ts else None

            # Build image URL
            seller_id = item.get("sellerId", "")
            catalog_id = item.get("catalogId", "")
            photos = item.get("photos", [])
            image_version = item.get("imageVersion", "")
            image_url = ""
            if photos and seller_id and catalog_id:
                image_url = f"https://p1.liveauctioneers.com/{seller_id}/{catalog_id}/{item_id}_1_x.jpg?version={image_version}"

            # Build lot URL
            lot_slug = item.get("slug", "")
            sale_url = f"{BASE_URL}/item/{item_id}_{lot_slug}" if lot_slug else f"{BASE_URL}/item/{item_id}"

            result = {
                "artist_name": artist_name,
                "title": item.get("title", ""),
                "medium": "",  # Not reliably available
                "dimensions": "",
                "sale_date": sale_date,
                "auction_house": item.get("sellerName", ""),
                "lot_number": str(item.get("lotNumber", "")),
                "estimate_low": est_low,
                "estimate_high": est_high,
                "hammer_price": hammer_usd,
                "hammer_price_usd": hammer_usd,
                "currency": "USD",
                "sold": 1 if is_sold else 0,
                "sale_url": sale_url,
                "image_url": image_url,
                "source_id": f"la-{item_id}",
            }
            results.append(result)

            if len(results) >= max_results:
                break

        # Check if there are more pages
        total_found = search_data.get("totalFound", 0) or data.get("priceResult", {}).get("totalFound", 0)
        if len(results) >= total_found or len(item_ids) < per_page:
            break

        page += 1
        time.sleep(1 + random.uniform(0, 0.5))

    logger.info(f"LiveAuctioneers: {artist_name} → {len(results)} results")
    return results


def fetch_all_artists(artist_names, max_results_per=50, delay=1.5):
    """
    Fetch auction results for multiple artists from LiveAuctioneers.

    Returns:
        dict with 'results' (list of auction result dicts)
    """
    all_results = []
    found = 0

    for i, name in enumerate(artist_names):
        logger.info(f"LiveAuctioneers: fetching {name} ({i+1}/{len(artist_names)})")

        results = fetch_artist_results(name, max_results=max_results_per)
        if results:
            found += 1
            all_results.extend(results)

        time.sleep(delay + random.uniform(0, 1.0))

    logger.info(
        f"LiveAuctioneers complete: {found}/{len(artist_names)} artists found, "
        f"{len(all_results)} results"
    )
    return {"results": all_results}


def _extract_window_data(html):
    """Extract and parse window.__data JSON from page HTML."""
    match = re.search(r'window\.__data\s*=\s*({.*?});\s*</script>', html, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.warning("Failed to parse window.__data JSON")
        return None


def _to_usd(amount, currency, data):
    """Convert amount to USD using embedded currency conversion rates."""
    if not amount or amount <= 0:
        return None
    if currency == "USD":
        return round(float(amount), 2)

    # Try to get conversion rate from embedded data
    currencies = data.get("currency", {}).get("rates", {})
    if not currencies:
        # Try alternate structure
        currency_data = data.get("currency", {})
        if isinstance(currency_data, dict):
            for key, val in currency_data.items():
                if isinstance(val, dict) and val.get("currencyCode") == currency:
                    rate = val.get("conversionToUsd", 0)
                    if rate > 0:
                        return round(float(amount) * rate, 2)

    # Fallback rough conversion rates
    fallback_rates = {
        "GBP": 1.27, "EUR": 1.09, "CHF": 1.13, "CAD": 0.74,
        "AUD": 0.65, "JPY": 0.0067, "HKD": 0.13, "SEK": 0.096,
        "DKK": 0.146, "NOK": 0.094, "CNY": 0.14,
    }
    rate = fallback_rates.get(currency, 1.0)
    return round(float(amount) * rate, 2)
