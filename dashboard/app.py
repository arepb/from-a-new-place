#!/usr/bin/env python3
"""ArtScope Dashboard — Flask web app for viewing artist price trends."""

import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template, request, jsonify
import plotly
import plotly.graph_objects as go

from database import get_db, init_db

app = Flask(__name__)


@app.route("/")
def index():
    """Leaderboard page — top artists by Heat Index."""
    sort = request.args.get("sort", "score")
    medium_filter = request.args.get("medium", "all")
    price_min = request.args.get("price_min", 0, type=int)
    price_max = request.args.get("price_max", 0, type=int)
    page = request.args.get("page", 1, type=int)
    search_q = request.args.get("q", "").strip()
    per_page = 50

    order_map = {
        "score": "heat_score DESC",
        "price": "avg_price DESC",
        "sales": "sale_count DESC",
        "recent": "latest_sale DESC",
        "velocity": "heat_score DESC",
    }
    order = order_map.get(sort, "heat_score DESC")

    # Build dynamic WHERE clauses
    extra_clauses = []
    params = []

    if medium_filter != "all":
        extra_clauses.append("AND a.medium = ?")
        params.append(medium_filter)

    if search_q:
        extra_clauses.append("AND LOWER(a.name) LIKE ?")
        params.append(f"%{search_q.lower()}%")

    price_clause = "AND ar.hammer_price_usd > 0"
    if price_min > 0:
        price_clause += " AND ar.hammer_price_usd >= ?"
        params.append(price_min)
    if price_max > 0:
        price_clause += " AND ar.hammer_price_usd <= ?"
        params.append(price_max)

    medium_clause = " ".join(extra_clauses)

    with get_db() as db:
        # Get global price range for the scrubber
        price_bounds = db.execute("""
            SELECT ROUND(MIN(hammer_price_usd)) as global_min,
                   ROUND(MAX(hammer_price_usd)) as global_max
            FROM auction_results WHERE sold = 1 AND hammer_price_usd > 0
        """).fetchone()

        # Count total matching artists for pagination
        count_params = [p for p in params]  # copy
        total_matching = db.execute(f"""
            SELECT COUNT(*) as c FROM (
                SELECT a.id
                FROM artists a
                JOIN auction_results ar ON ar.artist_id = a.id
                WHERE ar.sold = 1 {price_clause}
                {medium_clause}
                GROUP BY a.id
                HAVING COUNT(ar.id) >= 2
            )
        """, count_params).fetchone()["c"]

        total_pages = max(1, (total_matching + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page

        artists = db.execute(f"""
            SELECT a.id, a.name, a.nationality, a.birth_year, a.medium, a.tags,
                   a.image_url, a.instagram_handle,
                   COUNT(ar.id) as sale_count,
                   ROUND(AVG(ar.hammer_price_usd), 0) as avg_price,
                   ROUND(MIN(ar.hammer_price_usd), 0) as min_price,
                   ROUND(MAX(ar.hammer_price_usd), 0) as max_price,
                   MAX(ar.sale_date) as latest_sale,
                   COUNT(DISTINCT ar.auction_house) as house_count,
                   COALESCE(ts.composite_score, 0) as heat_score,
                   COALESCE(ts.sell_through_rate, 0) as sell_through,
                   COALESCE(ts.estimate_beat_rate, 0) as est_beat,
                   COALESCE(ts_prev.composite_score, -1) as prev_heat_score,
                   (SELECT ar2.image_url FROM auction_results ar2
                    WHERE ar2.artist_id = a.id AND ar2.image_url IS NOT NULL AND ar2.image_url != ''
                    ORDER BY ar2.sale_date DESC LIMIT 1) as artwork_thumb,
                   (SELECT ROUND(AVG((ar3.hammer_price_usd - ar3.estimate_high) * 100.0 / ar3.estimate_high), 0)
                    FROM auction_results ar3
                    WHERE ar3.artist_id = a.id AND ar3.sold = 1
                      AND ar3.estimate_high IS NOT NULL AND ar3.estimate_high > 0
                      AND ar3.hammer_price_usd IS NOT NULL) as avg_vs_estimate
            FROM artists a
            JOIN auction_results ar ON ar.artist_id = a.id
            LEFT JOIN (
                SELECT artist_id, composite_score, sell_through_rate, estimate_beat_rate
                FROM trend_scores
                WHERE id IN (SELECT MAX(id) FROM trend_scores GROUP BY artist_id)
            ) ts ON ts.artist_id = a.id
            LEFT JOIN (
                SELECT artist_id, composite_score
                FROM trend_scores
                WHERE id IN (
                    SELECT MAX(id) FROM trend_scores
                    WHERE id NOT IN (SELECT MAX(id) FROM trend_scores GROUP BY artist_id)
                    GROUP BY artist_id
                )
            ) ts_prev ON ts_prev.artist_id = a.id
            WHERE ar.sold = 1 {price_clause}
            {medium_clause}
            GROUP BY a.id
            HAVING sale_count >= 2
            ORDER BY {order}
            LIMIT {per_page} OFFSET {offset}
        """, params).fetchall()

        # Get available mediums for filter
        mediums = db.execute("""
            SELECT DISTINCT medium FROM artists
            WHERE medium IS NOT NULL AND medium != ''
            ORDER BY medium
        """).fetchall()

        # Stats
        total_artists = db.execute("SELECT COUNT(*) as c FROM artists").fetchone()["c"]
        total_results = db.execute("SELECT COUNT(*) as c FROM auction_results WHERE sold = 1").fetchone()["c"]
        total_signals = db.execute("SELECT COUNT(*) as c FROM price_signals").fetchone()["c"]

        # Last updated timestamp
        last_scrape = db.execute("""
            SELECT finished_at FROM scrape_log
            WHERE status = 'complete' OR status = 'success'
            ORDER BY finished_at DESC LIMIT 1
        """).fetchone()
        last_updated = last_scrape["finished_at"][:10] if last_scrape and last_scrape["finished_at"] else None

    return render_template(
        "index.html",
        artists=artists,
        mediums=[m["medium"] for m in mediums],
        sort=sort,
        medium_filter=medium_filter,
        price_min=price_min,
        price_max=price_max,
        global_price_min=int(price_bounds["global_min"] or 0),
        global_price_max=int(price_bounds["global_max"] or 500000),
        total_artists=total_artists,
        total_results=total_results,
        total_signals=total_signals,
        last_updated=last_updated,
        page=page,
        total_pages=total_pages,
        total_matching=total_matching,
        search_q=search_q,
        pagination_qs=_build_pagination_qs(sort, medium_filter, price_min, price_max, search_q),
    )


def _build_pagination_qs(sort, medium, price_min, price_max, search_q):
    """Build query string for pagination links, excluding page param."""
    from urllib.parse import urlencode
    params = {}
    if sort and sort != "score":
        params["sort"] = sort
    if medium and medium != "all":
        params["medium"] = medium
    if price_min > 0:
        params["price_min"] = price_min
    if price_max > 0:
        params["price_max"] = price_max
    if search_q:
        params["q"] = search_q
    return urlencode(params)


@app.route("/artist/<int:artist_id>")
def artist_detail(artist_id):
    """Individual artist page with price chart."""
    with get_db() as db:
        artist = db.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        if not artist:
            return "Artist not found", 404

        results = db.execute("""
            SELECT * FROM auction_results
            WHERE artist_id = ? AND sold = 1
            ORDER BY sale_date ASC
        """, (artist_id,)).fetchall()

        signals = db.execute("""
            SELECT * FROM price_signals
            WHERE artist_id = ?
            ORDER BY signal_date DESC
        """, (artist_id,)).fetchall()

        score = db.execute("""
            SELECT * FROM trend_scores
            WHERE artist_id = ?
            ORDER BY period DESC LIMIT 1
        """, (artist_id,)).fetchone()

        # Get artwork thumbnail for og:image (use larger size for social sharing)
        og_image_row = db.execute("""
            SELECT image_url FROM auction_results
            WHERE artist_id = ? AND image_url IS NOT NULL AND image_url != ''
            ORDER BY sale_date DESC LIMIT 1
        """, (artist_id,)).fetchone()
        # Upscale Artsy CDN URL for social previews
        og_image = None
        if og_image_row and og_image_row["image_url"]:
            og_url = og_image_row["image_url"]
            og_image = og_url.replace("height=50", "height=600").replace("width=50", "width=600").replace("height=150", "height=600").replace("width=150", "width=600")

    # Build price chart
    chart_json = _build_price_chart(artist, results)

    return render_template(
        "artist.html",
        artist=artist,
        results=results,
        signals=signals,
        score=score,
        chart_json=chart_json,
        og_image=og_image,
    )


@app.route("/discover")
def discover():
    """Discovery feed — newly tracked artists and first sales."""
    with get_db() as db:
        # Artists with recent first sales
        new_artists = db.execute("""
            SELECT a.id, a.name, a.nationality, a.birth_year, a.medium, a.tags,
                   a.first_seen_date,
                   COUNT(ar.id) as sale_count,
                   ROUND(AVG(ar.hammer_price_usd), 0) as avg_price
            FROM artists a
            LEFT JOIN auction_results ar ON ar.artist_id = a.id AND ar.sold = 1
            GROUP BY a.id
            ORDER BY a.first_seen_date DESC
            LIMIT 50
        """).fetchall()

        # Recent signals
        recent_signals = db.execute("""
            SELECT ps.*, a.name as artist_name, a.id as artist_id
            FROM price_signals ps
            JOIN artists a ON a.id = ps.artist_id
            ORDER BY ps.signal_date DESC
            LIMIT 20
        """).fetchall()

    return render_template(
        "discover.html",
        new_artists=new_artists,
        recent_signals=recent_signals,
    )


def _build_price_chart(artist, results):
    """Build a Plotly price chart for an artist."""
    if not results:
        return None

    dates = [r["sale_date"] for r in results if r["sale_date"]]
    prices = [r["hammer_price_usd"] for r in results if r["sale_date"] and r["hammer_price_usd"]]
    houses = [r["auction_house"] or "" for r in results if r["sale_date"] and r["hammer_price_usd"]]
    titles = [r["title"] or "Untitled" for r in results if r["sale_date"] and r["hammer_price_usd"]]

    if not dates:
        return None

    hover_text = [
        f"<b>{t[:40]}</b><br>{h}<br>${p:,.0f}"
        for t, h, p in zip(titles, houses, prices)
    ]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dates,
        y=prices,
        mode="markers+lines",
        marker=dict(size=10, color="#e74c3c", line=dict(width=1, color="#c0392b")),
        line=dict(color="#e74c3c", width=2, dash="dot"),
        hovertext=hover_text,
        hoverinfo="text",
        name="Hammer Price",
    ))

    # Add estimate bands if available
    est_dates = []
    est_lows = []
    est_highs = []
    for r in results:
        if r["sale_date"] and r["estimate_low"] and r["estimate_high"]:
            est_dates.append(r["sale_date"])
            est_lows.append(r["estimate_low"])
            est_highs.append(r["estimate_high"])

    if est_dates:
        fig.add_trace(go.Scatter(
            x=est_dates + est_dates[::-1],
            y=est_highs + est_lows[::-1],
            fill="toself",
            fillcolor="rgba(52, 152, 219, 0.15)",
            line=dict(color="rgba(52, 152, 219, 0.3)"),
            hoverinfo="skip",
            name="Estimate Range",
        ))

    fig.update_layout(
        title=None,
        xaxis_title=None,
        yaxis_title="Price (USD)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",",
        template="plotly_white",
        height=400,
        margin=dict(l=60, r=20, t=20, b=40),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        font=dict(family="Inter, system-ui, sans-serif"),
    )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5555))
    debug = os.environ.get("FLASK_ENV") != "production"
    app.run(debug=debug, host="0.0.0.0", port=port)
