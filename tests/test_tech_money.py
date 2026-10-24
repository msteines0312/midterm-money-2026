"""Tests for src/analysis/tech_money.py, using a small hand-built database."""

import pytest

from src.analysis.tech_money import (
    competitiveness,
    network_share,
    network_totals,
    party_buckets,
    primary_vs_general,
    top_races,
)
from src.db import connect, create_schema, upsert_rows

PULLED_AT = "2026-10-23"

COMMITTEES = [
    {"committee_id": "A1", "name": "Crypto PAC One", "committee_type": "O", "designation": "U"},
    {"committee_id": "A2", "name": "Crypto PAC Two", "committee_type": "V", "designation": "U"},
    {"committee_id": "B1", "name": "AI PAC", "committee_type": "W", "designation": "U"},
    {"committee_id": "U1", "name": "Unlabeled Super PAC", "committee_type": "O", "designation": "U"},
    # A party committee: labeled by mistake on purpose, so the type filter has to catch it
    {"committee_id": "P1", "name": "Party Committee", "committee_type": "Y", "designation": "P"},
]
# X1 is deliberately absent from committees, like the bogus individual filer in the real data
PAC_INDUSTRIES = [
    {"committee_id": "A1", "network": "Crypto", "industry": "Crypto", "source_url": "http://example.com"},
    {"committee_id": "A2", "network": "Crypto", "industry": "Crypto", "source_url": "http://example.com"},
    {"committee_id": "B1", "network": "AI", "industry": "AI", "source_url": "http://example.com"},
    {"committee_id": "P1", "network": "Crypto", "industry": "Crypto", "source_url": "http://example.com"},
    {"committee_id": "X1", "network": "Crypto", "industry": "Crypto", "source_url": "http://example.com"},
]
RACES = [
    {"race_id": "TX-01", "state": "TX", "district": "01", "cook_rating": "Toss Up"},
    {"race_id": "TX-05", "state": "TX", "district": "05", "cook_rating": "Lean R"},
    {"race_id": "MN-02", "state": "MN", "district": "02", "cook_rating": "Solid D"},
]


def spend(committee, key, party, support_oppose, election, race, total, pulled_at=PULLED_AT):
    """Build one outside_spending row; candidate_key doubles as candidate_id here."""
    return {
        "committee_id": committee, "candidate_key": key, "candidate_id": key,
        "candidate_name": key, "party": party, "race_id": race,
        "election_type": election, "support_oppose": support_oppose,
        "pulled_at": pulled_at, "total": total, "count": 1,
    }


SPENDING = [
    spend("A1", "D1", "DEM", "S", "G", "TX-01", 100),
    spend("A1", "R1", "REP", "O", "G", "TX-01", 40),
    spend("A2", "D2", "DFL", "S", "G", "MN-02", 30),
    spend("B1", "R2", "REP", "S", "P", "TX-05", 70),
    spend("B1", "R2", "REP", "S", "G", "TX-05", 20),
    # No party and no race, like a filing that names a candidate we could not match
    {**spend("B1", "TX|SMITH", None, "S", "G", None, 10), "candidate_id": None},
    spend("B1", "D1", "DEM", "S", "S", "TX-01", 5),
    spend("U1", "R1", "REP", "S", "G", "TX-01", 500),
    spend("P1", "R1", "REP", "S", "G", "TX-01", 1000),
    spend("X1", "R1", "REP", "S", "G", "TX-01", 100000),
    # An older snapshot that must never leak into the 2026-10-23 numbers
    spend("A1", "D1", "DEM", "S", "G", "TX-01", 7777, pulled_at="2026-10-01"),
]


@pytest.fixture
def conn(tmp_path):
    conn = connect(tmp_path / "test.db")
    create_schema(conn)
    upsert_rows(conn, "committees", COMMITTEES)
    upsert_rows(conn, "pac_industries", PAC_INDUSTRIES)
    upsert_rows(conn, "races", RACES)
    upsert_rows(conn, "outside_spending", SPENDING)
    yield conn
    conn.close()


def test_network_totals(conn):
    result = network_totals(conn, PULLED_AT).set_index("network")
    assert result.loc["Crypto", "total"] == 170
    assert result.loc["Crypto", "n_candidates"] == 3
    assert result.loc["Crypto", "industry"] == "Crypto"
    assert result.loc["AI", "total"] == 105
    # The race-less TX|SMITH row still counts. Distinct keys: R2, TX|SMITH, D1
    assert result.loc["AI", "n_candidates"] == 3


def test_party_buckets_count_dfl_as_democrat_and_null_as_other(conn):
    result = party_buckets(conn, PULLED_AT)
    totals = {(r.network, r.bucket): r.total for r in result.itertuples()}
    assert totals == {
        ("Crypto", "Supporting Democrats"): 130,  # DEM 100 + DFL 30
        ("Crypto", "Opposing Republicans"): 40,
        ("AI", "Supporting Republicans"): 90,
        ("AI", "Supporting Democrats"): 5,
        ("AI", "Other or unknown"): 10,
    }


def test_competitiveness_splits_toss_up_lean_and_solid(conn):
    result = competitiveness(conn, PULLED_AT)
    totals = {(r.network, r.seat_type): r.total for r in result.itertuples()}
    assert totals == {
        ("Crypto", "Competitive"): 140,  # Toss Up
        ("Crypto", "Safe"): 30,          # Solid D
        ("AI", "Competitive"): 20,       # Lean R, general only
    }


def test_primary_money_not_in_competitiveness(conn):
    result = competitiveness(conn, PULLED_AT)
    # AI spent 70 in the TX-05 primary and 5 in a special; neither may appear
    assert result[result.network == "AI"].total.sum() == 20


def test_primary_vs_general(conn):
    result = primary_vs_general(conn, PULLED_AT)
    totals = {(r.network, r.election): r.total for r in result.itertuples()}
    assert totals == {
        ("Crypto", "General"): 170,
        ("AI", "Primary"): 70,
        ("AI", "General"): 30,  # includes the race-less 10
        ("AI", "Other"): 5,     # special election
    }


def test_top_races_orders_by_network_total(conn):
    result = top_races(conn, PULLED_AT, n=2)
    assert list(result.race_id) == ["TX-01", "TX-05"]
    top = result.iloc[0]
    assert top.cook_rating == "Toss Up"
    assert top.network_total == 145
    # 145 network + 500 unlabeled super PAC. Party committee and X1 excluded.
    assert top.all_super_pac_total == 645


def test_non_committee_filer_excluded_from_top_races_and_network_share(conn):
    races = top_races(conn, PULLED_AT)
    assert races.all_super_pac_total.max() < 100000
    share = network_share(conn, PULLED_AT).set_index("network")
    assert share.loc["Crypto", "total"] == 170  # no X1 or P1 money


def test_party_committee_excluded_from_denominator(conn):
    share = network_share(conn, PULLED_AT).set_index("network")
    # Denominator: 170 + 105 + 500 unlabeled = 775
    assert share.loc["Crypto", "share_of_super_pac_spending"] == pytest.approx(170 / 775)
    assert share.loc["AI", "share_of_super_pac_spending"] == pytest.approx(105 / 775)
