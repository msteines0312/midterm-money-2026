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
PROCESSED_DIR = DATA_DIR / "processed"
DB_PATH = PROCESSED_DIR / "midterm_money.db"

FEC_BASE_URL = "https://api.open.fec.gov/v1"
CYCLE = 2026

# Cook ratings and PVI, read from Wikipedia because Cook's own lists are
# paywalled and block scripts. Two pages are needed: the ratings page lists
# only competitive seats, and the main elections page has every district's
# PVI. Revision IDs are pinned so the exact same tables can be downloaded again.
WIKIPEDIA_DIR = RAW_DIR / "wikipedia"
COOK_RATINGS_PAGE = ("2026_United_States_House_of_Representatives_election_ratings", 1381240142)
PVI_PAGE = ("2026_United_States_House_of_Representatives_elections", 1380949529)


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
