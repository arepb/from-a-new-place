# ArtScope — From A New Place

## Overview
Emerging artist auction price tracker. Scrapes auction data from Artsy's GraphQL API, scores artists with a composite "Heat Index," and displays results via a Flask dashboard. Live at **https://from-a-new-place.onrender.com/**

## Tech Stack
- **Backend**: Flask + SQLite (artscope.db), deployed on Render via gunicorn
- **Frontend**: Jinja2 templates, inline CSS, Plotly.js for charts
- **Scraping**: Artsy Metaphysics v2 GraphQL (no auth), plus Invaluable, Heritage, LiveAuctioneers
- **Image processing**: Pillow (color extraction, og-image generation)
- **Dependencies**: flask, plotly, requests, gunicorn, click, tabulate, Pillow

## Architecture

### Database (`database.py`)
SQLite with WAL mode, foreign keys enforced. Key tables:
- **artists** — name, slug, nationality, birth_year, medium, tags, instagram_handle, wikipedia_url
- **auction_results** — artist_id FK, title, sale_date, auction_house, hammer_price_usd, estimate_low/high, image_url, sale_url, source_id. UNIQUE(auction_house, source_id)
- **trend_scores** — artist_id FK, period (YYYY-MM), composite_score, sell_through_rate, estimate_beat_rate, price_change_pct. UNIQUE(artist_id, period)
- **price_signals** — artist_id FK, signal_type, source, details, url
- **artist_colors** — artist_id FK, hex_color, percentage, rank (1-5). UNIQUE(artist_id, rank)
- **scrape_log** — source, status, records_found/new, timestamps

### Dashboard (`dashboard/app.py`)
Routes:
- `GET /` — Discover (main page). Sortable by heat_score, price, sales, recent. Filterable by medium, price range, search. 50/page.
- `GET /gallery` — Visual grid of artwork thumbnails, 60/page, ordered by sale_date DESC. Thumbnails link to Artsy, artist names link to detail pages.
- `GET /discover` — Signals: new artists feed + recent editorial signals.
- `GET /artist/<slug>` — Artist detail with Plotly price chart, auction history, signals, color palette.
- `GET /artist/<int:artist_id>` — 301 redirect to slug URL (backward compat).

### Scraper (`scraper/`)
- **artsy.py** — Primary source. GraphQL to `https://metaphysics-production.artsy.net/v2`. No auth needed. Fetches artist info + auction results with images.
- **base.py** — Rate limiting, UA rotation, currency conversion (20+ currencies), price parsing.
- **signals.py** — RSS monitoring of 9 publications: Artforum, Hyperallergic, ARTnews, The Art Newspaper, ArtDaily, Juxtapoz, NYT, Financial Times, The Guardian.
- **invaluable.py**, **heritage.py**, **liveauctioneers.py** — Secondary auction sources.
- **discover.py** — Artist discovery from Artsy.

### Scripts (`scripts/`)
- **seed_artists.py** — Initialize DB with curated 30-artist watchlist.
- **extract_colors.py** — Top 5 dominant colors per artist from artwork thumbnails. Uses PIL quantize. `--force` to re-extract.
- **backfill_bio.py** — Wikipedia API for nationality/birth_year. Extensive nationality mapping.
- **fix_estimates.py** — Re-fetch and convert non-USD estimates from Artsy API.
- **generate_og_image.py** — 1200x630 PNG with leaderboard preview + price chart for social sharing.

### Scoring (`analysis/heat_index.py`)
Composite score (0-1, displayed 0-100) weighted:
- Price velocity: 30%
- Sell-through rate: 20%
- Estimate beat rate: 15%
- Volume increase: 10%
- Editorial signals: 10%
- Social momentum: 10%
- Source diversification: 5%

### Update cycle (`update.py`)
Biweekly: scrape all sources → score artists → log results.

## Design System
- **Background**: #fff4f4 (pinkish, inspired by Colby Museum of Art)
- **Text**: #1a1a1a (near-black)
- **Accent**: #c0392b (deep red)
- **Surface**: #fff (cards, chart backgrounds)
- **Border**: #e0d5d5
- **Font**: Inter, system-ui, -apple-system, sans-serif
- **Style**: Bold uppercase headers, clean grid layouts, minimal ornamentation

## Deployment
- **Platform**: Render.com (render.yaml)
- **Start**: `cd dashboard && gunicorn app:app --bind 0.0.0.0:$PORT`
- **Auto-deploy**: Push to `master` branch on GitHub (arepb/from-a-new-place)
- **Local dev**: `python dashboard/app.py` on port 5555 (configured in `.claude/launch.json`)

## Key Conventions
- Artsy CDN images resize via URL params: `height=300&width=300` for thumbnails, `height=600&width=600` for social previews
- Artist URLs use slugs (`/artist/futura`) with 301 redirects from old numeric IDs
- Currency conversion handles 20+ currencies in `_parse_estimate` (scraper/artsy.py)
- og:image must be PNG/JPG (never SVG — iOS/iMessage doesn't support it)
- All templates share consistent nav: Discover | Gallery | Signals
- Database path: `artscope.db` in project root

## Current Stats (as of March 2025)
- 205 artists tracked
- 10,488 auction results
- 15 editorial signals
- 165 pages in gallery (60/page)
