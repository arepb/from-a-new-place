#!/usr/bin/env python3
"""Update script — scrape new auction data, discover artists, re-score, and deploy.

Run this biweekly to keep the site fresh:
    python update.py

It will:
1. Discover new emerging artists from Artsy (targeting 250+ total)
2. Scrape latest auction results for all tracked artists
3. Scan editorial feeds for signals
4. Re-compute Heat Index scores
5. Commit and push to GitHub (auto-deploys on Render)
"""

import sys
import os
import subprocess
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("update")


def run():
    from database import init_db, get_db, find_or_create_artist
    from scraper.artsy import fetch_all_artists
    from scraper.discover import run_discovery
    from analysis.heat_index import score_all_artists, save_scores

    init_db()
    now = datetime.now().strftime("%Y-%m-%d")

    # --- Step 1: Discover new artists ---
    logger.info("=" * 60)
    logger.info("STEP 1: Discovering new artists")
    logger.info("=" * 60)

    with get_db() as db:
        before = db.execute("SELECT COUNT(*) as c FROM artists").fetchone()["c"]
        # Grow the artist pool — increase target over time
        target = max(before + 20, 250)
        added = run_discovery(db, target_count=target)
        after = db.execute("SELECT COUNT(*) as c FROM artists").fetchone()["c"]

    logger.info(f"Artists: {before} → {after} (+{added} new)")

    # --- Step 2: Scrape auction results ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 2: Scraping auction results from Artsy")
    logger.info("=" * 60)

    with get_db() as db:
        rows = db.execute("SELECT name FROM artists ORDER BY name").fetchall()
        artist_names = [r["name"] for r in rows]

        results_before = db.execute(
            "SELECT COUNT(*) as c FROM auction_results"
        ).fetchone()["c"]

    logger.info(f"Fetching results for {len(artist_names)} artists...")
    fetch_data = fetch_all_artists(artist_names, max_results_per=50, delay=1.0)
    results = fetch_data["results"]
    artist_info_list = fetch_data["artist_info"]

    new_count = 0
    with get_db() as db:
        # Update artist portraits
        for ai in artist_info_list:
            if ai.get("image_url"):
                db.execute(
                    "UPDATE artists SET image_url = ? WHERE name = ?",
                    (ai["image_url"], ai["name"]),
                )

        for r in results:
            artist_name = r.pop("artist_name")
            artist_id = find_or_create_artist(
                db, artist_name,
                first_seen_date=now,
                first_seen_source="artsy",
            )
            from database import insert_auction_result
            if insert_auction_result(db, artist_id, **r):
                new_count += 1

        results_after = db.execute(
            "SELECT COUNT(*) as c FROM auction_results"
        ).fetchone()["c"]

    logger.info(f"Artsy results: {results_before} → {results_after} (+{new_count} new)")

    # --- Step 3: Scan editorial signals ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 3: Scanning editorial feeds")
    logger.info("=" * 60)

    try:
        from scraper.signals import scan_editorial_feeds

        with get_db() as db:
            rows = db.execute("SELECT id, name FROM artists").fetchall()
            artist_names = [r["name"] for r in rows]
            name_to_id = {r["name"]: r["id"] for r in rows}

        found_signals = scan_editorial_feeds(artist_names)
        sig_count = 0

        with get_db() as db:
            for sig in found_signals:
                artist_id = name_to_id.get(sig["artist_name"])
                if not artist_id:
                    continue
                db.execute(
                    """INSERT INTO price_signals
                       (artist_id, signal_type, signal_date, source, details, url)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (artist_id, sig["signal_type"], sig["signal_date"],
                     sig["source"], sig["details"], sig.get("url", "")),
                )
                sig_count += 1

        logger.info(f"Signals: {len(found_signals)} found, {sig_count} saved")
    except Exception as e:
        logger.warning(f"Signal scan failed (non-critical): {e}")

    # --- Step 4: Re-score all artists ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 4: Computing Heat Index scores")
    logger.info("=" * 60)

    with get_db() as db:
        scores = score_all_artists(db, min_sales=2)
        if scores:
            save_scores(db, scores)
            logger.info(f"Scored {len(scores)} artists")
            logger.info(f"Top 5:")
            for s in scores[:5]:
                logger.info(
                    f"  {s['artist_name']}: {s['composite_score']:.3f} "
                    f"({s['num_sales']} sales)"
                )
        else:
            logger.warning("No artists had enough data to score")

    # --- Step 5: Git commit & push ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 5: Deploying to Render")
    logger.info("=" * 60)

    project_dir = os.path.dirname(__file__)
    try:
        subprocess.run(
            ["git", "add", "artscope.db"],
            cwd=project_dir, check=True,
        )

        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=project_dir,
        )

        if result.returncode != 0:
            msg = f"Data update {now}: {after} artists, {results_after} results, {len(scores)} scored"
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=project_dir, check=True,
            )
            subprocess.run(
                ["git", "push"],
                cwd=project_dir, check=True,
            )
            logger.info("Pushed to GitHub → Render will auto-deploy")
        else:
            logger.info("No new data to deploy")

    except subprocess.CalledProcessError as e:
        logger.error(f"Git operation failed: {e}")
        logger.info("You can manually push with: git add artscope.db && git commit -m 'data update' && git push")

    # --- Summary ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("UPDATE COMPLETE")
    logger.info(f"  Artists:  {after}")
    logger.info(f"  Results:  {results_after}")
    logger.info(f"  Scored:   {len(scores)}")
    logger.info("=" * 60)


if __name__ == "__main__":
    run()
