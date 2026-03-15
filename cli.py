#!/usr/bin/env python3
"""ArtScope CLI — command-line interface for the emerging artist tracker."""

import sys
import os
import logging
import click
from tabulate import tabulate
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, get_db, find_or_create_artist, insert_auction_result

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("artscope")


@click.group()
def cli():
    """ArtScope — Spot emerging artists before the market does."""
    pass


@cli.command()
def setup():
    """Initialize the database."""
    init_db()
    click.echo("Database ready.")


@cli.command()
@click.option("--source", type=click.Choice(["artsy", "liveauctioneers", "heritage", "invaluable", "all"]), default="artsy")
@click.option("--query", "-q", default=None, help="Search query (e.g. 'contemporary painting')")
@click.option("--pages", "-p", default=5, help="Max pages to scrape per source")
@click.option("--max-results", default=50, help="Max results per artist (Artsy)")
def scrape(source, query, pages, max_results):
    """Run auction scrapers to collect price data."""
    init_db()

    total_new = 0

    # Artsy GraphQL API — primary source (no bot detection)
    if source in ("artsy", "all"):
        click.echo("\nScraping Artsy (GraphQL API)...")
        from scraper.artsy import fetch_all_artists

        with get_db() as db:
            rows = db.execute("SELECT name FROM artists ORDER BY name").fetchall()
            artist_names = [r["name"] for r in rows]

            cursor = db.execute(
                "INSERT INTO scrape_log (source) VALUES (?)", ("artsy",)
            )
            log_id = cursor.lastrowid

        if not artist_names:
            click.echo("  No artists in database. Run seed_artists.py first.")
        else:
            click.echo(f"  Fetching results for {len(artist_names)} artists...")
            fetch_data = fetch_all_artists(artist_names, max_results_per=max_results)
            results = fetch_data["results"]
            artist_info_list = fetch_data["artist_info"]
            new_count = 0

            with get_db() as db:
                # Save artist portrait images
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
                        first_seen_date=datetime.now().strftime("%Y-%m-%d"),
                        first_seen_source="artsy",
                    )
                    if insert_auction_result(db, artist_id, **r):
                        new_count += 1

                db.execute(
                    """UPDATE scrape_log SET finished_at = datetime('now'),
                       status = 'complete', records_found = ?, records_new = ?
                       WHERE id = ?""",
                    (len(results), new_count, log_id),
                )

            total_new += new_count
            click.echo(f"  Artsy: {len(results)} results, {new_count} new records")

    # LiveAuctioneers — secondary source (page scraping)
    if source in ("liveauctioneers", "all"):
        click.echo("\nScraping LiveAuctioneers...")
        from scraper.liveauctioneers import fetch_all_artists as la_fetch_all

        with get_db() as db:
            rows = db.execute("SELECT name FROM artists ORDER BY name").fetchall()
            artist_names = [r["name"] for r in rows]

            cursor = db.execute(
                "INSERT INTO scrape_log (source) VALUES (?)", ("liveauctioneers",)
            )
            log_id = cursor.lastrowid

        if artist_names:
            click.echo(f"  Fetching results for {len(artist_names)} artists...")
            la_data = la_fetch_all(artist_names, max_results_per=max_results)
            la_results = la_data["results"]
            new_count = 0

            with get_db() as db:
                for r in la_results:
                    artist_name = r.pop("artist_name")
                    artist_id = find_or_create_artist(
                        db, artist_name,
                        first_seen_date=datetime.now().strftime("%Y-%m-%d"),
                        first_seen_source="liveauctioneers",
                    )
                    if insert_auction_result(db, artist_id, **r):
                        new_count += 1

                db.execute(
                    """UPDATE scrape_log SET finished_at = datetime('now'),
                       status = 'complete', records_found = ?, records_new = ?
                       WHERE id = ?""",
                    (len(la_results), new_count, log_id),
                )

            total_new += new_count
            click.echo(f"  LiveAuctioneers: {len(la_results)} results, {new_count} new records")

    # Heritage and Invaluable scrapers (may be blocked by bot detection)
    page_scrapers = []
    if source in ("heritage", "all"):
        from scraper.heritage import HeritageScraper
        page_scrapers.append(HeritageScraper())
    if source in ("invaluable", "all"):
        from scraper.invaluable import InvaluableScraper
        page_scrapers.append(InvaluableScraper())

    for scraper_inst in page_scrapers:
        click.echo(f"\nScraping {scraper_inst.name}...")

        with get_db() as db:
            cursor = db.execute(
                "INSERT INTO scrape_log (source) VALUES (?)", (scraper_inst.name,)
            )
            log_id = cursor.lastrowid

        results = scraper_inst.scrape_and_filter(query=query, max_pages=pages)
        new_count = 0

        with get_db() as db:
            for r in results:
                artist_name = r.pop("artist_name", None)
                if not artist_name:
                    continue

                artist_id = find_or_create_artist(
                    db, artist_name,
                    first_seen_date=datetime.now().strftime("%Y-%m-%d"),
                    first_seen_source=scraper_inst.name,
                )

                was_new = insert_auction_result(db, artist_id, **r)
                if was_new:
                    new_count += 1

            db.execute(
                """UPDATE scrape_log SET finished_at = datetime('now'),
                   status = 'complete', records_found = ?, records_new = ?
                   WHERE id = ?""",
                (len(results), new_count, log_id),
            )

        total_new += new_count
        click.echo(f"  {scraper_inst.name}: {len(results)} results, {new_count} new records")

    click.echo(f"\nDone. {total_new} new records added total.")


@cli.command()
@click.option("--query", "-q", default=None, help="Search query")
@click.option("--pages", "-p", default=3, help="Max pages")
def signals(query, pages):
    """Scan editorial feeds for artist mentions."""
    init_db()

    with get_db() as db:
        # Get all tracked artist names
        rows = db.execute("SELECT id, name FROM artists").fetchall()
        if not rows:
            click.echo("No artists in database yet. Run 'scrape' first.")
            return

        artist_names = [r["name"] for r in rows]
        name_to_id = {r["name"]: r["id"] for r in rows}

    click.echo(f"Scanning editorial feeds for {len(artist_names)} artists...")

    from scraper.signals import scan_editorial_feeds
    found_signals = scan_editorial_feeds(artist_names)

    new_count = 0
    with get_db() as db:
        for sig in found_signals:
            artist_id = name_to_id.get(sig["artist_name"])
            if not artist_id:
                continue
            db.execute(
                """INSERT INTO price_signals (artist_id, signal_type, signal_date, source, details, url)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (artist_id, sig["signal_type"], sig["signal_date"], sig["source"], sig["details"], sig.get("url", "")),
            )
            new_count += 1

    click.echo(f"Found {len(found_signals)} mentions, saved {new_count} signals.")


@cli.command()
@click.option("--min-sales", default=3, help="Minimum sales to be scored")
def score(min_sales):
    """Compute Heat Index scores for all artists with enough data."""
    init_db()

    from analysis.heat_index import score_all_artists, save_scores

    with get_db() as db:
        scores = score_all_artists(db, min_sales=min_sales)
        if not scores:
            click.echo("Not enough data to score. Need more auction results.")
            return

        save_scores(db, scores)

    click.echo(f"\nScored {len(scores)} artists.\n")

    # Show top 20
    table_data = []
    for s in scores[:20]:
        table_data.append([
            s["artist_name"],
            f"{s['composite_score']:.3f}",
            s["num_sales"],
            f"{s['price_velocity']:.2f}",
            f"{s['sell_through_rate']:.2f}",
            f"{s['estimate_beat_rate']:.2f}",
        ])

    headers = ["Artist", "Heat Index", "Sales", "Price Vel.", "Sell-Thru", "Est. Beat"]
    click.echo(tabulate(table_data, headers=headers, tablefmt="simple"))


@cli.command()
@click.option("--limit", "-n", default=20, help="Number of results")
@click.option("--sort", type=click.Choice(["score", "price", "sales", "recent"]), default="score")
def leaderboard(limit, sort):
    """Show the current artist leaderboard."""
    init_db()

    order_clause = {
        "score": "ts.composite_score DESC",
        "price": "avg_price DESC",
        "sales": "sale_count DESC",
        "recent": "latest_sale DESC",
    }[sort]

    with get_db() as db:
        rows = db.execute(f"""
            SELECT a.name, a.nationality, a.medium,
                   COUNT(ar.id) as sale_count,
                   ROUND(AVG(ar.hammer_price_usd), 0) as avg_price,
                   ROUND(MIN(ar.hammer_price_usd), 0) as min_price,
                   ROUND(MAX(ar.hammer_price_usd), 0) as max_price,
                   MAX(ar.sale_date) as latest_sale,
                   COALESCE(ts.composite_score, 0) as heat_score
            FROM artists a
            JOIN auction_results ar ON ar.artist_id = a.id
            LEFT JOIN trend_scores ts ON ts.artist_id = a.id
            WHERE ar.sold = 1 AND ar.hammer_price_usd <= 5000
            GROUP BY a.id
            HAVING sale_count >= 2
            ORDER BY {order_clause}
            LIMIT ?
        """, (limit,)).fetchall()

    if not rows:
        click.echo("No data yet. Run 'scrape' first.")
        return

    table_data = []
    for r in rows:
        table_data.append([
            r["name"][:30],
            f"{r['heat_score']:.3f}" if r["heat_score"] else "—",
            r["sale_count"],
            f"${r['avg_price']:,.0f}" if r["avg_price"] else "—",
            f"${r['min_price']:,.0f}–${r['max_price']:,.0f}" if r["min_price"] else "—",
            r["latest_sale"] or "—",
        ])

    headers = ["Artist", "Heat", "Sales", "Avg Price", "Range", "Last Sale"]
    click.echo(f"\n{'='*80}")
    click.echo(f"  ARTSCOPE LEADERBOARD — sorted by {sort}")
    click.echo(f"{'='*80}\n")
    click.echo(tabulate(table_data, headers=headers, tablefmt="simple"))


@cli.command()
@click.argument("artist_name")
def artist(artist_name):
    """Show detailed info and price history for an artist."""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM artists WHERE LOWER(name) LIKE ?",
            (f"%{artist_name.lower()}%",),
        ).fetchone()

        if not row:
            click.echo(f"No artist found matching '{artist_name}'")
            return

        click.echo(f"\n{'='*60}")
        click.echo(f"  {row['name']}")
        click.echo(f"{'='*60}")
        if row["nationality"]:
            click.echo(f"  Nationality: {row['nationality']}")
        if row["birth_year"]:
            click.echo(f"  Born: {row['birth_year']}")
        if row["medium"]:
            click.echo(f"  Medium: {row['medium']}")
        click.echo(f"  First tracked: {row['first_seen_date']} via {row['first_seen_source']}")

        # Auction results
        results = db.execute(
            """SELECT * FROM auction_results
               WHERE artist_id = ? AND sold = 1
               ORDER BY sale_date DESC""",
            (row["id"],),
        ).fetchall()

        if results:
            click.echo(f"\n  Auction Results ({len(results)} sales):")
            click.echo(f"  {'-'*56}")
            table = []
            for r in results:
                table.append([
                    r["sale_date"] or "—",
                    r["auction_house"][:20] if r["auction_house"] else "—",
                    (r["title"] or "Untitled")[:30],
                    f"${r['hammer_price_usd']:,.0f}" if r["hammer_price_usd"] else "—",
                ])
            click.echo(tabulate(table, headers=["Date", "House", "Title", "Price (USD)"], tablefmt="simple"))

        # Signals
        sigs = db.execute(
            "SELECT * FROM price_signals WHERE artist_id = ? ORDER BY signal_date DESC",
            (row["id"],),
        ).fetchall()

        if sigs:
            click.echo(f"\n  Signals ({len(sigs)}):")
            for s in sigs:
                click.echo(f"    [{s['signal_date']}] {s['source']}: {s['details'][:60]}")

        # Current score
        score = db.execute(
            "SELECT * FROM trend_scores WHERE artist_id = ? ORDER BY period DESC LIMIT 1",
            (row["id"],),
        ).fetchone()

        if score:
            click.echo(f"\n  Heat Index: {score['composite_score']:.3f}")


@cli.command()
def stats():
    """Show database statistics."""
    with get_db() as db:
        artists = db.execute("SELECT COUNT(*) as c FROM artists").fetchone()["c"]
        results = db.execute("SELECT COUNT(*) as c FROM auction_results").fetchone()["c"]
        sold = db.execute("SELECT COUNT(*) as c FROM auction_results WHERE sold = 1").fetchone()["c"]
        signals = db.execute("SELECT COUNT(*) as c FROM price_signals").fetchone()["c"]
        houses = db.execute("SELECT COUNT(DISTINCT auction_house) as c FROM auction_results").fetchone()["c"]

        avg_price = db.execute(
            "SELECT ROUND(AVG(hammer_price_usd), 0) as avg FROM auction_results WHERE sold = 1 AND hammer_price_usd <= 5000"
        ).fetchone()["avg"]

        click.echo(f"\n  ArtScope Database Stats")
        click.echo(f"  {'='*40}")
        click.echo(f"  Artists tracked:     {artists:,}")
        click.echo(f"  Auction results:     {results:,}")
        click.echo(f"  Sold lots:           {sold:,}")
        click.echo(f"  Auction houses:      {houses:,}")
        click.echo(f"  Price signals:       {signals:,}")
        click.echo(f"  Avg price (sold):    ${avg_price:,.0f}" if avg_price else "  Avg price: —")


if __name__ == "__main__":
    cli()
