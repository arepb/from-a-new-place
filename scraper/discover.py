"""Auto-discover emerging artists from Artsy auction results.

Uses Artsy's Metaphysics v2 GraphQL API to search recent auction results
across multiple categories and price points, then extracts new artist names
to add to our tracking database.
"""

import time
import random
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

ARTSY_API = "https://metaphysics-production.artsy.net/v2"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept": "application/json",
}


def discover_artists_from_gene(gene_id, first=100):
    """
    Discover artists via an Artsy gene (category) by finding artists
    who have auction results.

    Returns list of artist slug strings.
    """
    query = """
    query($geneId: String!, $first: Int!) {
      gene(id: $geneId) {
        name
        artistsConnection(first: $first) {
          edges {
            node {
              slug
              name
              nationality
              birthday
              deathday
              image {
                cropped(width: 100, height: 100) {
                  url
                }
              }
              auctionResultsConnection(first: 1, sort: DATE_DESC) {
                totalCount
              }
            }
          }
        }
      }
    }
    """
    try:
        resp = requests.post(
            ARTSY_API,
            json={"query": query, "variables": {"geneId": gene_id, "first": first}},
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Gene query error for {gene_id}: {e}")
        return []

    gene_data = data.get("data", {}).get("gene")
    if not gene_data:
        logger.debug(f"Gene not found: {gene_id}")
        return []

    artists = []
    edges = gene_data.get("artistsConnection", {}).get("edges", [])
    for edge in edges:
        node = edge.get("node", {})
        total = node.get("auctionResultsConnection", {}).get("totalCount", 0)
        if total >= 3:  # Only artists with some auction history
            artists.append({
                "name": node["name"],
                "slug": node["slug"],
                "nationality": node.get("nationality", ""),
                "birth_year": _parse_year(node.get("birthday", "")),
                "death_year": _parse_year(node.get("deathday", "")),
                "total_results": total,
                "image_url": _get_image(node),
            })

    logger.info(f"Gene '{gene_data['name']}': {len(edges)} artists, {len(artists)} with 3+ auction results")
    return artists


def discover_artists_by_search(keyword, first=50):
    """
    Search Artsy for artists matching a keyword.
    Returns list of artist info dicts.
    """
    query = """
    query($keyword: String!, $first: Int!) {
      matchConnection(term: $keyword, first: $first, entities: [ARTIST]) {
        edges {
          node {
            ... on Artist {
              slug
              name
              nationality
              birthday
              deathday
              image {
                cropped(width: 100, height: 100) {
                  url
                }
              }
              auctionResultsConnection(first: 1, sort: DATE_DESC) {
                totalCount
              }
            }
          }
        }
      }
    }
    """
    try:
        resp = requests.post(
            ARTSY_API,
            json={"query": query, "variables": {"keyword": keyword, "first": first}},
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Search error for '{keyword}': {e}")
        return []

    edges = data.get("data", {}).get("matchConnection", {}).get("edges", [])
    artists = []
    for edge in edges:
        node = edge.get("node", {})
        if not node.get("name"):
            continue
        total = node.get("auctionResultsConnection", {}).get("totalCount", 0)
        if total >= 3:
            artists.append({
                "name": node["name"],
                "slug": node["slug"],
                "nationality": node.get("nationality", ""),
                "birth_year": _parse_year(node.get("birthday", "")),
                "death_year": _parse_year(node.get("deathday", "")),
                "total_results": total,
                "image_url": _get_image(node),
            })

    logger.info(f"Search '{keyword}': {len(edges)} results, {len(artists)} with 3+ auction results")
    return artists


def discover_curated_artists():
    """
    Hand-picked emerging artists across diverse mediums and geographies
    that aren't in the seed list. These are artists with growing auction
    markets that represent interesting collecting opportunities.
    """
    return [
        # Contemporary painting — African diaspora
        {"name": "Amoako Boafo", "medium": "painting", "tags": "painting,figurative,african contemporary"},
        {"name": "Aboudia", "medium": "painting", "tags": "painting,street art,african contemporary"},
        {"name": "Cinga Samson", "medium": "painting", "tags": "painting,figurative,african contemporary"},
        {"name": "Kudzanai-Violet Hwami", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Michaela Yearwood-Dan", "medium": "painting", "tags": "painting,textile,mixed media"},
        {"name": "Jerrell Gibbs", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Arcmanoro Niles", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Kwesi Botchway", "medium": "painting", "tags": "painting,figurative,african contemporary"},
        {"name": "Tunji Adeniyi-Jones", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Collins Obijiaku", "medium": "painting", "tags": "painting,figurative,contemporary"},

        # Contemporary painting — figurative
        {"name": "Anna Weyant", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Hilary Pecis", "medium": "painting", "tags": "painting,still life,contemporary"},
        {"name": "Lucy Bull", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Avery Singer", "medium": "painting", "tags": "painting,digital,contemporary"},
        {"name": "Loie Hollowell", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Emily Mae Smith", "medium": "painting", "tags": "painting,figurative,surrealist"},
        {"name": "Nicolas Party", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Shara Hughes", "medium": "painting", "tags": "painting,landscape,contemporary"},
        {"name": "Jordy Kerwick", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Matthew Wong", "medium": "painting", "tags": "painting,landscape,contemporary"},

        # Abstract & pattern painting
        {"name": "Dashiell Manley", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Sarah Meyohas", "medium": "mixed media", "tags": "mixed media,conceptual,contemporary"},
        {"name": "Erin Morrison", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Austin Lee", "medium": "painting", "tags": "painting,digital,figurative"},

        # Photography — contemporary
        {"name": "Roe Ethridge", "medium": "photography", "tags": "photography,contemporary,conceptual"},
        {"name": "Deana Lawson", "medium": "photography", "tags": "photography,portrait,contemporary"},
        {"name": "Zanele Muholi", "medium": "photography", "tags": "photography,portrait,contemporary"},
        {"name": "Elle Pérez", "medium": "photography", "tags": "photography,portrait,contemporary"},
        {"name": "Viviane Sassen", "medium": "photography", "tags": "photography,fashion,contemporary"},
        {"name": "Paul Mpagi Sepuya", "medium": "photography", "tags": "photography,contemporary,portrait"},

        # Ceramics / sculpture — growing market
        {"name": "Takuro Kuwata", "medium": "ceramics", "tags": "ceramics,sculpture,japanese contemporary"},
        {"name": "Brian Rochefort", "medium": "ceramics", "tags": "ceramics,sculpture,contemporary"},
        {"name": "Brie Ruais", "medium": "ceramics", "tags": "ceramics,sculpture,contemporary"},
        {"name": "Ghada Amer", "medium": "sculpture", "tags": "sculpture,textile,contemporary"},
        {"name": "Simone Leigh", "medium": "sculpture", "tags": "sculpture,ceramics,contemporary"},
        {"name": "Daniel Arsham", "medium": "sculpture", "tags": "sculpture,contemporary,conceptual"},
        {"name": "Yayoi Kusama", "medium": "sculpture", "tags": "sculpture,installation,contemporary"},

        # Works on paper / printmaking
        {"name": "Torey Thornton", "medium": "drawing", "tags": "drawing,abstract,contemporary"},
        {"name": "Chloe Wise", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Jenna Gribbon", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Sanya Kantarovsky", "medium": "painting", "tags": "painting,figurative,contemporary"},

        # Textile / fiber — undervalued
        {"name": "Jeffrey Gibson", "medium": "mixed media", "tags": "mixed media,textile,native american"},
        {"name": "Sanford Biggers", "medium": "mixed media", "tags": "mixed media,quilt,contemporary"},
        {"name": "Sheila Hicks", "medium": "textile", "tags": "textile,sculpture,fiber art"},

        # Street / urban / outsider
        {"name": "KAWS", "medium": "painting", "tags": "painting,sculpture,street art"},
        {"name": "Invader", "medium": "mixed media", "tags": "mixed media,street art,mosaic"},
        {"name": "Futura", "medium": "painting", "tags": "painting,street art,abstract"},
        {"name": "Mr. Doodle", "medium": "drawing", "tags": "drawing,street art,illustration"},
        {"name": "Eddie Martinez", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Harold Ancart", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Vaughn Spann", "medium": "painting", "tags": "painting,abstract,figurative"},

        # Latin American emerging
        {"name": "Oscar Murillo", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Felipe Baeza", "medium": "mixed media", "tags": "mixed media,collage,contemporary"},
        {"name": "Firelei Báez", "medium": "painting", "tags": "painting,figurative,contemporary"},

        # Asian contemporary
        {"name": "Ayako Rokkaku", "medium": "painting", "tags": "painting,figurative,japanese contemporary"},
        {"name": "Yoshitomo Nara", "medium": "painting", "tags": "painting,figurative,japanese contemporary"},
        {"name": "Genieve Figgis", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Tao Siqi", "medium": "painting", "tags": "painting,figurative,chinese contemporary"},
        {"name": "Liu Ye", "medium": "painting", "tags": "painting,figurative,chinese contemporary"},
        {"name": "Huang Yuxing", "medium": "painting", "tags": "painting,abstract,chinese contemporary"},
        {"name": "Zhang Xiaogang", "medium": "painting", "tags": "painting,figurative,chinese contemporary"},
        {"name": "Christine Sun Kim", "medium": "drawing", "tags": "drawing,conceptual,contemporary"},

        # European emerging
        {"name": "Flora Yukhnovich", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Cecily Brown", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Tracey Emin", "medium": "mixed media", "tags": "mixed media,figurative,contemporary"},
        {"name": "Jadé Fadojutimi", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Louise Giovanelli", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Gabriella Boyd", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Holly Hendry", "medium": "sculpture", "tags": "sculpture,installation,contemporary"},
        {"name": "Rachel Jones", "medium": "painting", "tags": "painting,abstract,contemporary"},

        # Multidisciplinary / installation
        {"name": "Tschabalala Self", "medium": "mixed media", "tags": "mixed media,painting,textile"},
        {"name": "Lauren Halsey", "medium": "sculpture", "tags": "sculpture,installation,contemporary"},
        {"name": "Tourmaline", "medium": "photography", "tags": "photography,film,contemporary"},
        {"name": "Baseera Khan", "medium": "mixed media", "tags": "mixed media,installation,contemporary"},

        # Abstract painting — market risers
        {"name": "Tomm El-Saieh", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Sam Gilliam", "medium": "painting", "tags": "painting,abstract,color field"},
        {"name": "Stanley Whitney", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Reggie Burrows Hodges", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Chase Hall", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Louis Fratino", "medium": "painting", "tags": "painting,figurative,contemporary"},

        # Printmaking / editions — accessible
        {"name": "Katherine Bernhardt", "medium": "painting", "tags": "painting,pattern,contemporary"},
        {"name": "Robin F. Williams", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Jammie Holmes", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Henry Taylor", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Calida Rawles", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Titus Kaphar", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Jordan Casteel", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Amy Sherald", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Kehinde Wiley", "medium": "painting", "tags": "painting,figurative,contemporary"},

        # Interesting mid-career with recent heat
        {"name": "Rashid Johnson", "medium": "mixed media", "tags": "mixed media,painting,contemporary"},
        {"name": "Mark Bradford", "medium": "mixed media", "tags": "mixed media,abstract,contemporary"},
        {"name": "Julie Curtiss", "medium": "painting", "tags": "painting,figurative,surrealist"},
        {"name": "Robert Nava", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Salman Toor", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Tala Madani", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Jennifer Packer", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Lynette Yiadom-Boakye", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Njideka Akunyili Crosby", "medium": "mixed media", "tags": "mixed media,collage,figurative"},

        # Sculpture / 3D — diversifying
        {"name": "Huma Bhabha", "medium": "sculpture", "tags": "sculpture,contemporary,figurative"},
        {"name": "Tau Lewis", "medium": "sculpture", "tags": "sculpture,textile,contemporary"},
        {"name": "Arlene Shechet", "medium": "sculpture", "tags": "sculpture,ceramics,contemporary"},
        {"name": "Kennedy Yanko", "medium": "sculpture", "tags": "sculpture,metal,contemporary"},

        # More global diversity
        {"name": "Tomokazu Matsuyama", "medium": "painting", "tags": "painting,figurative,japanese contemporary"},
        {"name": "Wangari Mathenge", "medium": "painting", "tags": "painting,figurative,kenyan contemporary"},
        {"name": "Serge Attukwei Clottey", "medium": "mixed media", "tags": "mixed media,sculpture,ghanaian contemporary"},
        {"name": "Ibrahim El-Salahi", "medium": "painting", "tags": "painting,abstract,sudanese contemporary"},
        {"name": "El Anatsui", "medium": "sculpture", "tags": "sculpture,installation,african contemporary"},
        {"name": "Harminder Judge", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Heji Shin", "medium": "photography", "tags": "photography,contemporary,portrait"},
        {"name": "Sola Olulode", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Ambera Wellmann", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Naudline Pierre", "medium": "painting", "tags": "painting,figurative,contemporary"},

        # Additional emerging to fill out to ~200
        {"name": "Ewa Juszkiewicz", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Lubaina Himid", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Marlene Dumas", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Theaster Gates", "medium": "mixed media", "tags": "mixed media,sculpture,contemporary"},
        {"name": "Kerry James Marshall", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Kara Walker", "medium": "drawing", "tags": "drawing,silhouette,contemporary"},
        {"name": "Mickalene Thomas", "medium": "mixed media", "tags": "mixed media,collage,contemporary"},
        {"name": "Derrick Adams", "medium": "mixed media", "tags": "mixed media,collage,contemporary"},
        {"name": "Deborah Roberts", "medium": "mixed media", "tags": "mixed media,collage,contemporary"},
        {"name": "Patrick Martinez", "medium": "mixed media", "tags": "mixed media,neon,contemporary"},
        {"name": "Mark Grotjahn", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Joe Bradley", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Dana Schutz", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Hernan Bas", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Wangechi Mutu", "medium": "mixed media", "tags": "mixed media,collage,contemporary"},
        {"name": "Lorna Simpson", "medium": "photography", "tags": "photography,mixed media,contemporary"},
        {"name": "Kiki Smith", "medium": "sculpture", "tags": "sculpture,printmaking,contemporary"},
        {"name": "Sarah Sze", "medium": "sculpture", "tags": "sculpture,installation,contemporary"},
        {"name": "Do Ho Suh", "medium": "sculpture", "tags": "sculpture,installation,korean contemporary"},
        {"name": "Lee Bul", "medium": "sculpture", "tags": "sculpture,installation,korean contemporary"},
        {"name": "Ouattara Watts", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Hurvin Anderson", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Peter Doig", "medium": "painting", "tags": "painting,landscape,contemporary"},
        {"name": "Herold Grossbaum", "medium": "painting", "tags": "painting,abstract,contemporary"},
        {"name": "Sol Calero", "medium": "painting", "tags": "painting,installation,contemporary"},
        {"name": "Maryam Hoseini", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Emma McIntyre", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Alejandro Cardenas", "medium": "painting", "tags": "painting,figurative,surrealist"},
        {"name": "Florine Demosthene", "medium": "mixed media", "tags": "mixed media,drawing,contemporary"},
        {"name": "Coady Brown", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Sasha Gordon", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Marcus Jahmal", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Cynthia Talmadge", "medium": "painting", "tags": "painting,figurative,contemporary"},
        {"name": "Susumu Kamijo", "medium": "painting", "tags": "painting,figurative,japanese contemporary"},
        {"name": "Stickymonger", "medium": "painting", "tags": "painting,figurative,korean contemporary"},
        {"name": "Aya Takano", "medium": "painting", "tags": "painting,figurative,japanese contemporary"},
        {"name": "Mr.", "medium": "painting", "tags": "painting,figurative,japanese contemporary"},
        {"name": "Roby Dwi Antono", "medium": "painting", "tags": "painting,figurative,indonesian contemporary"},
    ]


def run_discovery(db, target_count=200, delay=1.5):
    """
    Run full discovery pipeline to reach target artist count.

    Args:
        db: SQLite connection
        target_count: target number of tracked artists
        delay: seconds between API calls

    Returns:
        number of new artists added
    """
    from database import find_or_create_artist
    from scraper.artsy import fetch_artist_results

    # Get existing artists
    existing = set()
    rows = db.execute("SELECT LOWER(name) as name FROM artists").fetchall()
    for r in rows:
        existing.add(r["name"])

    current_count = len(existing)
    logger.info(f"Currently tracking {current_count} artists, target is {target_count}")

    if current_count >= target_count:
        logger.info("Already at target, nothing to do")
        return 0

    needed = target_count - current_count
    now = datetime.now().strftime("%Y-%m-%d")
    added = 0

    # Phase 1: Add curated artists
    logger.info("Phase 1: Adding curated emerging artists...")
    curated = discover_curated_artists()
    for artist_data in curated:
        if added >= needed:
            break
        name = artist_data["name"]
        if name.lower() in existing:
            continue

        medium = artist_data.get("medium", "")
        tags = artist_data.get("tags", "")

        artist_id = find_or_create_artist(
            db, name,
            medium=medium,
            tags=tags,
            first_seen_date=now,
            first_seen_source="discovery",
        )
        existing.add(name.lower())
        added += 1
        logger.info(f"  Added: {name} ({medium})")

    db.commit()
    logger.info(f"Phase 1 complete: added {added} curated artists")

    if added >= needed:
        return added

    # Phase 2: Search Artsy for more artists by gene/category
    logger.info("Phase 2: Searching Artsy genes for more artists...")
    genes = [
        "emerging-art", "contemporary-painting", "contemporary-figurative-painting",
        "abstract-painting", "contemporary-photography", "contemporary-sculpture",
        "street-art", "textile-art", "ceramics", "new-media-art",
        "african-contemporary-art", "south-asian-contemporary-art",
        "latin-american-contemporary-art", "east-asian-contemporary-art",
        "contemporary-portrait-painting", "works-on-paper",
    ]

    for gene_id in genes:
        if added >= needed:
            break

        discovered = discover_artists_from_gene(gene_id, first=50)
        time.sleep(delay)

        for artist in discovered:
            if added >= needed:
                break
            name = artist["name"]
            if name.lower() in existing:
                continue

            artist_id = find_or_create_artist(
                db, name,
                nationality=artist.get("nationality", ""),
                birth_year=artist.get("birth_year"),
                death_year=artist.get("death_year"),
                first_seen_date=now,
                first_seen_source="discovery-gene",
            )

            if artist.get("image_url"):
                db.execute(
                    "UPDATE artists SET image_url = ? WHERE id = ?",
                    (artist["image_url"], artist_id),
                )

            existing.add(name.lower())
            added += 1
            logger.info(f"  Added from gene '{gene_id}': {name}")

        db.commit()

    logger.info(f"Discovery complete: added {added} new artists (total: {len(existing)})")
    return added


def _parse_year(year_str):
    """Parse year from birthday/deathday string."""
    if not year_str:
        return None
    import re
    match = re.search(r"\d{4}", str(year_str))
    return int(match.group()) if match else None


def _get_image(node):
    """Extract image URL from artist node."""
    image = node.get("image", {})
    if image:
        cropped = image.get("cropped", {})
        if cropped:
            return cropped.get("url", "")
    return ""


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    from database import init_db, get_db
    init_db()

    with get_db() as db:
        added = run_discovery(db, target_count=200)
        total = db.execute("SELECT COUNT(*) as c FROM artists").fetchone()["c"]
        print(f"\nDone! Added {added} new artists. Total tracked: {total}")
