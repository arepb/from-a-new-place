"""Heritage Auctions scraper.

Heritage (ha.com) is one of the largest US auction houses, strong in
illustration art, prints, photography, and emerging contemporary.
Their past results are publicly browsable.

Uses Playwright for JS-rendered content.
"""

import re
import logging
from datetime import datetime
from .base import BaseScraper

logger = logging.getLogger(__name__)


class HeritageScraper(BaseScraper):
    name = "heritage"
    base_url = "https://fineart.ha.com"
    min_delay = 3.0
    max_delay = 6.0

    # Heritage fine art category search — past auction results
    SEARCH_URL = "https://fineart.ha.com/c/search-results.zx"

    # Default search params for sold fine art lots
    DEFAULT_PARAMS = {
        "N": "790+231",  # Fine art, sold lots
        "Nty": "0",
        "type": "surl-sold",
    }

    def scrape(self, query=None, max_pages=5):
        """Scrape Heritage Auctions past results.

        Due to Heritage's JS-heavy rendering, this scraper works best
        with Playwright. Falls back to requests+BS4 for basic data.
        """
        results = []

        for page in range(max_pages):
            params = dict(self.DEFAULT_PARAMS)
            params["No"] = str(page * 28)  # Heritage uses 28 results per page

            if query:
                params["Ntk"] = "SI_Titles"
                params["Ntt"] = query

            resp = self.fetch(self.SEARCH_URL, params=params)
            if not resp:
                break

            page_results = self._parse_search_page(resp.text)
            if not page_results:
                break

            results.extend(page_results)
            logger.info(
                f"Heritage page {page+1}: found {len(page_results)} results"
            )

        self.results_found = len(results)
        return results

    def _parse_search_page(self, html):
        """Parse a Heritage search results page."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        results = []

        # Heritage uses various container classes for lot cards
        lot_cards = soup.select(".search-result-item, .lot-card, [data-lot-id]")

        # Fallback: look for price-bearing containers
        if not lot_cards:
            lot_cards = soup.find_all("div", class_=re.compile(r"lot|result|item"))

        for card in lot_cards:
            try:
                result = self._parse_lot_card(card)
                if result and result.get("hammer_price"):
                    results.append(result)
            except Exception as e:
                logger.debug(f"Heritage: failed to parse lot card: {e}")

        return results

    def _parse_lot_card(self, card):
        """Extract data from a single lot card element."""
        data = {
            "auction_house": "Heritage Auctions",
            "currency": "USD",
        }

        # Title and artist — Heritage typically has "Artist Name - Title"
        title_el = card.select_one(
            ".lot-title, .search-result-title, a[href*='/a/']"
        )
        if title_el:
            full_title = title_el.get_text(strip=True)
            data["sale_url"] = title_el.get("href", "")
            if data["sale_url"] and not data["sale_url"].startswith("http"):
                data["sale_url"] = f"https://fineart.ha.com{data['sale_url']}"

            # Try to split "Artist Name - Title, Date"
            if " - " in full_title:
                parts = full_title.split(" - ", 1)
                data["artist_name"] = parts[0].strip()
                data["title"] = parts[1].strip()
            else:
                data["artist_name"] = full_title
                data["title"] = full_title

        # Extract lot ID for dedup
        lot_id = card.get("data-lot-id", "")
        if not lot_id and data.get("sale_url"):
            match = re.search(r"/a/(\d+)", data.get("sale_url", ""))
            if match:
                lot_id = match.group(1)
        data["source_id"] = f"heritage-{lot_id}" if lot_id else None

        # Price realized
        price_el = card.select_one(
            ".price-realized, .search-result-price, .lot-price"
        )
        if price_el:
            price_text = price_el.get_text(strip=True)
            data["hammer_price"] = self.parse_price(price_text)
            data["currency"] = self.detect_currency(price_text)

        # Estimate
        est_el = card.select_one(".estimate, .lot-estimate")
        if est_el:
            est_text = est_el.get_text(strip=True)
            est_match = re.findall(r"[\d,]+", est_text)
            if len(est_match) >= 2:
                data["estimate_low"] = float(est_match[0].replace(",", ""))
                data["estimate_high"] = float(est_match[1].replace(",", ""))

        # Sale date
        date_el = card.select_one(".sale-date, .lot-date, time")
        if date_el:
            date_text = date_el.get("datetime", "") or date_el.get_text(strip=True)
            data["sale_date"] = self._parse_date(date_text)

        # Lot number
        lot_el = card.select_one(".lot-number, .lot-num")
        if lot_el:
            data["lot_number"] = lot_el.get_text(strip=True)

        # Image
        img_el = card.select_one("img")
        if img_el:
            data["image_url"] = img_el.get("src", "") or img_el.get("data-src", "")

        # Medium/description
        desc_el = card.select_one(".lot-description, .medium")
        if desc_el:
            data["medium"] = desc_el.get_text(strip=True)[:200]

        return data if data.get("artist_name") else None

    def _parse_date(self, date_str):
        """Try to parse various date formats into YYYY-MM-DD."""
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None


def scrape_heritage(query=None, max_pages=5):
    """Convenience function to run the Heritage scraper."""
    scraper = HeritageScraper()
    return scraper.scrape_and_filter(query=query, max_pages=max_pages)
