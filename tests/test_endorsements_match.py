"""Tests for src/endorsements_match.py.

The parser tests run on trimmed copies of the real list pages in
tests/fixtures/. The matching tests use real rows from the candidates table.
"""

from pathlib import Path

import pandas as pd

from src.endorsements_match import (
    _parse_office,
    house_only,
    listing_date,
    match_candidates,
    parse_endorsement_list,
    truth_social_date,
)

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


# Real rows from the candidates table (2026 pull)
CANDIDATES = pd.DataFrame(
    [
        ("H0AL01055", "CARL, JERRY LEE, JR", "REP", "AL", "01", "AL-01", "O"),
        ("H6AL01136", "MILLS, RALPH JOHN III", "REP", "AL", "01", "AL-01", "O"),
        ("H8AL02171", "MOORE, FELIX BARRY", "REP", "AL", "01", "AL-01", "I"),
        ("H2MI07123", "BARRETT, THOMAS MORE", "REP", "MI", "07", "MI-07", "I"),
        ("H6MI07298", "LAWRENCE, WILLIAM", "DEM", "MI", "07", "MI-07", "C"),
    ],
    columns=["candidate_id", "name", "party", "state", "district", "race_id", "incumbent_challenge"],
)


def test_truth_social_date_reads_the_post_id():
    # Mastodon IDs carry the post time in milliseconds in their top 48 bits
    assert truth_social_date("https://truthsocial.com/@realDonaldTrump/posts/116795239595013935") == "2026-06-22"
    assert truth_social_date("https://sports.yahoo.com/some-story") == ""


def test_trump_parser_reads_only_the_2026_house_table():
    rows = parse_endorsement_list(read_fixture("endorsements_trump_ballotpedia.html"), "ballotpedia_trump")
    names = {row["name"] for row in rows}
    assert len(rows) == 8
    assert "Jerry Carl" in names
    # The 2026 Senate and 2024 House tables in the fixture are not read
    assert all(row["office"] == "house" for row in rows)
    carl = next(row for row in rows if row["name"] == "Jerry Carl")
    assert (carl["state"], carl["district"], carl["date"]) == ("AL", "01", "2026-06-22")
    assert carl["endorsement_type"] == "Primary"


def test_trump_parser_at_large_and_earliest_source():
    rows = parse_endorsement_list(read_fixture("endorsements_trump_ballotpedia.html"), "ballotpedia_trump")
    begich = next(row for row in rows if row["name"] == "Nicholas Begich")
    assert (begich["state"], begich["district"]) == ("AK", "00")
    # Barrett has two posts (primary and general). The earlier one is kept
    barrett = next(row for row in rows if row["name"] == "Tom Barrett")
    assert barrett["endorsement_type"] == "Primary, General"
    assert barrett["source_url"].startswith("https://truthsocial.com/")
    assert barrett["date"] == min(barrett["all_dates"])


def test_cfg_parser_reads_offices_from_the_heading_code():
    rows = parse_endorsement_list(read_fixture("endorsements_cfg_sample.html"), "club_for_growth")
    offices = {row["office"] for row in rows}
    assert {"house", "senate", "governor", "other"} <= offices
    begich = next(row for row in rows if row["name"] == "Nick Begich")
    assert (begich["office"], begich["state"], begich["district"]) == ("house", "AK", "00")


def test_jd_parser_pads_districts():
    rows = parse_endorsement_list(read_fixture("endorsements_jd_sample.html"), "justice_democrats")
    abughazaleh = next(row for row in rows if row["name"] == "Kat Abughazaleh")
    assert (abughazaleh["state"], abughazaleh["district"]) == ("IL", "09")
    assert all(row["office"] == "house" for row in rows)


def test_non_house_rows_dropped():
    rows = parse_endorsement_list(read_fixture("endorsements_cfg_sample.html"), "club_for_growth")
    house, dropped = house_only(rows)
    assert all(row["office"] == "house" for row in house)
    assert dropped == len(rows) - len(house)
    # Five statewide (governor, attorney general) and five Senate rows in the snapshot
    assert dropped == 10


def test_match_by_race_and_last_name():
    rows = [{"name": "Jerry Carl", "state": "AL", "district": "01"}]
    matched, review = match_candidates(rows, CANDIDATES, party="REP")
    assert review == []
    assert (matched[0]["candidate_id"], matched[0]["race_id"]) == ("H0AL01055", "AL-01")


def test_match_by_candidate_id():
    rows = [{"name": "Tom Barrett", "state": "MI", "district": "07", "candidate_id": "H2MI07123"}]
    matched, review = match_candidates(rows, CANDIDATES, party="REP")
    assert matched[0]["candidate_id"] == "H2MI07123"


def test_district_change_matches_by_id():
    # The list says the old district, but the FEC ID settles it and the race
    # comes from the candidates table, not the list
    rows = [{"name": "Barry Moore", "state": "AL", "district": "02", "candidate_id": "H8AL02171"}]
    matched, review = match_candidates(rows, CANDIDATES, party="REP")
    assert (matched[0]["candidate_id"], matched[0]["race_id"]) == ("H8AL02171", "AL-01")


# Real rows for two hard cases: twins in one race, and one person filed twice
TIES = pd.DataFrame(
    [
        ("H6TX22283", "NEHLS, TREVER", "REP", "TX", "22", "TX-22", "O"),
        ("H0TX22302", "NEHLS, TROY", "REP", "TX", "22", "TX-22", "I"),
        ("H8MO09146", "ONDER JR, ROBERT FRANK", "REP", "MO", "03", "MO-03", "I"),
        ("H4MO03221", "ONDER, ROBERT FOR JR.", "REP", "MO", "03", "MO-03", "I"),
    ],
    columns=CANDIDATES.columns,
)


def test_first_name_breaks_a_last_name_tie():
    rows = [{"name": "Troy Nehls", "state": "TX", "district": "22"}, {"name": "Trever Nehls", "state": "TX", "district": "22"}]
    matched, review = match_candidates(rows, TIES, party="REP")
    assert [row["candidate_id"] for row in matched] == ["H0TX22302", "H6TX22283"]


def test_override_settles_a_duplicate_registration():
    # The row from data/manual/nominee_matches.csv. Overrides apply by race
    # and last name, because list spellings differ ("Marty" or "Martin")
    overrides = [{"race_id": "MO-03", "name": "Bob Onder", "candidate_id": "H4MO03221"}]
    rows = [{"name": "Bob Onder", "state": "MO", "district": "03"}]
    matched, review = match_candidates(rows, TIES, party="REP")
    assert matched == [] and len(review) == 1
    matched, review = match_candidates(rows, TIES, party="REP", overrides=overrides)
    assert matched[0]["candidate_id"] == "H4MO03221"


def test_trump_special_elections_are_marked():
    rows = parse_endorsement_list(read_fixture("endorsements_trump_ballotpedia.html"), "ballotpedia_trump")
    assert all(row["special"] is False for row in rows)
    assert _parse_office("U.S. House Georgia District 14 (special)") == ("GA", "14", True)
    assert _parse_office("U.S. House Alaska At-large District") == ("AK", "00", False)


def test_unmatched_goes_to_review():
    rows = [
        {"name": "Nobody Here", "state": "AL", "district": "01"},
        # Right race and last name, but the other party, so it must not match
        {"name": "William Lawrence", "state": "MI", "district": "07"},
    ]
    matched, review = match_candidates(rows, CANDIDATES, party="REP")
    assert matched == []
    assert [row["name"] for row in review] == ["Nobody Here", "William Lawrence"]
    assert all(row["review_reason"] for row in review)


# Real rows: Minnesota Democrats file as DFL, and Greg Casar's 2026 filing
# is in TX-37 after Texas redrew its map, though Justice Democrats lists TX-35
REDRAWN = pd.DataFrame(
    [
        ("H8MN05239", "OMAR, ILHAN", "DFL", "MN", "05", "MN-05", "I"),
        ("H2TX35144", "CASAR, GREG", "DEM", "TX", "37", "TX-37", "O"),
        ("H6TX35999", "CASAR, MARIA", "DEM", "TX", "35", "TX-35", "O"),
    ],
    columns=CANDIDATES.columns,
)


def test_dfl_counts_as_democratic():
    matched, review = match_candidates([{"name": "Ilhan Omar", "state": "MN", "district": "05"}], REDRAWN, party="DEM")
    assert [row["candidate_id"] for row in matched] == ["H8MN05239"]


def test_redrawn_district_matches_on_full_name_in_the_state():
    # No Greg Casar in TX-35, but exactly one Greg Casar in Texas
    matched, review = match_candidates([{"name": "Greg Casar", "state": "TX", "district": "35"}], REDRAWN.iloc[:2], party="DEM")
    assert [(row["candidate_id"], row["race_id"]) for row in matched] == [("H2TX35144", "TX-37")]
    assert "TX-35" in matched[0]["match_note"]


def test_statewide_fallback_needs_the_first_name():
    # A different Casar in the listed race must not be swapped for Greg
    matched, review = match_candidates([{"name": "Ana Casar", "state": "TX", "district": "36"}], REDRAWN, party="DEM")
    assert matched == []
    assert len(review) == 1


# Club for Growth copies, in order. The list was cleared for the new cycle on
# 2025-02-13, so the 2025-02-01 copy is the 2024 slate.
COPIES = ["20250201", "20250213", "20250303", "20250815", "20251004", "20260416", "20260801", "20260825"]


def test_listing_date_starts_the_run_before_the_primary():
    # Nick Begich: 2024 slate, cleared, then listed from March 2025 on
    present = {"20250201", "20250303", "20250815", "20251004", "20260416", "20260801", "20260825"}
    assert listing_date(COPIES, present, "20260818") == ("20250303", "listed")


def test_listing_date_drops_an_endorsement_removed_before_the_primary():
    # Chip Roy: listed in 2025, then removed before his primary
    assert listing_date(COPIES, {"20250303", "20250815"}, "20260303") == (None, "removed")


def test_listing_date_uses_a_relisting_after_the_primary():
    # Derek Merrin: 2024 slate, removed, listed again after his May primary
    assert listing_date(COPIES, {"20250201", "20260801", "20260825"}, "20260505") == ("20260801", "listed")


def test_listing_date_keeps_a_loser_removed_after_the_primary():
    present = {"20251004", "20260416"}
    assert listing_date(COPIES, present, "20260519") == ("20251004", "listed")
