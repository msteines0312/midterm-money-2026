"""Checks for the endorsements report (reports/endorsements.md).

These run on the real database and the committed research files, because the
point is to prove the committed report matches them:

- the committed numbers file equals a fresh build
- every number the JSON lists under `cited` appears in the report as written,
  with one test case per cited number so a failure names the number
- every scored Trump outcome agrees with Ballotpedia's own result
- the report and its builder contain no em dashes

The database is not committed, so the first group is skipped on a machine
that has not run the pipeline.
"""

import json
import sys
from pathlib import Path

import pytest

# Let the test import the script directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_endorsements_report import (  # noqa: E402
    BUILDER_PATH_NAME,
    NUMBERS_PATH,
    REPORT_PATH,
    build,
    rate_text,
    slug,
    source_says,
)
from src.config import DB_PATH  # noqa: E402

BUILDER_PATH = Path(__file__).resolve().parents[1] / "scripts" / BUILDER_PATH_NAME
EM_DASH = chr(0x2014)  # written as a code point so this file has none itself

needs_database = pytest.mark.skipif(not Path(DB_PATH).exists(), reason="database not built on this machine")
needs_report = pytest.mark.skipif(not NUMBERS_PATH.exists(), reason="report not written yet")


def cited_keys():
    """Names of the cited numbers, read from the committed file at collection time."""
    if not NUMBERS_PATH.exists():
        return []
    return sorted(json.loads(NUMBERS_PATH.read_text(encoding="utf-8"))["cited"])


@pytest.fixture(scope="module")
def built():
    """A fresh build from the database, and the committed numbers."""
    numbers, _ = build()
    committed = json.loads(NUMBERS_PATH.read_text(encoding="utf-8"))
    return numbers, committed


@needs_database
@needs_report
def test_committed_numbers_match_a_fresh_build(built):
    numbers, committed = built
    # Round-trip through JSON so tuples and lists compare the same way
    assert json.loads(json.dumps(numbers, ensure_ascii=False)) == committed


@needs_report
@pytest.mark.parametrize("key", cited_keys())
def test_every_cited_number_appears_in_the_report(key):
    committed = json.loads(NUMBERS_PATH.read_text(encoding="utf-8"))
    report = REPORT_PATH.read_text(encoding="utf-8")
    assert committed["cited"][key] in report, f"{key}: {committed['cited'][key]!r} not in the report"


@needs_report
def test_scored_outcomes_agree_with_the_source():
    """Ballotpedia's own result is an independent check on the nominee-based scoring."""
    check = json.loads(NUMBERS_PATH.read_text(encoding="utf-8"))["source_check"]
    assert check["compared"] > 0
    assert check["disagree"] == []


def test_source_says_reads_ballotpedia_outcomes():
    assert source_says("Won primary runoff") == "won"
    assert source_says("Not on the ballot general") == "won"
    assert source_says("Not on the ballot primary") == "withdrew"
    assert source_says("Not on the ballot primary runoff") == "lost"
    assert source_says("Lost primary") == "lost"
    assert source_says("") == ""


def test_rate_text_and_slug():
    assert rate_text({"rate": 76 / 81, "won": 76, "lost": 5}) == "94% (76 of 81)"
    assert slug("Club for Growth PAC") == "club_for_growth_pac"


@pytest.mark.parametrize("path", [REPORT_PATH, BUILDER_PATH, Path(__file__)])
def test_no_em_dashes(path):
    if not path.exists():
        pytest.skip(f"{path.name} not written yet")
    assert EM_DASH not in path.read_text(encoding="utf-8")
