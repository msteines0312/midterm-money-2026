"""Tests for src/nominees.py.

The fixture holds real rows cut from the pinned Wikipedia revision: Alabama 1
and 2, three California races (one Democrat-Republican, two same-party),
Alaska's at-large seat, a single-nominee race (Wisconsin 2), and Tennessee 4,
where one nominee sits outside the list markup.
"""

from pathlib import Path

import pytest

from src.nominees import parse_nominees

FIXTURE = Path(__file__).parent / "fixtures" / "nominees_sample.html"


@pytest.fixture(scope="module")
def nominees():
    return parse_nominees(FIXTURE.read_text(encoding="utf-8"))


def for_race(nominees, race_id):
    return [(n["name"], n["party"]) for n in nominees if n["race_id"] == race_id]


def test_two_nominees_with_party(nominees):
    assert for_race(nominees, "AL-02") == [
        ("Shomari Figures", "Democratic"),
        ("Rhett Marques", "Republican"),
    ]


def test_at_large_race_id(nominees):
    assert {n["race_id"] for n in nominees if n["race_id"].startswith("AK")} == {"AK-00"}


def test_same_party_race_kept(nominees):
    # California's top-two primary can send two Democrats to November
    assert for_race(nominees, "CA-04") == [
        ("Eric Jones", "Democratic"),
        ("Mike Thompson", "Democratic"),
    ]
    assert [p for _, p in for_race(nominees, "CA-40")] == ["Republican", "Republican"]


def test_single_nominee_race(nominees):
    assert for_race(nominees, "WI-02") == [("Mark Pocan", "Democratic")]


def test_unconfirmed_status(nominees):
    # The pinned revision has no candidate cell with a pending runoff, TBD,
    # or withdrawal, so every real row is confirmed. See the fixture comment.
    assert {n["status"] for n in nominees} == {"confirmed"}
    pytest.skip("No unconfirmed row exists in the pinned revision to test against")


def test_footnotes_stripped(nominees):
    for nominee in nominees:
        assert "▌" not in nominee["name"]
        assert "[" not in nominee["name"]
        assert "(" not in nominee["name"]
        assert nominee["name"] == nominee["name"].strip()


def test_nominee_outside_list_markup_is_kept(nominees):
    # Clay Faircloth is plain text after the list in the real Tennessee 4 cell
    assert len(for_race(nominees, "TN-04")) == 4
    assert ("Clay Faircloth", "Independent") in for_race(nominees, "TN-04")


def test_only_candidate_tables_are_read(nominees):
    # Alabama 1 appears once, and the fixture holds only these races
    assert {n["race_id"] for n in nominees} == {
        "AL-01", "AL-02", "CA-01", "CA-04", "CA-40", "AK-00", "WI-02", "TN-04"
    }
