"""Heat Index — composite scoring algorithm for emerging artist detection.

Combines price momentum, sell-through rates, estimate-beating behavior,
editorial signals, and social momentum into a single 0-1 score.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Default weights (should match config.yaml)
DEFAULT_WEIGHTS = {
    "price_velocity": 0.30,
    "sell_through_rate": 0.20,
    "estimate_beat_rate": 0.15,
    "volume_increase": 0.10,
    "editorial_signals": 0.10,
    "social_momentum": 0.10,
    "source_diversification": 0.05,
}


def compute_heat_index(db, artist_id, period=None, weights=None):
    """
    Compute Heat Index for an artist for a given period.

    Args:
        db: SQLite connection
        artist_id: artist row id
        period: YYYY-MM string (defaults to current month)
        weights: dict of factor weights (defaults to DEFAULT_WEIGHTS)

    Returns:
        dict with individual factor scores and composite score
    """
    weights = weights or DEFAULT_WEIGHTS
    period = period or datetime.now().strftime("%Y-%m")

    scores = {
        "price_velocity": _price_velocity(db, artist_id),
        "sell_through_rate": _sell_through_rate(db, artist_id),
        "estimate_beat_rate": _estimate_beat_rate(db, artist_id),
        "volume_increase": _volume_increase(db, artist_id),
        "editorial_signals": _editorial_signal_score(db, artist_id),
        "social_momentum": 0.0,  # populated separately via Google Trends
        "source_diversification": _source_diversification(db, artist_id),
    }

    composite = sum(scores[k] * weights.get(k, 0) for k in scores)
    scores["composite_score"] = round(min(composite, 1.0), 4)
    scores["period"] = period
    scores["artist_id"] = artist_id

    return scores


def _price_velocity(db, artist_id, months=24):
    """% change in average hammer price — first half vs second half of history.
    Returns 0-1 score where 1 = +100% or more growth."""
    # Split the artist's full auction history in half chronologically
    results = db.execute(
        """SELECT hammer_price_usd FROM auction_results
           WHERE artist_id = ? AND sold = 1 AND hammer_price_usd > 0
           ORDER BY sale_date ASC""",
        (artist_id,),
    ).fetchall()

    if len(results) < 4:
        # Need at least 4 results to split meaningfully
        return 0.0

    mid = len(results) // 2
    early_avg = sum(r["hammer_price_usd"] for r in results[:mid]) / mid
    recent_avg = sum(r["hammer_price_usd"] for r in results[mid:]) / (len(results) - mid)

    if early_avg == 0:
        return 0.0

    change_pct = (recent_avg - early_avg) / early_avg
    # Normalize: 0% = 0, 100%+ = 1.0
    return round(min(max(change_pct, 0), 1.0), 4)


def _avg_price(db, artist_id, date_from, date_to):
    row = db.execute(
        """SELECT AVG(hammer_price_usd) as avg_price
           FROM auction_results
           WHERE artist_id = ? AND sale_date BETWEEN ? AND ?
             AND hammer_price_usd IS NOT NULL AND sold = 1""",
        (artist_id, date_from, date_to),
    ).fetchone()
    return row["avg_price"] if row and row["avg_price"] else None


def _sell_through_rate(db, artist_id, months=36):
    """% of lots that actually sold. High sell-through = demand."""
    cutoff = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    row = db.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN sold = 1 THEN 1 ELSE 0 END) as sold_count
           FROM auction_results
           WHERE artist_id = ? AND sale_date >= ?""",
        (artist_id, cutoff),
    ).fetchone()

    total = row["total"] if row else 0
    if total == 0:
        return 0.0

    rate = row["sold_count"] / total
    return round(rate, 4)


def _estimate_beat_rate(db, artist_id, months=36):
    """How often hammer price exceeds high estimate. Beating estimates = heat."""
    cutoff = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    row = db.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN hammer_price_usd > estimate_high THEN 1 ELSE 0 END) as beat_count
           FROM auction_results
           WHERE artist_id = ? AND sale_date >= ?
             AND estimate_high IS NOT NULL AND estimate_high > 0 AND sold = 1""",
        (artist_id, cutoff),
    ).fetchone()

    total = row["total"] if row else 0
    if total == 0:
        return 0.0

    return round(row["beat_count"] / total, 4)


def _volume_increase(db, artist_id, months=18):
    """Are more lots appearing? Compares recent half vs earlier half."""
    now = datetime.now()
    mid = now - timedelta(days=months * 30 // 2)
    start = now - timedelta(days=months * 30)

    early = db.execute(
        "SELECT COUNT(*) as c FROM auction_results WHERE artist_id = ? AND sale_date BETWEEN ? AND ?",
        (artist_id, start.strftime("%Y-%m-%d"), mid.strftime("%Y-%m-%d")),
    ).fetchone()["c"]

    recent = db.execute(
        "SELECT COUNT(*) as c FROM auction_results WHERE artist_id = ? AND sale_date BETWEEN ? AND ?",
        (artist_id, mid.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")),
    ).fetchone()["c"]

    if early == 0:
        return 0.5 if recent > 0 else 0.0

    increase = (recent - early) / early
    return round(min(max(increase, 0), 1.0), 4)


def _editorial_signal_score(db, artist_id, months=6):
    """Score based on editorial mentions. More mentions = more heat."""
    cutoff = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    row = db.execute(
        """SELECT COUNT(*) as c FROM price_signals
           WHERE artist_id = ? AND signal_date >= ?
             AND signal_type = 'editorial_mention'""",
        (artist_id, cutoff),
    ).fetchone()

    count = row["c"] if row else 0
    # Normalize: 0 mentions = 0, 5+ mentions = 1.0
    return round(min(count / 5.0, 1.0), 4)


def _source_diversification(db, artist_id, months=36):
    """Score based on appearing at multiple auction houses."""
    cutoff = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    row = db.execute(
        """SELECT COUNT(DISTINCT auction_house) as houses
           FROM auction_results
           WHERE artist_id = ? AND sale_date >= ?""",
        (artist_id, cutoff),
    ).fetchone()

    houses = row["houses"] if row else 0
    # 1 house = 0, 2 = 0.33, 3 = 0.67, 4+ = 1.0
    if houses <= 1:
        return 0.0
    return round(min((houses - 1) / 3.0, 1.0), 4)


def score_all_artists(db, min_sales=3, weights=None):
    """Score all artists with enough data. Returns list of score dicts."""
    artists = db.execute(
        """SELECT a.id, a.name, COUNT(ar.id) as sale_count
           FROM artists a
           JOIN auction_results ar ON ar.artist_id = a.id
           WHERE ar.sold = 1
           GROUP BY a.id
           HAVING sale_count >= ?
           ORDER BY sale_count DESC""",
        (min_sales,),
    ).fetchall()

    scores = []
    for artist in artists:
        score = compute_heat_index(db, artist["id"], weights=weights)
        score["artist_name"] = artist["name"]
        score["num_sales"] = artist["sale_count"]
        scores.append(score)

    scores.sort(key=lambda x: x["composite_score"], reverse=True)
    return scores


def save_scores(db, scores):
    """Persist scores to the trend_scores table."""
    for s in scores:
        db.execute(
            """INSERT OR REPLACE INTO trend_scores
               (artist_id, period, avg_price, median_price, num_sales,
                price_change_pct, sell_through_rate, estimate_beat_rate,
                signal_count, composite_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s["artist_id"], s["period"], None, None,
                s.get("num_sales", 0),
                s.get("price_velocity", 0),
                s.get("sell_through_rate", 0),
                s.get("estimate_beat_rate", 0),
                0,
                s["composite_score"],
            ),
        )
