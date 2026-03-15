"""Base scraper with rate limiting, retries, and user-agent rotation."""

import time
import random
import logging
import requests
from abc import ABC, abstractmethod
from datetime import datetime

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

# Approximate exchange rates — updated periodically, good enough for trend analysis
EXCHANGE_RATES_TO_USD = {
    "USD": 1.0,
    "EUR": 1.09,
    "GBP": 1.27,
    "CHF": 1.13,
    "SEK": 0.096,
    "NOK": 0.094,
    "DKK": 0.146,
    "CAD": 0.74,
    "AUD": 0.65,
    "JPY": 0.0067,
    "CNY": 0.14,
    "HKD": 0.13,
    "KRW": 0.00075,
}


def to_usd(amount, currency):
    """Convert an amount to USD using approximate rates."""
    if amount is None:
        return None
    currency = currency.upper().strip()
    rate = EXCHANGE_RATES_TO_USD.get(currency)
    if rate is None:
        logger.warning(f"Unknown currency: {currency}, treating as USD")
        return amount
    return round(amount * rate, 2)


class BaseScraper(ABC):
    """Base class for all auction scrapers."""

    name = "base"
    base_url = ""
    min_delay = 2.0  # minimum seconds between requests
    max_delay = 5.0
    max_retries = 3
    max_price_usd = 5000  # filter ceiling

    def __init__(self):
        self.session = requests.Session()
        self._rotate_ua()
        self.results_found = 0
        self.results_new = 0

    def _rotate_ua(self):
        self.session.headers["User-Agent"] = random.choice(USER_AGENTS)

    def _delay(self):
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def fetch(self, url, params=None, method="GET"):
        """Fetch a URL with retries and rate limiting."""
        for attempt in range(self.max_retries):
            try:
                self._rotate_ua()
                if method == "GET":
                    resp = self.session.get(url, params=params, timeout=30)
                else:
                    resp = self.session.post(url, data=params, timeout=30)

                if resp.status_code == 429:
                    wait = (attempt + 1) * 10
                    logger.warning(f"Rate limited on {self.name}, waiting {wait}s")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                self._delay()
                return resp

            except requests.RequestException as e:
                logger.warning(
                    f"{self.name} attempt {attempt+1}/{self.max_retries} failed: {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep((attempt + 1) * 3)

        logger.error(f"{self.name}: all {self.max_retries} attempts failed for {url}")
        return None

    def parse_price(self, price_str):
        """Extract numeric price from a string like '$1,234' or '€2.500'."""
        if not price_str:
            return None
        cleaned = price_str.replace(",", "").replace(".", "")
        # Handle European format where . is thousands separator
        # If original has both . and , assume . is thousands
        digits = ""
        for ch in price_str:
            if ch.isdigit() or ch == ".":
                digits += ch
        try:
            return float(digits) if digits else None
        except ValueError:
            return None

    def detect_currency(self, text):
        """Detect currency from price text."""
        if not text:
            return "USD"
        text = text.strip()
        if text.startswith("$") or "USD" in text:
            return "USD"
        if text.startswith("€") or "EUR" in text:
            return "EUR"
        if text.startswith("£") or "GBP" in text:
            return "GBP"
        if "CHF" in text:
            return "CHF"
        if "SEK" in text:
            return "SEK"
        if "DKK" in text:
            return "DKK"
        if "NOK" in text:
            return "NOK"
        if "CA$" in text or "CAD" in text:
            return "CAD"
        if "A$" in text or "AUD" in text:
            return "AUD"
        if "¥" in text or "JPY" in text:
            return "JPY"
        return "USD"

    @abstractmethod
    def scrape(self, query=None, max_pages=5):
        """
        Scrape auction results. Returns list of dicts with keys:
        - artist_name (str)
        - title (str)
        - medium (str, optional)
        - dimensions (str, optional)
        - sale_date (str, YYYY-MM-DD)
        - auction_house (str)
        - lot_number (str, optional)
        - estimate_low (float, optional)
        - estimate_high (float, optional)
        - hammer_price (float)
        - currency (str)
        - sale_url (str, optional)
        - image_url (str, optional)
        - source_id (str) — unique identifier from the source
        """
        pass

    def scrape_and_filter(self, query=None, max_pages=5):
        """Scrape and filter to sub-$5K results only."""
        results = self.scrape(query=query, max_pages=max_pages)
        filtered = []
        for r in results:
            price_usd = to_usd(r.get("hammer_price"), r.get("currency", "USD"))
            if price_usd is not None and price_usd <= self.max_price_usd:
                r["hammer_price_usd"] = price_usd
                filtered.append(r)
        logger.info(
            f"{self.name}: {len(results)} total results, {len(filtered)} under ${self.max_price_usd}"
        )
        return filtered
