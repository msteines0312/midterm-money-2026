"""Checks for the billionaire money report (reports/billionaire-money.md).

These run on the real database and the committed research files, because the
point is to prove the committed report matches them:

- the committed numbers file equals a fresh build
- every number the JSON lists under `cited` appears in the report as written,
  with one test case per cited number so a failure names the number
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

from build_billionaire_report import (  # noqa: E402
    BUILDER_PATH_NAME,
    NUMBERS_PATH,
    REPORT_PATH,
    build,
    money,
    percent,
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
    """A fresh build from the database, and the committed outputs."""
    numbers, _ = build()
    committed = json.loads(NUMBERS_PATH.read_text(encoding="utf-8"))
    report = REPORT_PATH.read_text(encoding="utf-8")
    return numbers, committed, report


@needs_database
@needs_report
def test_committed_numbers_match_a_fresh_build(built):
    numbers, committed, _ = built
    # Round-trip through JSON so tuples and lists compare the same way
    assert json.loads(json.dumps(numbers, ensure_ascii=False)) == committed


@needs_report
@pytest.mark.parametrize("key", cited_keys())
def test_every_cited_number_appears_in_the_report(key):
    committed = json.loads(NUMBERS_PATH.read_text(encoding="utf-8"))
    report = REPORT_PATH.read_text(encoding="utf-8")
    assert committed["cited"][key] in report, f"{key}: {committed['cited'][key]!r} not in the report"


@needs_report
def test_no_pac_is_called_backed_without_reconciling():
    """The rule from the design: a PAC that does not reconcile is never called backed."""
    committed = json.loads(NUMBERS_PATH.read_text(encoding="utf-8"))
    for row in committed["pacs"]["list"]:
        if row["status"] == "backed":
            assert abs(row["diff_pct"]) <= 0.05, f"{row['pac']} is backed but does not reconcile"


def test_money_formatting():
    assert money(52_900_000) == "$52.9M"
    assert money(850_000) == "$850K"
    assert percent(0.424) == "42%"


@pytest.mark.parametrize("path", [REPORT_PATH, BUILDER_PATH, Path(__file__)])
def test_no_em_dashes(path):
    if not path.exists():
        pytest.skip(f"{path.name} not written yet")
    assert EM_DASH not in path.read_text(encoding="utf-8")
