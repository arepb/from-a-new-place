#!/usr/bin/env python3
"""Seed the database with a starting watchlist of emerging artists.

These are artists who have been identified through various channels as
having early-stage market activity in the sub-$5K range. This list is
a starting point — the scrapers will discover more artists organically.

Selection criteria:
- Active contemporary artists (born after 1970)
- Work regularly appears at auction under $5K
- Showing at notable galleries or in significant exhibitions
- Represent diverse media and geographies
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import init_db, get_db, find_or_create_artist

# Curated seed list — a mix of artists to watch across media and markets
SEED_ARTISTS = [
    # Contemporary painting — emerging
    {"name": "Issy Wood", "nationality": "British", "birth_year": 1993, "medium": "painting", "tags": "painting,contemporary,figurative"},
    {"name": "Dominique Fung", "nationality": "Canadian", "birth_year": 1987, "medium": "painting", "tags": "painting,contemporary,surrealist"},
    {"name": "Cristina BanBan", "nationality": "Spanish", "birth_year": 1987, "medium": "painting", "tags": "painting,figurative,contemporary"},
    {"name": "Danielle Mckinney", "nationality": "American", "birth_year": 1981, "medium": "painting", "tags": "painting,figurative,contemporary"},
    {"name": "Emma Stern", "nationality": "American", "birth_year": 1992, "medium": "painting", "tags": "painting,digital,figurative"},
    {"name": "Claire Tabouret", "nationality": "French", "birth_year": 1981, "medium": "painting", "tags": "painting,figurative,contemporary"},
    {"name": "Michaela Yearwood-Dan", "nationality": "British", "birth_year": 1994, "medium": "painting", "tags": "painting,textile,mixed media"},
    {"name": "Allison Zuckerman", "nationality": "American", "birth_year": 1990, "medium": "painting", "tags": "painting,collage,digital"},

    # Photography — emerging
    {"name": "Paul Mpagi Sepuya", "nationality": "American", "birth_year": 1982, "medium": "photography", "tags": "photography,contemporary,portrait"},
    {"name": "Tyler Mitchell", "nationality": "American", "birth_year": 1995, "medium": "photography", "tags": "photography,fashion,contemporary"},
    {"name": "Maisie Cousins", "nationality": "British", "birth_year": 1992, "medium": "photography", "tags": "photography,still life,contemporary"},

    # Ceramics & sculpture — hot category
    {"name": "Lindsey Mendick", "nationality": "British", "birth_year": 1987, "medium": "ceramics", "tags": "ceramics,sculpture,contemporary"},
    {"name": "Genesis Belanger", "nationality": "American", "birth_year": 1978, "medium": "ceramics", "tags": "ceramics,sculpture,surrealist"},
    {"name": "Woody De Othello", "nationality": "American", "birth_year": 1991, "medium": "ceramics", "tags": "ceramics,sculpture,contemporary"},
    {"name": "Andile Dyalvane", "nationality": "South African", "birth_year": 1978, "medium": "ceramics", "tags": "ceramics,sculpture,african contemporary"},

    # Works on paper / prints — accessible price point
    {"name": "Toyin Ojih Odutola", "nationality": "Nigerian-American", "birth_year": 1985, "medium": "drawing", "tags": "drawing,works on paper,figurative"},
    {"name": "Christina Quarles", "nationality": "American", "birth_year": 1985, "medium": "painting", "tags": "painting,drawing,figurative,abstract"},
    {"name": "Kenturah Davis", "nationality": "American", "birth_year": 1980, "medium": "drawing", "tags": "drawing,portrait,contemporary"},

    # Textile & fiber art — undervalued category
    {"name": "Diedrick Brackens", "nationality": "American", "birth_year": 1989, "medium": "textile", "tags": "textile,weaving,contemporary"},
    {"name": "Billie Zangewa", "nationality": "Malawian", "birth_year": 1973, "medium": "textile", "tags": "textile,collage,figurative"},
    {"name": "Gio Swaby", "nationality": "Bahamian", "birth_year": 1991, "medium": "textile", "tags": "textile,mixed media,figurative"},

    # Digital / new media — watch category
    {"name": "Sara Ludy", "nationality": "American", "birth_year": 1980, "medium": "digital", "tags": "digital,new media,installation"},
    {"name": "Rachel Rossin", "nationality": "American", "birth_year": 1987, "medium": "digital", "tags": "digital,VR,painting"},

    # Global emerging — under-covered markets
    {"name": "Otis Kwame Kye Quaicoe", "nationality": "Ghanaian", "birth_year": 1988, "medium": "painting", "tags": "painting,figurative,african contemporary"},
    {"name": "Amani Lewis", "nationality": "American", "birth_year": 1994, "medium": "mixed media", "tags": "mixed media,painting,collage"},
    {"name": "Rafa Silvares", "nationality": "Brazilian", "birth_year": 1992, "medium": "painting", "tags": "painting,abstract,contemporary"},
    {"name": "Somaya Critchlow", "nationality": "British", "birth_year": 1993, "medium": "painting", "tags": "painting,figurative,contemporary"},
    {"name": "Jadé Fadojutimi", "nationality": "British", "birth_year": 1993, "medium": "painting", "tags": "painting,abstract,contemporary"},
    {"name": "Maria Berrio", "nationality": "Colombian", "birth_year": 1982, "medium": "collage", "tags": "collage,mixed media,figurative"},

    # Illustration / outsider — Heritage Auctions sweet spot
    {"name": "Jess Johnson", "nationality": "New Zealand", "birth_year": 1979, "medium": "drawing", "tags": "drawing,illustration,psychedelic"},
    {"name": "GucciGhost", "nationality": "American", "birth_year": 1984, "medium": "painting", "tags": "painting,street art,contemporary"},
]


def seed():
    init_db()
    now = datetime.now().strftime("%Y-%m-%d")
    count = 0

    with get_db() as db:
        for artist_data in SEED_ARTISTS:
            name = artist_data.pop("name")
            artist_data["first_seen_date"] = now
            artist_data["first_seen_source"] = "seed"
            artist_id = find_or_create_artist(db, name, **artist_data)
            count += 1

    print(f"Seeded {count} artists into the database.")


if __name__ == "__main__":
    seed()
