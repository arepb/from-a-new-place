#!/usr/bin/env python3
"""Backfill artist nationality and birth year from Wikipedia.

Parses Wikipedia API (extracts + infobox) to get birth year and nationality
for artists who have a wikipedia_url but are missing this bio data.
"""

import sys
import os
import re
import json
import time
import logging
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import get_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_bio")

HEADERS = {"User-Agent": "FromANewPlace/1.0 (art tracker)"}

# Map of common nationality adjectives to country names
NATIONALITY_MAP = {
    "american": "American",
    "british": "British",
    "english": "British",
    "scottish": "British",
    "welsh": "British",
    "french": "French",
    "german": "German",
    "italian": "Italian",
    "spanish": "Spanish",
    "japanese": "Japanese",
    "chinese": "Chinese",
    "korean": "South Korean",
    "south korean": "South Korean",
    "canadian": "Canadian",
    "australian": "Australian",
    "mexican": "Mexican",
    "brazilian": "Brazilian",
    "colombian": "Colombian",
    "venezuelan": "Venezuelan",
    "cuban": "Cuban",
    "puerto rican": "Puerto Rican",
    "dominican": "Dominican",
    "argentinian": "Argentinian",
    "argentine": "Argentinian",
    "peruvian": "Peruvian",
    "chilean": "Chilean",
    "dutch": "Dutch",
    "belgian": "Belgian",
    "swiss": "Swiss",
    "austrian": "Austrian",
    "swedish": "Swedish",
    "norwegian": "Norwegian",
    "danish": "Danish",
    "finnish": "Finnish",
    "icelandic": "Icelandic",
    "irish": "Irish",
    "polish": "Polish",
    "czech": "Czech",
    "romanian": "Romanian",
    "hungarian": "Hungarian",
    "greek": "Greek",
    "portuguese": "Portuguese",
    "turkish": "Turkish",
    "russian": "Russian",
    "ukrainian": "Ukrainian",
    "israeli": "Israeli",
    "indian": "Indian",
    "pakistani": "Pakistani",
    "iranian": "Iranian",
    "iraqi": "Iraqi",
    "lebanese": "Lebanese",
    "egyptian": "Egyptian",
    "south african": "South African",
    "nigerian": "Nigerian",
    "ghanaian": "Ghanaian",
    "kenyan": "Kenyan",
    "ethiopian": "Ethiopian",
    "tanzanian": "Tanzanian",
    "ugandan": "Ugandan",
    "senegalese": "Senegalese",
    "cameroonian": "Cameroonian",
    "congolese": "Congolese",
    "moroccan": "Moroccan",
    "tunisian": "Tunisian",
    "algerian": "Algerian",
    "ivorian": "Ivorian",
    "côte d'ivoire": "Ivorian",
    "taiwanese": "Taiwanese",
    "thai": "Thai",
    "vietnamese": "Vietnamese",
    "filipino": "Filipino",
    "indonesian": "Indonesian",
    "malaysian": "Malaysian",
    "singaporean": "Singaporean",
    "new zealand": "New Zealander",
    "new zealander": "New Zealander",
    "jamaican": "Jamaican",
    "trinidadian": "Trinidadian",
    "haitian": "Haitian",
    "guatemalan": "Guatemalan",
    "costa rican": "Costa Rican",
    "panamanian": "Panamanian",
    "ecuadorian": "Ecuadorian",
    "bolivian": "Bolivian",
    "uruguayan": "Uruguayan",
    "paraguayan": "Paraguayan",
    "serbian": "Serbian",
    "croatian": "Croatian",
    "bosnian": "Bosnian",
    "slovenian": "Slovenian",
    "albanian": "Albanian",
    "bulgarian": "Bulgarian",
    "slovak": "Slovak",
    "latvian": "Latvian",
    "lithuanian": "Lithuanian",
    "estonian": "Estonian",
    "georgian": "Georgian",
    "armenian": "Armenian",
    "azerbaijani": "Azerbaijani",
    "belarusian": "Belarusian",
    "kazakh": "Kazakh",
    "uzbek": "Uzbek",
    "scottish-american": "Scottish-American",
    "african american": "American",
    "african-american": "American",
    "eritrean": "Eritrean",
    "somali": "Somali",
    "sudanese": "Sudanese",
    "zimbabwean": "Zimbabwean",
    "mozambican": "Mozambican",
    "zambian": "Zambian",
    "malawian": "Malawian",
    "rwandan": "Rwandan",
    "burundian": "Burundian",
    "angolan": "Angolan",
    "namibian": "Namibian",
    "botswanan": "Botswanan",
    "liberian": "Liberian",
    "sierra leonean": "Sierra Leonean",
    "togolese": "Togolese",
    "beninese": "Beninese",
    "malian": "Malian",
    "burkinabé": "Burkinabé",
    "nigerien": "Nigerien",
    "chadian": "Chadian",
    "gabonese": "Gabonese",
}


def extract_title_from_url(wiki_url):
    """Extract the Wikipedia article title from a URL."""
    # https://en.wikipedia.org/wiki/Futura_(artist) -> Futura_(artist)
    match = re.search(r'/wiki/(.+)$', wiki_url)
    if match:
        return requests.utils.unquote(match.group(1))
    return None


def fetch_wikipedia_data(wiki_title):
    """Fetch extract and infobox data from Wikipedia API."""
    # Get the plain text extract (first few sentences)
    params = {
        "action": "query",
        "titles": wiki_title,
        "prop": "extracts|revisions",
        "exintro": True,
        "explaintext": True,
        "rvprop": "content",
        "rvslots": "main",
        "rvsection": "0",
        "format": "json",
        "redirects": 1,
    }

    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params=params,
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Wikipedia API error for {wiki_title}: {e}")
        return None, None

    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None, None

    page = list(pages.values())[0]
    if page.get("missing") is not None:
        return None, None

    extract = page.get("extract", "")

    # Get the wikitext of section 0 for infobox parsing
    wikitext = ""
    revisions = page.get("revisions", [])
    if revisions:
        slots = revisions[0].get("slots", {})
        main = slots.get("main", {})
        wikitext = main.get("*", "")

    return extract, wikitext


def parse_birth_year(extract, wikitext):
    """Extract birth year from Wikipedia extract or infobox."""
    birth_year = None

    # Try infobox first: | birth_date = {{birth date and age|1955|1|17}}
    # or | birth_date = {{Birth date|1955|1|17}}
    infobox_match = re.search(
        r'\|\s*birth_date\s*=\s*\{\{[Bb]irth[ _]date(?:[ _]and[ _]age)?\|(\d{4})',
        wikitext
    )
    if infobox_match:
        birth_year = int(infobox_match.group(1))
        return birth_year

    # Try infobox plain date: | birth_date = January 17, 1955
    infobox_date = re.search(
        r'\|\s*birth_date\s*=\s*.*?(\d{4})',
        wikitext
    )
    if infobox_date:
        year = int(infobox_date.group(1))
        if 1900 <= year <= 2010:
            birth_year = year
            return birth_year

    # Try extract: "born January 17, 1955" or "(born 1955)"
    born_match = re.search(r'\(born\s+(?:\w+\s+\d{1,2},?\s+)?(\d{4})\)', extract)
    if born_match:
        birth_year = int(born_match.group(1))
        return birth_year

    # Try: "born on January 17, 1955"
    born_match2 = re.search(r'born\s+(?:on\s+)?(?:\w+\s+\d{1,2},?\s+)?(\d{4})', extract)
    if born_match2:
        year = int(born_match2.group(1))
        if 1900 <= year <= 2010:
            birth_year = year
            return birth_year

    # Try: "(1955–2020)" or "(1955 –" pattern for birth-death
    lifespan = re.search(r'\((\d{4})\s*[–—-]', extract)
    if lifespan:
        year = int(lifespan.group(1))
        if 1900 <= year <= 2010:
            birth_year = year
            return birth_year

    # Try: "b. 1955"
    b_match = re.search(r'\bb\.\s*(\d{4})\b', extract)
    if b_match:
        year = int(b_match.group(1))
        if 1900 <= year <= 2010:
            birth_year = year
            return birth_year

    return birth_year


def parse_nationality(extract, wikitext):
    """Extract nationality from Wikipedia extract or infobox."""
    nationality = None

    # Try infobox: | nationality = American
    infobox_nat = re.search(
        r'\|\s*nationality\s*=\s*\[?\[?([A-Za-z\s\'-]+?)(?:\]?\]?)?\s*(?:\n|\|)',
        wikitext
    )
    if infobox_nat:
        nat_text = infobox_nat.group(1).strip().rstrip(']').strip()
        # Clean up wiki markup
        nat_text = re.sub(r'\[+|\]+', '', nat_text).strip()
        if nat_text and len(nat_text) < 30:
            nationality = nat_text
            return nationality

    # Try extract first sentence for nationality patterns
    # "is an American artist" or "is a Japanese painter"
    first_sentence = extract.split('.')[0] if extract else ""

    # Match nationality adjectives
    for adj, nat in sorted(NATIONALITY_MAP.items(), key=lambda x: -len(x[0])):
        # Look for the nationality adjective in the first sentence
        pattern = r'\b' + re.escape(adj) + r'\b'
        if re.search(pattern, first_sentence, re.IGNORECASE):
            nationality = nat
            return nationality

    # Try: "born in [City], [Country]" or "born in [Country]"
    born_in = re.search(
        r'born\s+in\s+(?:[\w\s]+,\s+)?(United States|United Kingdom|France|Germany|Italy|'
        r'Japan|China|Canada|Australia|Mexico|Brazil|South Korea|Nigeria|Ghana|'
        r'South Africa|India|Kenya|Ethiopia|Colombia|Cuba|Puerto Rico|Trinidad|'
        r'Jamaica|Haiti|Egypt|Iran|Israel|Turkey|Russia|Ukraine|Poland|'
        r'Netherlands|Belgium|Switzerland|Austria|Sweden|Norway|Denmark|Finland|'
        r'Ireland|Czech Republic|Romania|Hungary|Greece|Portugal|New Zealand|'
        r'Philippines|Indonesia|Vietnam|Thailand|Taiwan|Singapore|Malaysia)',
        first_sentence, re.IGNORECASE
    )
    if born_in:
        country = born_in.group(1).strip()
        country_to_nat = {
            "United States": "American",
            "United Kingdom": "British",
            "France": "French",
            "Germany": "German",
            "Italy": "Italian",
            "Japan": "Japanese",
            "China": "Chinese",
            "Canada": "Canadian",
            "Australia": "Australian",
            "Mexico": "Mexican",
            "Brazil": "Brazilian",
            "South Korea": "South Korean",
            "Nigeria": "Nigerian",
            "Ghana": "Ghanaian",
            "South Africa": "South African",
            "India": "Indian",
            "Kenya": "Kenyan",
            "Ethiopia": "Ethiopian",
            "Colombia": "Colombian",
            "Cuba": "Cuban",
            "Puerto Rico": "Puerto Rican",
            "Trinidad": "Trinidadian",
            "Jamaica": "Jamaican",
            "Haiti": "Haitian",
            "Egypt": "Egyptian",
            "Iran": "Iranian",
            "Israel": "Israeli",
            "Turkey": "Turkish",
            "Russia": "Russian",
            "Ukraine": "Ukrainian",
            "Poland": "Polish",
            "Netherlands": "Dutch",
            "Belgium": "Belgian",
            "Switzerland": "Swiss",
            "Austria": "Austrian",
            "Sweden": "Swedish",
            "Norway": "Norwegian",
            "Denmark": "Danish",
            "Finland": "Finnish",
            "Ireland": "Irish",
            "Czech Republic": "Czech",
            "Romania": "Romanian",
            "Hungary": "Hungarian",
            "Greece": "Greek",
            "Portugal": "Portuguese",
            "New Zealand": "New Zealander",
            "Philippines": "Filipino",
            "Indonesia": "Indonesian",
            "Vietnam": "Vietnamese",
            "Thailand": "Thai",
            "Taiwan": "Taiwanese",
            "Singapore": "Singaporean",
            "Malaysia": "Malaysian",
        }
        nationality = country_to_nat.get(country, country)
        return nationality

    return nationality


def backfill_all():
    """Backfill bio data for all artists with Wikipedia URLs but missing data."""
    with get_db() as db:
        artists = db.execute("""
            SELECT id, name, nationality, birth_year, wikipedia_url
            FROM artists
            WHERE wikipedia_url IS NOT NULL AND wikipedia_url != ''
            AND (nationality IS NULL OR nationality = '' OR birth_year IS NULL)
            ORDER BY name
        """).fetchall()

    logger.info(f"Found {len(artists)} artists needing bio backfill")

    updated_count = 0
    nat_count = 0
    year_count = 0

    for i, artist in enumerate(artists):
        wiki_title = extract_title_from_url(artist["wikipedia_url"])
        if not wiki_title:
            logger.warning(f"Could not extract title from {artist['wikipedia_url']}")
            continue

        logger.info(f"[{i+1}/{len(artists)}] {artist['name']} → {wiki_title}")

        extract, wikitext = fetch_wikipedia_data(wiki_title)
        if not extract and not wikitext:
            logger.warning(f"  No data found for {artist['name']}")
            time.sleep(0.5)
            continue

        updates = {}

        # Only fill in missing fields
        if not artist["birth_year"]:
            birth_year = parse_birth_year(extract or "", wikitext or "")
            if birth_year:
                updates["birth_year"] = birth_year
                year_count += 1
                logger.info(f"  Birth year: {birth_year}")

        if not artist["nationality"] or artist["nationality"] == "":
            nationality = parse_nationality(extract or "", wikitext or "")
            if nationality:
                updates["nationality"] = nationality
                nat_count += 1
                logger.info(f"  Nationality: {nationality}")

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            values = list(updates.values()) + [artist["id"]]
            with get_db() as db:
                db.execute(
                    f"UPDATE artists SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
                    values,
                )
            updated_count += 1
        else:
            logger.info(f"  No data extracted")

        # Be respectful of Wikipedia's API
        time.sleep(0.3)

    logger.info("")
    logger.info("=" * 50)
    logger.info("BACKFILL COMPLETE")
    logger.info(f"  Artists processed: {len(artists)}")
    logger.info(f"  Artists updated:   {updated_count}")
    logger.info(f"  Nationalities:     {nat_count}")
    logger.info(f"  Birth years:       {year_count}")
    logger.info("=" * 50)


if __name__ == "__main__":
    backfill_all()
