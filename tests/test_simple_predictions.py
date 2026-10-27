"""Tests for src/predict/simple.py, using a small hand-built database."""

import pandas as pd
import pytest

from src.db import connect, create_schema, upsert_rows
from src.predict.simple import match_nominees, simple_predictions

PULLED_AT = "2026-10-23"


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    create_schema(connection)
    yield connection
    connection.close()


def candidate(candidate_id, name, party, race_id, status="C"):
    return {
        "candidate_id": candidate_id, "name": name, "party": party,
        "state": race_id[:2], "district": race_id[3:], "race_id": race_id,
        "incumbent_challenge": status,
    }


def add_race(conn, race_id, cook_rating=None):
    upsert_rows(conn, "races", [{
        "race_id": race_id, "state": race_id[:2], "district": race_id[3:],
        "cook_rating": cook_rating, "cook_pvi": None, "rating_source": "cook",
    }])


def add_money(conn, candidate_id, external, self_funding=0.0):
    upsert_rows(conn, "candidate_totals", [{
        "candidate_id": candidate_id, "pulled_at": PULLED_AT,
        "candidate_self_funding": self_funding, "external_contributions": external,
    }])


def nominee(race_id, name, party, status="confirmed"):
    return {"race_id": race_id, "name": name, "party": party, "status": status}


def two_way_race(conn, dem_money, rep_money, rating="Lean R", race_id="TX-01"):
    """Insert a D vs R race with both nominees on file; return its nominees."""
    add_race(conn, race_id, rating)
    upsert_rows(conn, "candidates", [
        candidate("D1", "ALVAREZ, ANA", "DEM", race_id),
        candidate("R1", "BAKER, BOB", "REP", race_id, "I"),
    ])
    add_money(conn, "D1", dem_money)
    add_money(conn, "R1", rep_money)
    return [nominee(race_id, "Ana Alvarez", "Democratic"), nominee(race_id, "Bob Baker", "Republican")]


def predict_one(conn, nominees):
    return simple_predictions(conn, nominees, PULLED_AT).iloc[0]


# Matching

def test_unique_last_name_match():
    candidates = [candidate("H1", "KEAN, THOMAS H JR", "REP", "NJ-07")]
    result = match_nominees([nominee("NJ-07", "Thomas Kean Jr.", "Republican")], candidates, [])
    assert result[0]["candidate_id"] == "H1"


def test_accents_and_multiword_last_names_match():
    candidates = [
        candidate("H1", "HERNANDEZ, ROSA", "DEM", "NM-01"),
        candidate("H2", "VAN DREW, JEFFERSON", "REP", "NJ-02"),
    ]
    nominees = [nominee("NM-01", "Rosa Hernández", "Democratic"), nominee("NJ-02", "Jefferson Van Drew", "Republican")]
    assert [row["candidate_id"] for row in match_nominees(nominees, candidates, [])] == ["H1", "H2"]


def test_ambiguous_last_name_unmatched():
    candidates = [candidate("H1", "SMITH, ANN", "DEM", "OH-01"), candidate("H2", "SMITH, BEN", "REP", "OH-01")]
    result = match_nominees([nominee("OH-01", "Ann Smith", "Democratic")], candidates, [])
    assert result[0]["candidate_id"] is None


def test_override_wins():
    candidates = [candidate("H1", "SMITH, ANN", "DEM", "OH-01"), candidate("H2", "SMITH, BEN", "REP", "OH-01")]
    overrides = [{"race_id": "OH-01", "name": "Ann Smith", "candidate_id": "H2", "note": "checked"}]
    result = match_nominees([nominee("OH-01", "Ann Smith", "Democratic")], candidates, overrides)
    assert result[0]["candidate_id"] == "H2"


def test_match_ignores_other_races():
    candidates = [candidate("H1", "SMITH, ANN", "DEM", "OH-02")]
    result = match_nominees([nominee("OH-01", "Ann Smith", "Democratic")], candidates, [])
    assert result[0]["candidate_id"] is None


# Money rule

def test_money_share_and_leader(conn):
    row = predict_one(conn, two_way_race(conn, 300, 100))
    assert row["race_type"] == "D_vs_R"
    assert row["dem_money_share"] == pytest.approx(0.75)
    assert row["money_leader_party"] == "DEM"
    assert row["incumbent_party"] == "REP"
    assert row["cook_favorite_party"] == "REP"
    assert row["money_and_cook_agree"] is not None and not row["money_and_cook_agree"]


def test_unmatched_nominee_counts_as_zero_money(conn):
    nominees = two_way_race(conn, 0, 500)
    nominees[0]["name"] = "Someone Else"
    row = predict_one(conn, nominees)
    assert row["dem_candidate_id"] is None
    assert row["dem_money"] == 0
    assert row["dem_money_share"] == 0.0
    assert row["money_leader_party"] == "REP"


def test_unmatched_nominee_opponent_share_is_one(conn):
    nominees = two_way_race(conn, 0, 500)
    nominees[0]["name"] = "Someone Else"
    # The Democrat has no FEC match, so the Republican holds the whole share
    assert 1 - predict_one(conn, nominees)["dem_money_share"] == 1.0


def test_negative_money_floored_at_zero(conn):
    row = predict_one(conn, two_way_race(conn, -50, 100))
    assert row["dem_money"] == 0
    assert row["dem_money_share"] == 0.0


def test_both_zero_is_abstain(conn):
    row = predict_one(conn, two_way_race(conn, 0, 0))
    assert row["money_leader_party"] is None
    assert pd.isna(row["dem_money_share"])


def test_exact_half_is_abstain(conn):
    row = predict_one(conn, two_way_race(conn, 200, 200))
    assert row["dem_money_share"] == 0.5
    assert row["money_leader_party"] is None
    assert row["money_and_cook_agree"] is None


def test_self_funding_not_counted(conn):
    nominees = two_way_race(conn, 100, 300)
    add_money(conn, "D1", 100, self_funding=9_000_000)
    row = predict_one(conn, nominees)
    assert row["dem_money_share"] == pytest.approx(0.25)


# Cook

def test_toss_up_has_no_cook_favorite(conn):
    row = predict_one(conn, two_way_race(conn, 300, 100, rating="Toss Up"))
    assert row["cook_favorite_party"] is None
    assert row["money_and_cook_agree"] is None


# Race types

def test_unopposed_race_type(conn):
    add_race(conn, "CA-01", "Solid D")
    upsert_rows(conn, "candidates", [candidate("D1", "ALVAREZ, ANA", "DEM", "CA-01", "I")])
    add_money(conn, "D1", 100)
    row = predict_one(conn, [nominee("CA-01", "Ana Alvarez", "Democratic")])
    assert row["race_type"] == "unopposed"
    assert row["money_leader_party"] is None
    assert row["cook_favorite_party"] is None
    assert row["dem_candidate_id"] == "D1"


def test_same_party_race_has_no_cook_favorite(conn):
    add_race(conn, "CA-02", "Solid D")
    upsert_rows(conn, "candidates", [
        candidate("D1", "ALVAREZ, ANA", "DEM", "CA-02"), candidate("D2", "CHEN, CY", "DEM", "CA-02"),
    ])
    add_money(conn, "D1", 100)
    add_money(conn, "D2", 300)
    nominees = [nominee("CA-02", "Ana Alvarez", "Democratic"), nominee("CA-02", "Cy Chen", "Democratic")]
    row = predict_one(conn, nominees)
    assert row["race_type"] == "same_party"
    assert row["cook_favorite_party"] is None
    # Top two by money fill the dem_* and rep_* columns, richest first
    assert row["dem_candidate_id"] == "D2"
    assert row["rep_candidate_id"] == "D1"
    assert "top two" in row["notes"]


def test_independent_race_is_other(conn):
    nominees = two_way_race(conn, 300, 100)
    nominees[0]["party"] = "Independent"
    row = predict_one(conn, nominees)
    assert row["race_type"] == "other"
    assert row["cook_favorite_party"] is None
    assert row["notes"]


def test_unconfirmed_status_passed_through(conn):
    nominees = two_way_race(conn, 300, 100)
    nominees[1]["status"] = "unconfirmed"
    assert predict_one(conn, nominees)["status"] == "unconfirmed"


# Outside spending

def test_outside_spending_excludes_non_committee_filers(conn):
    nominees = two_way_race(conn, 300, 100)
    upsert_rows(conn, "committees", [
        {"committee_id": "C1", "name": "Super PAC", "committee_type": "O", "designation": "U"},
        {"committee_id": "C2", "name": "Party", "committee_type": "Y", "designation": "P"},
    ])

    def spend(committee, support_oppose, election_type, candidate_id, total):
        return {
            "committee_id": committee, "candidate_key": candidate_id, "candidate_id": candidate_id,
            "election_type": election_type, "support_oppose": support_oppose,
            "pulled_at": PULLED_AT, "total": total,
        }

    upsert_rows(conn, "outside_spending", [
        spend("C1", "S", "G", "D1", 10),
        spend("C1", "O", "G", "D1", 5),
        spend("C1", "S", "P", "D1", 1000),   # primary spending is not counted
        spend("C2", "S", "G", "D1", 1000),   # party committee is not a super PAC
        spend("C9", "S", "G", "R1", 1000),   # filer missing from committees
        spend("C1", "O", "G", "R1", 7),
    ])
    row = predict_one(conn, nominees)
    assert (row["outside_support_dem"], row["outside_oppose_dem"]) == (10, 5)
    assert (row["outside_support_rep"], row["outside_oppose_rep"]) == (0, 7)


# Third parties

def test_third_party_outraised_flagged(conn):
    nominees = two_way_race(conn, 300, 100)
    upsert_rows(conn, "candidates", [candidate("L1", "DOE, LEE", "LIB", "TX-01")])
    add_money(conn, "L1", 900)
    nominees.append(nominee("TX-01", "Lee Doe", "Libertarian"))
    row = predict_one(conn, nominees)
    assert row["race_type"] == "D_vs_R"
    assert bool(row["third_party_outraised"]) is True
    # The share is still Democrat versus Republican only
    assert row["dem_money_share"] == pytest.approx(0.75)


def test_third_party_not_flagged_when_small(conn):
    nominees = two_way_race(conn, 300, 100)
    upsert_rows(conn, "candidates", [candidate("L1", "DOE, LEE", "LIB", "TX-01")])
    add_money(conn, "L1", 10)
    nominees.append(nominee("TX-01", "Lee Doe", "Libertarian"))
    assert bool(predict_one(conn, nominees)["third_party_outraised"]) is False
