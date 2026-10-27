"""Tests for src/fec/bulk.py, run against real rows from the FEC's webl26 file."""

from pathlib import Path

import pytest

from src.fec.bulk import SUMMARY_COLUMNS, house_totals, parse_summary

SAMPLE = (Path(__file__).parent / "fixtures" / "webl_sample.txt").read_text(encoding="latin-1")

TOTALS_COLUMNS = {
    "candidate_id", "pulled_at", "coverage_end_date", "receipts", "disbursements",
    "cash_on_hand", "debts_owed", "individual_contributions", "pac_contributions",
    "party_contributions", "candidate_self_funding", "external_contributions",
}


@pytest.fixture
def totals():
    return {row["candidate_id"]: row for row in house_totals(SAMPLE, "2026-10-21")}


def test_parse_summary_names_all_30_columns():
    rows = parse_summary(SAMPLE)
    assert len(SUMMARY_COLUMNS) == 30
    assert rows[0]["CAND_ID"] == "H6KY06259"
    assert rows[0]["CAND_CONTRIB"] == "3300000"


def test_house_totals_drops_senate_rows(totals):
    assert set(totals) == {"H6KY06259", "H6FL13239", "H2AK01083"}


def test_rows_match_table_columns(totals):
    assert all(set(row) == TOTALS_COLUMNS for row in totals.values())


def test_self_funder_is_not_counted_as_external_money(totals):
    # Arquette put in $3.3M of their own money plus a $29K loan and raised
    # $1.66M from donors. Only the donor money is external fundraising.
    row = totals["H6KY06259"]
    assert row["receipts"] == 4990948.0
    assert row["candidate_self_funding"] == 3329000.0
    assert row["external_contributions"] == 1661948.0


def test_external_contributions_subtracts_refunds(totals):
    # Begich: individuals 3,248,372.14 - refunds to individuals 69,157.27
    # + PACs 1,213,077 + party 10,250 - refunds to committees 4,382.86
    assert totals["H2AK01083"]["external_contributions"] == pytest.approx(4398159.01)


def test_negative_cash_and_debts_are_kept(totals):
    row = totals["H6FL13239"]
    assert row["cash_on_hand"] == -10737.84
    assert row["debts_owed"] == 10000.0


def test_coverage_end_date_is_iso(totals):
    assert totals["H6KY06259"]["coverage_end_date"] == "2026-05-04"
    assert totals["H6FL13239"]["coverage_end_date"] == "2026-09-30"


def test_missing_coverage_date_stays_null():
    line = SAMPLE.splitlines()[0].split("|")
    line[27] = ""  # CVG_END_DT
    rows = house_totals("|".join(line) + "\n", "2026-10-21")
    assert rows[0]["coverage_end_date"] is None
