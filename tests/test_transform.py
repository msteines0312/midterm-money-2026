"""Tests for src/fec/transform.py, run against real saved API responses."""

import json
from pathlib import Path

import pytest

from src.fec.transform import (
    candidate_row,
    committee_row,
    outside_spending_row,
    race_id,
    to_money,
)

FIXTURES = Path(__file__).parent / "fixtures"

CANDIDATE_COLUMNS = {
    "candidate_id", "name", "party", "state", "district", "race_id",
    "incumbent_challenge", "primary_result",
}
COMMITTEE_COLUMNS = {"committee_id", "name", "committee_type", "designation"}
SPENDING_COLUMNS = {"committee_id", "candidate_id", "support_oppose", "pulled_at", "total", "count"}


def first_record(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())["results"][0]


@pytest.mark.parametrize("state, district, expected", [
    ("CA", "7", "CA-07"), ("CA", "07", "CA-07"),
    ("AK", "00", "AK-00"), ("AK", "0", "AK-00"), ("WY", None, "WY-00"), ("DC", "00", "DC-00"),
])
def test_race_id(state, district, expected):
    assert race_id(state, district) == expected


@pytest.mark.parametrize("raw, expected", [("0.04", 0.04), (1250.5, 1250.5), (0, 0.0), (None, None)])
def test_to_money(raw, expected):
    assert to_money(raw) == expected


def test_candidate_row_from_fixture():
    rec = first_record("candidates")
    row = candidate_row(rec)
    assert set(row) == CANDIDATE_COLUMNS
    assert row["primary_result"] is None
    assert row["race_id"] == race_id(rec["state"], rec["district"])


def test_committee_row_from_fixture():
    assert set(committee_row(first_record("committees"))) == COMMITTEE_COLUMNS


def test_outside_spending_row_from_fixture():
    row = outside_spending_row(first_record("outside_spending"), "2026-10-20")
    assert set(row) == SPENDING_COLUMNS
    assert row["support_oppose"] in {"S", "O"}
    assert row["pulled_at"] == "2026-10-20"
