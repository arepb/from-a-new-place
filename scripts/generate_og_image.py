#!/usr/bin/env python3
"""Generate a rich og:image for social sharing that mirrors the site design."""

import os
import sys
import sqlite3
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PIL import Image, ImageDraw, ImageFont

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artscope.db")
OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "dashboard", "static", "og-image.png"
)

# Colors matching the site's new dark grey-purple palette
BG = (20, 18, 24)          # #141218
SURFACE = (26, 23, 32)     # #1a1720
BORDER = (35, 31, 46)      # #231f2e
ACCENT = (231, 76, 60)     # #e74c3c
TEXT = (224, 224, 224)      # #e0e0e0
TEXT_DIM = (140, 135, 150)  # muted
TEXT_GREEN = (46, 204, 113) # green for positive
WHITE = (255, 255, 255)

W, H = 1200, 630


def hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def try_font(names, size):
    """Try loading fonts by name, fall back to default."""
    for name in names:
        for path in [
            f"/System/Library/Fonts/{name}",
            f"/Library/Fonts/{name}",
            f"/System/Library/Fonts/Supplemental/{name}",
            f"/usr/share/fonts/truetype/{name}",
        ]:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue
    return ImageFont.load_default()


def generate():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Get top 8 artists
    top_artists = conn.execute("""
        SELECT a.id, a.name, a.nationality, a.birth_year,
               t.composite_score as heat, t.price_change_pct
        FROM artists a
        JOIN trend_scores t ON t.artist_id = a.id
        ORDER BY t.composite_score DESC
        LIMIT 8
    """).fetchall()

    # Get colors for each artist
    artist_colors = {}
    for a in top_artists:
        colors = conn.execute(
            "SELECT hex_color, percentage FROM artist_colors WHERE artist_id = ? ORDER BY rank",
            (a["id"],),
        ).fetchall()
        artist_colors[a["id"]] = [c["hex_color"] for c in colors]

    # Get monthly price data for sparkline
    monthly = conn.execute("""
        SELECT strftime("%Y-%m", sale_date) as month,
               AVG(hammer_price_usd) as avg_price,
               COUNT(*) as count
        FROM auction_results
        WHERE hammer_price_usd > 0 AND sale_date IS NOT NULL
        GROUP BY month ORDER BY month
    """).fetchall()

    total_artists = conn.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
    total_results = conn.execute("SELECT COUNT(*) FROM auction_results").fetchone()[0]
    conn.close()

    # Create image
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Fonts
    font_title = try_font(["Helvetica-Bold.ttc", "Helvetica.ttc", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"], 38)
    font_subtitle = try_font(["Helvetica.ttc", "Helvetica-Light.ttc", "Arial.ttf", "DejaVuSans.ttf"], 16)
    font_label = try_font(["Helvetica.ttc", "Helvetica-Light.ttc", "Arial.ttf", "DejaVuSans.ttf"], 13)
    font_stat = try_font(["Helvetica-Bold.ttc", "Helvetica.ttc", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"], 22)
    font_row_name = try_font(["Helvetica-Bold.ttc", "Helvetica.ttc", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"], 15)
    font_row = try_font(["Helvetica.ttc", "Helvetica-Light.ttc", "Arial.ttf", "DejaVuSans.ttf"], 13)
    font_heat = try_font(["Helvetica-Bold.ttc", "Helvetica.ttc", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"], 14)
    font_chart_label = try_font(["Helvetica.ttc", "Helvetica-Light.ttc", "Arial.ttf", "DejaVuSans.ttf"], 11)

    # === HEADER ===
    # Title
    draw.text((40, 30), "From A ", fill=WHITE, font=font_title)
    title_w = draw.textlength("From A ", font=font_title)
    draw.text((40 + title_w, 30), "New Place", fill=ACCENT, font=font_title)

    # Subtitle
    draw.text((40, 78), "Emerging artist price tracker — ranked by Heat Index", fill=TEXT_DIM, font=font_subtitle)

    # Header line
    draw.line([(40, 108), (W - 40, 108)], fill=BORDER, width=1)

    # === STATS ROW ===
    stats_y = 120
    stats = [
        ("ARTISTS", str(total_artists)),
        ("AUCTION RESULTS", f"{total_results:,}"),
        ("HEAT INDEX", "SCORING"),
    ]
    stat_x = 40
    for label, value in stats:
        draw.text((stat_x, stats_y), label, fill=TEXT_DIM, font=font_label)
        draw.text((stat_x + 2, stats_y + 16), value, fill=WHITE, font=font_stat)
        stat_x += 200

    # === LEFT SIDE: LEADERBOARD ===
    table_y = 170
    draw.line([(40, table_y), (640, table_y)], fill=BORDER, width=1)

    # Column headers
    header_y = table_y + 6
    draw.text((40, header_y), "#", fill=TEXT_DIM, font=font_label)
    draw.text((65, header_y), "ARTIST", fill=TEXT_DIM, font=font_label)
    draw.text((330, header_y), "PALETTE", fill=TEXT_DIM, font=font_label)
    draw.text((500, header_y), "HEAT", fill=TEXT_DIM, font=font_label)
    draw.text((560, header_y), "TREND", fill=TEXT_DIM, font=font_label)

    draw.line([(40, header_y + 20), (640, header_y + 20)], fill=BORDER, width=1)

    # Artist rows
    row_y = header_y + 28
    row_h = 48

    for i, a in enumerate(top_artists):
        # Subtle alternating row bg
        if i % 2 == 1:
            draw.rectangle(
                [(38, row_y - 2), (642, row_y + row_h - 6)],
                fill=(22, 20, 28),
            )

        # Rank number
        draw.text((44, row_y + 6), str(i + 1), fill=TEXT_DIM, font=font_row)

        # Artist name
        name = a["name"]
        if len(name) > 25:
            name = name[:23] + "…"
        draw.text((65, row_y + 2), name, fill=WHITE, font=font_row_name)

        # Bio line
        bio_parts = []
        if a["nationality"]:
            bio_parts.append(a["nationality"])
        if a["birth_year"]:
            bio_parts.append(f"b. {a['birth_year']}")
        if bio_parts:
            draw.text((65, row_y + 22), " · ".join(bio_parts), fill=TEXT_DIM, font=font_chart_label)

        # Color palette dots
        colors = artist_colors.get(a["id"], [])
        dot_x = 330
        for hex_c in colors[:5]:
            rgb = hex_to_rgb(hex_c)
            draw.ellipse(
                [(dot_x, row_y + 10), (dot_x + 16, row_y + 26)],
                fill=rgb,
            )
            dot_x += 22

        # Heat score pill
        heat = a["heat"] * 100
        pill_x = 495
        pill_w = 44
        pill_h = 24
        pill_y = row_y + 6
        # Pill color intensity based on heat
        intensity = min(heat / 80, 1.0)
        pill_color = (
            int(ACCENT[0] * intensity + SURFACE[0] * (1 - intensity)),
            int(ACCENT[1] * intensity + SURFACE[1] * (1 - intensity)),
            int(ACCENT[2] * intensity + SURFACE[2] * (1 - intensity)),
        )
        draw.rounded_rectangle(
            [(pill_x, pill_y), (pill_x + pill_w, pill_y + pill_h)],
            radius=12,
            fill=pill_color,
        )
        heat_text = f"{heat:.0f}"
        tw = draw.textlength(heat_text, font=font_heat)
        draw.text(
            (pill_x + (pill_w - tw) / 2, pill_y + 4),
            heat_text,
            fill=WHITE,
            font=font_heat,
        )

        # Trend
        pct = (a["price_change_pct"] or 0) * 100
        trend_text = f"+{pct:.0f}%" if pct > 0 else f"{pct:.0f}%"
        trend_color = TEXT_GREEN if pct > 0 else ACCENT if pct < 0 else TEXT_DIM
        draw.text((560, row_y + 8), trend_text, fill=trend_color, font=font_row)

        row_y += row_h

    # === RIGHT SIDE: PRICE CHART ===
    chart_x = 680
    chart_y = 170
    chart_w = 480
    chart_h = 380

    # Chart background
    draw.rounded_rectangle(
        [(chart_x, chart_y), (chart_x + chart_w, chart_y + chart_h)],
        radius=8,
        fill=SURFACE,
        outline=BORDER,
    )

    # Chart title
    draw.text(
        (chart_x + 20, chart_y + 12),
        "AVERAGE SALE PRICE",
        fill=TEXT_DIM,
        font=font_label,
    )
    draw.text(
        (chart_x + 20, chart_y + 28),
        "Monthly trend across all tracked artists",
        fill=(100, 95, 110),
        font=font_chart_label,
    )

    # Plot area
    plot_x = chart_x + 70
    plot_y = chart_y + 60
    plot_w = chart_w - 100
    plot_h = chart_h - 110

    # Use last 18 months of data
    plot_data = monthly[-18:] if len(monthly) >= 18 else monthly
    if plot_data:
        prices = [d["avg_price"] for d in plot_data]
        max_price = max(prices)
        min_price = min(prices)
        price_range = max_price - min_price or 1

        # Grid lines
        for j in range(5):
            gy = plot_y + int(plot_h * j / 4)
            draw.line([(plot_x, gy), (plot_x + plot_w, gy)], fill=BORDER, width=1)
            # Price label
            price_val = max_price - (price_range * j / 4)
            if price_val >= 1000:
                label = f"${price_val / 1000:.0f}K"
            else:
                label = f"${price_val:.0f}"
            draw.text((plot_x - 50, gy - 6), label, fill=TEXT_DIM, font=font_chart_label)

        # Plot filled area + line
        points = []
        for j, d in enumerate(plot_data):
            px = plot_x + int(plot_w * j / (len(plot_data) - 1))
            py = plot_y + plot_h - int(plot_h * (d["avg_price"] - min_price) / price_range)
            points.append((px, py))

        # Filled area under curve (gradient effect)
        if len(points) >= 2:
            # Create polygon for fill
            fill_points = list(points) + [
                (points[-1][0], plot_y + plot_h),
                (points[0][0], plot_y + plot_h),
            ]
            # Semi-transparent fill - draw multiple fading layers
            for offset in range(0, 60, 2):
                alpha_pct = 1.0 - (offset / 60)
                fill_color = (
                    int(ACCENT[0] * 0.3 * alpha_pct + BG[0] * (1 - 0.3 * alpha_pct)),
                    int(ACCENT[1] * 0.3 * alpha_pct + BG[1] * (1 - 0.3 * alpha_pct)),
                    int(ACCENT[2] * 0.3 * alpha_pct + BG[2] * (1 - 0.3 * alpha_pct)),
                )
                shifted_points = [(x, min(y + offset, plot_y + plot_h)) for x, y in points]
                shifted_fill = list(shifted_points) + [
                    (points[-1][0], plot_y + plot_h),
                    (points[0][0], plot_y + plot_h),
                ]
                if len(shifted_fill) >= 3:
                    draw.polygon(shifted_fill, fill=fill_color)

            # Main line
            for j in range(len(points) - 1):
                draw.line(
                    [points[j], points[j + 1]],
                    fill=ACCENT,
                    width=3,
                )

            # Dots at data points
            for px, py in points:
                draw.ellipse(
                    [(px - 3, py - 3), (px + 3, py + 3)],
                    fill=ACCENT,
                )

        # Month labels (every 3rd month)
        for j, d in enumerate(plot_data):
            if j % 3 == 0 or j == len(plot_data) - 1:
                px = plot_x + int(plot_w * j / (len(plot_data) - 1))
                month_str = d["month"][-5:]  # "05-25" style
                draw.text(
                    (px - 12, plot_y + plot_h + 8),
                    month_str,
                    fill=TEXT_DIM,
                    font=font_chart_label,
                )

    # === BOTTOM BAR ===
    draw.line([(40, H - 50), (W - 40, H - 50)], fill=BORDER, width=1)
    draw.text(
        (40, H - 38),
        "from-a-new-place.onrender.com",
        fill=TEXT_DIM,
        font=font_label,
    )

    # Accent bar at top
    draw.rectangle([(0, 0), (W, 3)], fill=ACCENT)

    img.save(OUT_PATH, "PNG", optimize=True)
    print(f"Saved og-image to {OUT_PATH}")
    print(f"Size: {os.path.getsize(OUT_PATH):,} bytes")


if __name__ == "__main__":
    generate()
