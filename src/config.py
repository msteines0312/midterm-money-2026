"""Project paths and constants.

Every other module imports paths from here, so nothing in the project
hardcodes a file location and the code runs on any machine.
"""

import os
from pathlib import Path

from dotenv import dotenv_values

# config.py lives in src/, so the project root is one folder up
PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
# Hand-built CSVs (PAC industry labels, endorsements). Small, sourced, and committed.
MANUAL_DIR = DATA_DIR / "manual"
PAC_INDUSTRIES_CSV = MANUAL_DIR / "pac_industries.csv"
NOMINEE_MATCHES_CSV = MANUAL_DIR / "nominee_matches.csv"
# Hand-checked FEC IDs for 2022 and 2024 results rows the automatic match misses
HISTORY_MATCHES_CSV = MANUAL_DIR / "history_matches.csv"
PROCESSED_DIR = DATA_DIR / "processed"
DB_PATH = PROCESSED_DIR / "midterm_money.db"
# --sample runs write here so a partial pull never looks like a real snapshot
SAMPLE_DB_PATH = PROCESSED_DIR / "midterm_money_sample.db"

FEC_BASE_URL = "https://api.open.fec.gov/v1"
CYCLE = 2026

# Cook ratings and PVI, read from Wikipedia because Cook's own lists are
# paywalled and block scripts. Two pages are needed: the ratings page lists
# only competitive seats, and the main elections page has every district's
# PVI. Revision IDs are pinned so the exact same tables can be downloaded again.
WIKIPEDIA_DIR = RAW_DIR / "wikipedia"
COOK_RATINGS_PAGE = ("2026_United_States_House_of_Representatives_election_ratings", 1381240142)
PVI_PAGE = ("2026_United_States_House_of_Representatives_elections", 1380949529)
# Latest revision at fetch time (2026-10-24), pinned for the November nominees.
# Separate from PVI_PAGE because nominees change as primaries and runoffs finish.
NOMINEES_PAGE = ("2026_United_States_House_of_Representatives_elections", 1381568365)

# Past cycles for training the money model. Each cycle's pages are pinned to
# the last revision before election day (Nov 8, 2022 and Nov 5, 2024, at
# 00:00 UTC), found with the MediaWiki API (prop=revisions, rvstart, rvdir=older),
# so the PVI and ratings are what was known before any votes were counted.
HISTORY_CYCLES = (2022, 2024)
HISTORY_PVI_PAGES = {
    2022: ("2022_United_States_House_of_Representatives_elections", 1120557329),
    2024: ("2024_United_States_House_of_Representatives_elections", 1255162576),
}
HISTORY_RATINGS_PAGES = {
    2022: ("2022_United_States_House_of_Representatives_election_ratings", 1120614900),
    2024: ("2024_United_States_House_of_Representatives_election_ratings", 1255439657),
}

# Official House results, from the FEC's "Federal Elections" publication.
# Its House sheet has an FEC candidate ID on every row. The FEC had not
# published a 2024 edition as of October 2026.
RESULTS_DIR = RAW_DIR / "results"
FEC_RESULTS_URLS = {
    2022: "https://www.fec.gov/documents/5676/federalelections2022.xlsx",
}
# Fallback for 2024: the elections page's per-state tables after certification,
# pinned to the first revision on or after Jan 3, 2025 (found with the
# MediaWiki API, rvdir=newer). They list each candidate's vote share, not
# counts, and mark the winner with a check mark. The MIT Election Lab file
# (doi:10.7910/DVN/IG0UN2) needs a personal sign-in form to download.
WIKI_RESULTS_PAGES = {
    2024: ("2024_United_States_House_of_Representatives_elections", 1267103610),
}


def load_api_key(env_path=None):
    """Read the OpenFEC API key from a .env file or the environment.

    Parameters
    ----------
    env_path : pathlib.Path, optional
        File to read. Defaults to `.env` in the project root.

    Returns
    -------
    str
        The API key.

    Raises
    ------
    RuntimeError
        If no key is set, with instructions for getting one.
    """
    env = dotenv_values(env_path or PROJECT_ROOT / ".env")
    key = env.get("FEC_API_KEY") or os.environ.get("FEC_API_KEY")
    if not key:
        raise RuntimeError(
            "FEC_API_KEY is not set. Copy .env.example to .env and add a free "
            "key from https://api.data.gov/signup/"
        )
    return key
