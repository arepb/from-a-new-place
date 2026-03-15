"""Playwright-based browser scraper for bot-protected auction sites.

Most auction sites (Heritage, Invaluable, LiveAuctioneers) block plain
HTTP requests. This module uses a headless Chromium browser to bypass
bot detection and scrape JS-rendered content.

Usage:
    python3 -m scraper.browser_scraper --source heritage --query "contemporary" --pages 2

Requires: pip install playwright && python -m playwright install chromium
"""

import re
import json
import time
import random
import logging
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.base import to_usd

logger = logging.getLogger(__name__)

MAX_PRICE_USD = 5000


def _random_delay(low=2.0, high=5.0):
    time.sleep(random.uniform(low, high))


def scrape_heritage_browser(query="contemporary art", max_pages=3):
    """Scrape Heritage Auctions using Playwright browser."""
    from playwright.sync_api import sync_playwright

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        for page_num in range(max_pages):
            offset = page_num * 28
            url = (
                f"https://fineart.ha.com/c/search-results.zx"
                f"?N=790+231&Nty=0&type=surl-sold&No={offset}"
            )
            if query:
                url += f"&Ntk=SI_Titles&Ntt={query}"

            logger.info(f"Heritage browser: loading page {page_num + 1}")
            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception as e:
                logger.warning(f"Heritage page load failed: {e}")
                break

            _random_delay(2, 4)

            # Extract lot data from the page
            lots = page.evaluate("""
                () => {
                    const results = [];
                    // Heritage uses various selectors for lot listings
                    const cards = document.querySelectorAll(
                        '.search-result-item, [class*="lot-card"], [class*="search-result"]'
                    );

                    // If no structured cards, try to find price/title pairs
                    if (cards.length === 0) {
                        // Look for any elements with price-like text
                        const allElements = document.querySelectorAll('a[href*="/a/"]');
                        for (const el of allElements) {
                            const parent = el.closest('div, li, article, tr');
                            if (!parent) continue;
                            const text = parent.textContent;
                            const priceMatch = text.match(/\\$[\\d,]+/);
                            if (priceMatch) {
                                results.push({
                                    title: el.textContent.trim().substring(0, 200),
                                    url: el.href,
                                    priceText: priceMatch[0],
                                    fullText: text.substring(0, 500),
                                });
                            }
                        }
                    } else {
                        for (const card of cards) {
                            const titleEl = card.querySelector('a[href*="/a/"], .lot-title, h3, h4');
                            const priceEl = card.querySelector('[class*="price"], [class*="realized"]');
                            const dateEl = card.querySelector('time, [class*="date"]');
                            const imgEl = card.querySelector('img');
                            const estEl = card.querySelector('[class*="estimate"]');

                            if (titleEl) {
                                results.push({
                                    title: titleEl.textContent.trim().substring(0, 200),
                                    url: titleEl.href || '',
                                    priceText: priceEl ? priceEl.textContent.trim() : '',
                                    dateText: dateEl ? (dateEl.getAttribute('datetime') || dateEl.textContent.trim()) : '',
                                    imageUrl: imgEl ? (imgEl.src || imgEl.getAttribute('data-src')) : '',
                                    estimateText: estEl ? estEl.textContent.trim() : '',
                                    fullText: card.textContent.trim().substring(0, 500),
                                });
                            }
                        }
                    }
                    return results;
                }
            """)

            for lot in lots:
                parsed = _parse_heritage_lot(lot)
                if parsed and parsed.get("hammer_price"):
                    results.append(parsed)

            logger.info(f"Heritage browser page {page_num + 1}: {len(lots)} raw lots")

            if not lots:
                break

            _random_delay(3, 6)

        browser.close()

    # Filter to sub-$5K
    filtered = []
    for r in results:
        price_usd = to_usd(r.get("hammer_price", 0), r.get("currency", "USD"))
        if price_usd and price_usd <= MAX_PRICE_USD:
            r["hammer_price_usd"] = price_usd
            filtered.append(r)

    logger.info(f"Heritage browser: {len(results)} total, {len(filtered)} under ${MAX_PRICE_USD}")
    return filtered


def _parse_heritage_lot(lot_data):
    """Parse a lot dict from browser evaluation."""
    result = {
        "auction_house": "Heritage Auctions",
        "currency": "USD",
    }

    title = lot_data.get("title", "")
    if " - " in title:
        parts = title.split(" - ", 1)
        result["artist_name"] = parts[0].strip()
        result["title"] = parts[1].strip()
    elif "," in title and len(title.split(",")[0].split()) <= 4:
        parts = title.split(",", 1)
        result["artist_name"] = parts[0].strip()
        result["title"] = parts[1].strip()
    else:
        result["artist_name"] = title
        result["title"] = title

    result["sale_url"] = lot_data.get("url", "")
    result["image_url"] = lot_data.get("imageUrl", "")

    # Source ID from URL
    url_match = re.search(r"/a/(\d+)", result.get("sale_url", ""))
    result["source_id"] = f"heritage-{url_match.group(1)}" if url_match else None

    # Price
    price_text = lot_data.get("priceText", "")
    price_match = re.search(r"[\$£€]?([\d,]+)", price_text)
    if price_match:
        result["hammer_price"] = float(price_match.group(1).replace(",", ""))
    else:
        return None

    # Estimate
    est_text = lot_data.get("estimateText", "")
    est_nums = re.findall(r"[\d,]+", est_text)
    if len(est_nums) >= 2:
        result["estimate_low"] = float(est_nums[0].replace(",", ""))
        result["estimate_high"] = float(est_nums[1].replace(",", ""))

    # Date
    result["sale_date"] = lot_data.get("dateText", "")[:10] or None

    return result


def scrape_invaluable_browser(query="contemporary art", max_pages=3):
    """Scrape Invaluable using Playwright browser."""
    from playwright.sync_api import sync_playwright

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
        )
        page = context.new_page()

        for page_num in range(1, max_pages + 1):
            url = (
                f"https://www.invaluable.com/auction-lot/search"
                f"?query={query}&upcoming=false&salePriceRange=0-5000&page={page_num}"
            )

            logger.info(f"Invaluable browser: loading page {page_num}")
            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception as e:
                logger.warning(f"Invaluable page load failed: {e}")
                break

            _random_delay(2, 4)

            # Try to intercept JSON data from their React app
            lots = page.evaluate("""
                () => {
                    const results = [];

                    // Invaluable renders a React app — try to find lot cards
                    const cards = document.querySelectorAll(
                        '[class*="lot-card"], [class*="LotCard"], [data-testid*="lot"], [class*="search-result"]'
                    );

                    for (const card of cards) {
                        const titleEl = card.querySelector('a[href*="/auction-lot/"], h3, h4, [class*="title"]');
                        const priceEl = card.querySelector('[class*="price"], [class*="Price"]');
                        const houseEl = card.querySelector('[class*="house"], [class*="House"], [class*="auction"]');
                        const dateEl = card.querySelector('time, [class*="date"], [class*="Date"]');
                        const imgEl = card.querySelector('img');

                        if (titleEl) {
                            results.push({
                                title: titleEl.textContent.trim().substring(0, 200),
                                url: titleEl.href || '',
                                priceText: priceEl ? priceEl.textContent.trim() : '',
                                houseText: houseEl ? houseEl.textContent.trim() : '',
                                dateText: dateEl ? (dateEl.getAttribute('datetime') || dateEl.textContent.trim()) : '',
                                imageUrl: imgEl ? (imgEl.src || imgEl.getAttribute('data-src')) : '',
                            });
                        }
                    }

                    // If no structured results, try __NEXT_DATA__ or similar
                    if (results.length === 0) {
                        const nextData = document.getElementById('__NEXT_DATA__');
                        if (nextData) {
                            try {
                                const data = JSON.parse(nextData.textContent);
                                return { nextData: data };
                            } catch(e) {}
                        }
                    }

                    return results;
                }
            """)

            # Handle __NEXT_DATA__ case
            if isinstance(lots, dict) and "nextData" in lots:
                parsed = _parse_invaluable_next_data(lots["nextData"])
                results.extend(parsed)
            elif isinstance(lots, list):
                for lot in lots:
                    parsed = _parse_invaluable_lot(lot)
                    if parsed and parsed.get("hammer_price"):
                        results.append(parsed)

            logger.info(f"Invaluable browser page {page_num}: {len(lots) if isinstance(lots, list) else '?'} lots")

            if isinstance(lots, list) and not lots:
                break

            _random_delay(3, 6)

        browser.close()

    # Filter to sub-$5K
    filtered = []
    for r in results:
        price_usd = to_usd(r.get("hammer_price", 0), r.get("currency", "USD"))
        if price_usd and price_usd <= MAX_PRICE_USD:
            r["hammer_price_usd"] = price_usd
            filtered.append(r)

    logger.info(f"Invaluable browser: {len(results)} total, {len(filtered)} under ${MAX_PRICE_USD}")
    return filtered


def _parse_invaluable_lot(lot_data):
    """Parse a lot dict from Invaluable browser evaluation."""
    result = {
        "auction_house": lot_data.get("houseText", "Unknown"),
        "currency": "USD",
    }

    title = lot_data.get("title", "")
    # Try to split artist from title
    if " - " in title:
        parts = title.split(" - ", 1)
        result["artist_name"] = parts[0].strip()
        result["title"] = parts[1].strip()
    else:
        # Try parenthetical pattern: "Artist Name (Country, Dates)"
        paren_match = re.match(r"^([^(]+)\(", title)
        if paren_match:
            result["artist_name"] = paren_match.group(1).strip()
        else:
            result["artist_name"] = title.split(",")[0].strip() if "," in title else title
        result["title"] = title

    result["sale_url"] = lot_data.get("url", "")
    result["image_url"] = lot_data.get("imageUrl", "")

    # Source ID from URL
    url_match = re.search(r"/auction-lot/[^/]+-(\w+)", result.get("sale_url", ""))
    result["source_id"] = f"invaluable-{url_match.group(1)}" if url_match else None

    # Price
    price_text = lot_data.get("priceText", "")
    result["currency"] = _detect_currency(price_text)
    price_match = re.search(r"[\d,]+", price_text.replace(".", ""))
    if price_match:
        result["hammer_price"] = float(price_match.group().replace(",", ""))
    else:
        return None

    result["sale_date"] = lot_data.get("dateText", "")[:10] or None

    return result


def _parse_invaluable_next_data(next_data):
    """Parse Invaluable's __NEXT_DATA__ JSON for lot data."""
    results = []
    try:
        # Navigate the Next.js data structure to find lot listings
        props = next_data.get("props", {}).get("pageProps", {})
        lots = props.get("lots", props.get("results", props.get("items", [])))

        if isinstance(lots, dict):
            lots = lots.get("items", lots.get("results", []))

        for item in lots:
            result = {
                "artist_name": item.get("artistName", item.get("artist", "")),
                "title": item.get("title", item.get("lotTitle", "")),
                "auction_house": item.get("houseName", item.get("auctionHouseName", "Unknown")),
                "sale_url": f"https://www.invaluable.com{item.get('lotUrl', '')}",
                "image_url": item.get("imageUrl", ""),
                "currency": item.get("currency", "USD"),
                "sale_date": str(item.get("saleDate", ""))[:10],
                "source_id": f"invaluable-{item.get('lotId', item.get('id', ''))}",
            }

            price = item.get("salePrice", item.get("priceRealized"))
            if price:
                result["hammer_price"] = float(price)
                results.append(result)

            est_low = item.get("estimateLow", item.get("lowEstimate"))
            est_high = item.get("estimateHigh", item.get("highEstimate"))
            if est_low:
                result["estimate_low"] = float(est_low)
            if est_high:
                result["estimate_high"] = float(est_high)

    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"Failed to parse Invaluable __NEXT_DATA__: {e}")

    return results


def _detect_currency(text):
    if not text:
        return "USD"
    if "€" in text or "EUR" in text:
        return "EUR"
    if "£" in text or "GBP" in text:
        return "GBP"
    if "CHF" in text:
        return "CHF"
    return "USD"


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="Browser-based auction scraper")
    parser.add_argument("--source", choices=["heritage", "invaluable", "all"], default="all")
    parser.add_argument("--query", "-q", default="contemporary art")
    parser.add_argument("--pages", "-p", type=int, default=3)
    args = parser.parse_args()

    from database import init_db, get_db, find_or_create_artist, insert_auction_result
    init_db()

    all_results = []

    if args.source in ("heritage", "all"):
        print(f"\nScraping Heritage Auctions (browser)...")
        heritage_results = scrape_heritage_browser(query=args.query, max_pages=args.pages)
        all_results.extend(heritage_results)
        print(f"  Heritage: {len(heritage_results)} results under $5K")

    if args.source in ("invaluable", "all"):
        print(f"\nScraping Invaluable (browser)...")
        invaluable_results = scrape_invaluable_browser(query=args.query, max_pages=args.pages)
        all_results.extend(invaluable_results)
        print(f"  Invaluable: {len(invaluable_results)} results under $5K")

    # Save to database
    new_count = 0
    with get_db() as db:
        for r in all_results:
            artist_name = r.pop("artist_name", None)
            if not artist_name:
                continue
            artist_id = find_or_create_artist(
                db, artist_name,
                first_seen_date=datetime.now().strftime("%Y-%m-%d"),
                first_seen_source=r.get("auction_house", "browser"),
            )
            if insert_auction_result(db, artist_id, **r):
                new_count += 1

    print(f"\nTotal: {len(all_results)} results, {new_count} new records saved.")
