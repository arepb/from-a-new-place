#!/usr/bin/env python3
"""Fix estimate values that were stored in local currency instead of USD.

Re-fetches estimate display strings from Artsy's GraphQL API and re-parses
them using the updated _parse_estimate function that handles all currencies.
"""

import os
import sys
import re
import time
import random
import logging
import requests
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from scraper.artsy import _parse_estimate, slugify, ARTSY_API, HEADERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fix_estimates")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artscope.db")


def fix_all():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Get all artists
    artists = conn.execute(
        "SELECT id, name FROM artists ORDER BY name"
    ).fetchall()

    logger.info(f"Processing {len(artists)} artists")

    total_fixed = 0
    total_checked = 0

    for idx, artist in enumerate(artists):
        slug = slugify(artist["name"])

        # Fetch from Artsy
        query = """
        query($artistId: String!) {
          artist(id: $artistId) {
            auctionResultsConnection(first: 200, sort: DATE_DESC) {
              edges {
                node {
                  internalID
                  lotNumber
                  saleDate
                  estimate { display }
                  priceRealized { centsUSD }
                }
              }
            }
          }
        }
        """

        try:
            resp = requests.post(
                ARTSY_API,
                json={"query": query, "variables": {"artistId": slug}},
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"API error for {artist['name']}: {e}")
            time.sleep(1)
            continue

        artist_data = data.get("data", {}).get("artist")
        if not artist_data:
            continue

        edges = artist_data.get("auctionResultsConnection", {}).get("edges", [])
        artist_fixes = 0

        for edge in edges:
            node = edge["node"]
            est_display = (node.get("estimate") or {}).get("display", "")
            if not est_display:
                continue

            # Check if this is a non-USD estimate
            is_non_usd = any(
                marker in est_display
                for marker in ["£", "€", "ZAR", "HK$", "CN¥", "JPY", "¥", "S$",
                               "A$", "CA$", "NZ$", "CHF", "SEK", "NOK", "DKK",
                               "PLN", "INR", "₹", "KRW", "₩", "TWD", "NT$",
                               "MXN", "BRL", "R$", "TRY", "₺", "AED", "NGN", "₦"]
            )

            if not is_non_usd:
                continue

            # Re-parse with fixed function
            new_low, new_high = _parse_estimate(est_display)
            if new_low is None:
                continue

            # Build source_id to match
            sale_date = (node.get("saleDate") or "")[:10]
            lot_number = str(node.get("lotNumber", ""))
            source_id = f"artsy-{slug}-{sale_date}-{lot_number}"

            # Check current values
            existing = conn.execute(
                "SELECT id, estimate_low, estimate_high FROM auction_results WHERE source_id = ?",
                (source_id,),
            ).fetchone()

            if not existing:
                continue

            total_checked += 1

            # Check if estimates are significantly different (indicating they weren't converted)
            if existing["estimate_low"] and abs(existing["estimate_low"] - new_low) > 1:
                conn.execute(
                    "UPDATE auction_results SET estimate_low = ?, estimate_high = ? WHERE id = ?",
                    (new_low, new_high, existing["id"]),
                )
                artist_fixes += 1

        if artist_fixes > 0:
            conn.commit()
            total_fixed += artist_fixes
            logger.info(f"[{idx+1}/{len(artists)}] {artist['name']}: fixed {artist_fixes} estimates")
        elif (idx + 1) % 20 == 0:
            logger.info(f"[{idx+1}/{len(artists)}] progress...")

        time.sleep(0.4 + random.uniform(0, 0.3))

    conn.close()

    logger.info("")
    logger.info("=" * 50)
    logger.info("ESTIMATE FIX COMPLETE")
    logger.info(f"  Artists processed: {len(artists)}")
    logger.info(f"  Non-USD estimates checked: {total_checked}")
    logger.info(f"  Estimates fixed: {total_fixed}")
    logger.info("=" * 50)


if __name__ == "__main__":
    fix_all()
