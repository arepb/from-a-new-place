"""Invaluable.com scraper.

Invaluable aggregates results from 5,000+ auction houses globally.
It's the best single source for sub-$5K art because it covers regional
and smaller houses that the major platforms miss.

Uses their search/browse endpoints.
"""

import re
import json
import logging
from datetime import datetime
from .base import BaseScraper

logger = logging.getLogger(__name__)


class InvaluableScraper(BaseScraper):
    name = "invaluable"
    base_url = "https://www.invaluable.com"
    min_delay = 3.0
    max_delay = 7.0

    # Invaluable has a JSON API behind their search
    SEARCH_API = "https://www.invaluable.com/api/search"

    def scrape(self, query=None, max_pages=5):
        """Scrape Invaluable past auction results."""
        results = []

        for page in range(1, max_pages + 1):
            page_results = self._fetch_page(query, page)
            if not page_results:
                break
            results.extend(page_results)
            logger.info(
                f"Invaluable page {page}: found {len(page_results)} results"
            )

        self.results_found = len(results)
        return results

    def _fetch_page(self, query, page):
        """Fetch a single page of results."""
        # Try the JSON API first
        api_results = self._try_api(query, page)
        if api_results is not None:
            return api_results

        # Fall back to HTML scraping
        return self._try_html(query, page)

    def _try_api(self, query, page):
        """Try Invaluable's internal JSON API."""
        params = {
            "query": query or "contemporary art",
            "upcoming": "false",  # past results only
            "salePriceRange": "0-5000",
            "page": str(page),
            "pageSize": "48",
            "sort": "sale_date_desc",
        }

        resp = self.fetch(self.SEARCH_API, params=params)
        if not resp:
            return None

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            return None

        results = []
        items = data.get("results", data.get("items", data.get("lots", [])))

        for item in items:
            try:
                result = self._parse_api_item(item)
                if result:
                    results.append(result)
            except Exception as e:
                logger.debug(f"Invaluable: failed to parse API item: {e}")

        return results if results else None

    def _parse_api_item(self, item):
        """Parse a single item from the JSON API response."""
        data = {
            "auction_house": item.get("houseName", item.get("auctionHouse", "Unknown")),
        }

        # Artist
        artist = item.get("artistName", item.get("artist", ""))
        if not artist:
            # Sometimes embedded in the title
            title = item.get("title", item.get("lotTitle", ""))
            data["title"] = title
            data["artist_name"] = self._extract_artist_from_title(title)
        else:
            data["artist_name"] = artist
            data["title"] = item.get("title", item.get("lotTitle", ""))

        if not data.get("artist_name"):
            return None

        # Price
        price = item.get("salePrice", item.get("priceRealized", item.get("hammerPrice")))
        if price is not None:
            data["hammer_price"] = float(price)
        else:
            return None

        data["currency"] = item.get("currency", "USD")

        # Estimates
        data["estimate_low"] = item.get("estimateLow", item.get("lowEstimate"))
        data["estimate_high"] = item.get("estimateHigh", item.get("highEstimate"))
        if data["estimate_low"]:
            data["estimate_low"] = float(data["estimate_low"])
        if data["estimate_high"]:
            data["estimate_high"] = float(data["estimate_high"])

        # Date
        sale_date = item.get("saleDate", item.get("auctionDate", ""))
        if sale_date:
            data["sale_date"] = sale_date[:10]  # YYYY-MM-DD from ISO

        # Metadata
        data["lot_number"] = str(item.get("lotNumber", ""))
        data["medium"] = item.get("medium", item.get("description", ""))[:200]
        data["dimensions"] = item.get("dimensions", "")

        # URLs
        lot_url = item.get("lotUrl", item.get("url", ""))
        if lot_url and not lot_url.startswith("http"):
            lot_url = f"https://www.invaluable.com{lot_url}"
        data["sale_url"] = lot_url

        data["image_url"] = item.get("imageUrl", item.get("image", ""))

        # Source ID for dedup
        lot_id = item.get("lotId", item.get("id", ""))
        data["source_id"] = f"invaluable-{lot_id}" if lot_id else None

        data["sold"] = 1 if data["hammer_price"] > 0 else 0

        return data

    def _try_html(self, query, page):
        """Fall back to HTML scraping if API fails."""
        from bs4 import BeautifulSoup

        url = f"{self.base_url}/auction-lot/search"
        params = {
            "query": query or "contemporary art",
            "upcoming": "false",
            "salePriceRange": "0-5000",
            "page": str(page),
        }

        resp = self.fetch(url, params=params)
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        lot_cards = soup.select(
            ".lot-card, .search-result, [data-lot-id], .lot-item"
        )

        for card in lot_cards:
            try:
                result = self._parse_html_card(card)
                if result:
                    results.append(result)
            except Exception as e:
                logger.debug(f"Invaluable HTML parse error: {e}")

        return results if results else None

    def _parse_html_card(self, card):
        """Parse a lot card from HTML."""
        data = {"auction_house": "Unknown"}

        # Title/artist
        title_el = card.select_one(
            ".lot-title, .lot-name, h3 a, h4 a, [data-testid='lot-title']"
        )
        if title_el:
            full = title_el.get_text(strip=True)
            data["artist_name"] = self._extract_artist_from_title(full)
            data["title"] = full
            href = title_el.get("href", "")
            if href:
                data["sale_url"] = (
                    href if href.startswith("http")
                    else f"https://www.invaluable.com{href}"
                )

        # Auction house
        house_el = card.select_one(
            ".auction-house, .house-name, [data-testid='house-name']"
        )
        if house_el:
            data["auction_house"] = house_el.get_text(strip=True)

        # Price
        price_el = card.select_one(
            ".price-realized, .sale-price, .realized-price, [data-testid='price']"
        )
        if price_el:
            text = price_el.get_text(strip=True)
            data["hammer_price"] = self.parse_price(text)
            data["currency"] = self.detect_currency(text)

        # Date
        date_el = card.select_one(".sale-date, .date, time")
        if date_el:
            data["sale_date"] = date_el.get("datetime", date_el.get_text(strip=True))

        # Image
        img = card.select_one("img")
        if img:
            data["image_url"] = img.get("src", "") or img.get("data-src", "")

        # Source ID
        lot_id = card.get("data-lot-id", "")
        data["source_id"] = f"invaluable-{lot_id}" if lot_id else None

        return data if data.get("artist_name") and data.get("hammer_price") else None

    def _extract_artist_from_title(self, title):
        """Try to extract artist name from a lot title string."""
        if not title:
            return None
        # Common pattern: "Artist Name (Nationality, Born-Died)"
        paren_match = re.match(r"^([^(]+)\(", title)
        if paren_match:
            return paren_match.group(1).strip()
        # "Artist Name - Title"
        if " - " in title:
            return title.split(" - ", 1)[0].strip()
        # "Artist Name, Title"
        if ", " in title:
            parts = title.split(", ")
            if len(parts) >= 2 and len(parts[0].split()) <= 4:
                return parts[0].strip()
        return None


def scrape_invaluable(query=None, max_pages=5):
    """Convenience function to run the Invaluable scraper."""
    scraper = InvaluableScraper()
    return scraper.scrape_and_filter(query=query, max_pages=max_pages)
