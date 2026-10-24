"""Tests for the date filter and sum in scripts/check_outside_spending.py.

Uses the two real CLF (C00504530) rows in tests/fixtures/ie_sample.csv:
$20,500 spent 21-OCT-26 and $100,000 spent 20-OCT-26, both disseminated 21-OCT-26.
"""

import sys
from datetime import date
from pathlib import Path

# Let the test import the script directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_outside_spending import bulk_sum_through  # noqa: E402
from src.fec.independent_expenditures import parse_independent_expenditures  # noqa: E402

SAMPLE = (Path(__file__).parent / "fixtures" / "ie_sample.csv").read_text(encoding="latin-1")
ROWS = parse_independent_expenditures(SAMPLE)


def test_dates_rows_by_expenditure_date_not_dissemination_date():
    # Only the $100,000 row was spent on or before Oct 20, even though both were disseminated Oct 21
    assert bulk_sum_through(ROWS, "C00504530", date(2026, 10, 20)) == 100000.0


def test_includes_everything_on_or_before_the_cutoff_day():
    assert bulk_sum_through(ROWS, "C00504530", date(2026, 10, 21)) == 120500.0


def test_other_committees_are_not_counted():
    assert bulk_sum_through(ROWS, "C00000000", date(2026, 12, 31)) == 0.0
