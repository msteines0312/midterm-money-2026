"""Checks for the money and winning report (reports/money-and-winning.md).

These run on the real frozen prediction files, not fixtures, because the
point is to prove the committed report matches them:

- the committed numbers file equals a fresh build from the frozen files
- every number the JSON lists under `cited` appears in the report as written
- the report and its builder contain no em dashes
"""

import json
import sys
from pathlib import Path

import pytest

# Let the test import the script directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_money_winning_report import FIGURES_DIR, REPORT_PATH, build, points  # noqa: E402

NUMBERS_PATH = FIGURES_DIR / "money_winning_numbers.json"
BUILDER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_money_winning_report.py"
EM_DASH = chr(0x2014)  # written as a code point so this file has none itself


@pytest.fixture(scope="module")
def built():
    """A fresh build from the frozen files, and the committed outputs."""
    _, numbers = build()
    committed = json.loads(NUMBERS_PATH.read_text(encoding="utf-8"))
    report = REPORT_PATH.read_text(encoding="utf-8")
    return numbers, committed, report


def test_committed_numbers_match_a_fresh_build(built):
    numbers, committed, _ = built
    # Round-trip through JSON so tuples and lists compare the same way
    assert json.loads(json.dumps(numbers, ensure_ascii=False)) == committed


@pytest.mark.parametrize("key", sorted(json.loads(NUMBERS_PATH.read_text(encoding="utf-8"))["cited"]))
def test_every_cited_number_appears_in_the_report(built, key):
    _, committed, report = built
    assert committed["cited"][key] in report, f"{key}: {committed['cited'][key]!r} not in the report"


def test_disagreement_tables_are_complete(built):
    # The spec says the money-versus-Cook disagreements are published in full
    _, committed, _ = built
    assert len(committed["simple"]["disagreements"]) == committed["simple"]["disagree"]


def test_toss_up_incumbent_claim_holds(built):
    # The report says the model favors the incumbent's party in every Toss Up with an incumbent
    toss_ups = built[1]["predictions_2026"]["toss_ups"]
    assert toss_ups["incumbent_party_favored"] == toss_ups["with_incumbent"]


def test_points_formatting():
    assert points(0.144) == "+14.4"
    assert points(-0.041) == "-4.1"
    assert points(0.0) == "0.0"


@pytest.mark.parametrize("path", [REPORT_PATH, BUILDER_PATH, Path(__file__)])
def test_no_em_dashes(path):
    assert EM_DASH not in path.read_text(encoding="utf-8")
