#!/usr/bin/env python3
"""Extract dominant color palettes from artist artwork thumbnails.

For each artist, samples up to 20 artwork images, stitches them together,
and uses PIL's median-cut quantization to find the 5 most dominant colors.
Stores results in the artist_colors table.
"""

import sys
import os
import io
import re
import time
import logging
from collections import Counter

import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import get_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("extract_colors")

HEADERS = {"User-Agent": "FromANewPlace/1.0 (art tracker)"}
SAMPLE_SIZE = 20  # Max artworks to sample per artist
IMG_SIZE = 100    # Download size for each thumbnail


def resize_cdn_url(url, size=IMG_SIZE):
    """Resize an Artsy CDN URL to the desired dimensions."""
    url = re.sub(r'height=\d+', f'height={size}', url)
    url = re.sub(r'width=\d+', f'width={size}', url)
    return url


def is_near_white(r, g, b, threshold=235):
    return r > threshold and g > threshold and b > threshold


def is_near_black(r, g, b, threshold=20):
    return r < threshold and g < threshold and b < threshold


def is_near_gray(r, g, b, threshold=15):
    """Check if a color is a neutral gray (all channels close together, mid-range)."""
    avg = (r + g + b) / 3
    return (abs(r - avg) < threshold and abs(g - avg) < threshold and
            abs(b - avg) < threshold and 30 < avg < 200)


def extract_palette(images, num_colors=8):
    """Extract dominant colors from a list of PIL images.

    Quantizes to more colors than needed, then filters out
    backgrounds (white, black, gray) and returns top 5.
    """
    if not images:
        return []

    # Stitch images into a composite
    total_width = sum(img.width for img in images)
    max_height = max(img.height for img in images)
    composite = Image.new("RGB", (total_width, max_height))
    x_offset = 0
    for img in images:
        composite.paste(img, (x_offset, 0))
        x_offset += img.width

    # Quantize to find dominant colors
    # Use more colors than we need so we can filter backgrounds
    quantized = composite.quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
    palette_data = quantized.getpalette()
    pixels = list(quantized.getdata())
    total_pixels = len(pixels)

    if not palette_data or total_pixels == 0:
        return []

    # Count pixels per color index
    counts = Counter(pixels)

    # Build color list with percentages
    colors = []
    for idx, count in counts.most_common():
        r = palette_data[idx * 3]
        g = palette_data[idx * 3 + 1]
        b = palette_data[idx * 3 + 2]
        pct = count / total_pixels

        # Filter out backgrounds
        if is_near_white(r, g, b):
            continue
        if is_near_black(r, g, b):
            continue
        if is_near_gray(r, g, b) and pct < 0.3:
            # Allow gray only if it's very dominant (e.g., pencil drawings)
            continue

        hex_color = f"#{r:02X}{g:02X}{b:02X}"
        colors.append((hex_color, pct))

    # Normalize percentages for remaining colors
    if colors:
        total_pct = sum(c[1] for c in colors)
        colors = [(hex_c, pct / total_pct) for hex_c, pct in colors]

    return colors[:5]


def extract_all(force=False):
    """Extract color palettes for all artists."""
    with get_db() as db:
        # Get artists and check which already have colors
        if force:
            artists = db.execute("""
                SELECT id, name FROM artists ORDER BY name
            """).fetchall()
        else:
            artists = db.execute("""
                SELECT a.id, a.name FROM artists a
                WHERE a.id NOT IN (SELECT DISTINCT artist_id FROM artist_colors)
                ORDER BY a.name
            """).fetchall()

    logger.info(f"Processing {len(artists)} artists")
    updated = 0
    skipped = 0

    for i, artist in enumerate(artists):
        logger.info(f"[{i+1}/{len(artists)}] {artist['name']}")

        # Get artwork image URLs, spread across sale dates
        with get_db() as db:
            total_artworks = db.execute("""
                SELECT COUNT(*) as c FROM auction_results
                WHERE artist_id = ? AND image_url IS NOT NULL AND image_url != ''
            """, (artist["id"],)).fetchone()["c"]

            if total_artworks == 0:
                logger.info(f"  No artwork images, skipping")
                skipped += 1
                continue

            # Sample evenly across the artist's works
            # Use NTILE-like approach: get every Nth result
            step = max(1, total_artworks // SAMPLE_SIZE)
            artworks = db.execute(f"""
                SELECT image_url FROM (
                    SELECT image_url, ROW_NUMBER() OVER (ORDER BY sale_date) as rn
                    FROM auction_results
                    WHERE artist_id = ? AND image_url IS NOT NULL AND image_url != ''
                )
                WHERE (rn - 1) % ? = 0
                LIMIT ?
            """, (artist["id"], step, SAMPLE_SIZE)).fetchall()

        # Download and process images
        images = []
        for artwork in artworks:
            url = resize_cdn_url(artwork["image_url"], IMG_SIZE)
            try:
                resp = requests.get(url, headers=HEADERS, timeout=10)
                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                images.append(img)
            except Exception as e:
                continue  # Skip failed downloads silently
            time.sleep(0.1)  # Be nice to CDN

        if not images:
            logger.info(f"  No images downloaded, skipping")
            skipped += 1
            continue

        # Extract palette
        colors = extract_palette(images)
        if not colors:
            logger.info(f"  No meaningful colors extracted")
            skipped += 1
            continue

        # Store in database
        with get_db() as db:
            for rank, (hex_color, pct) in enumerate(colors, 1):
                db.execute("""
                    INSERT OR REPLACE INTO artist_colors (artist_id, hex_color, percentage, rank)
                    VALUES (?, ?, ?, ?)
                """, (artist["id"], hex_color, round(pct, 4), rank))

        color_preview = " ".join(c[0] for c in colors)
        logger.info(f"  {len(colors)} colors: {color_preview}")
        updated += 1

    logger.info("")
    logger.info("=" * 50)
    logger.info("COLOR EXTRACTION COMPLETE")
    logger.info(f"  Artists processed: {len(artists)}")
    logger.info(f"  Palettes extracted: {updated}")
    logger.info(f"  Skipped: {skipped}")
    logger.info("=" * 50)


if __name__ == "__main__":
    force = "--force" in sys.argv
    if force:
        logger.info("Force mode: re-extracting all artists")
    extract_all(force=force)
