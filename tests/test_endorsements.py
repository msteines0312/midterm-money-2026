"""Tests for src/analysis/endorsements.py, using a small hand-built database."""

import pytest

from src.analysis.endorsements import classify_primary, load_primary_dates, primary_dates_for
from src.db import connect, create_schema, upsert_rows

PULLED_AT = "2026-10-26"


def candidate(candidate_id, name, race_id, status, party="REP"):
    """One candidates row."""
    state, district = race_id.split("-")
    return {
        "candidate_id": candidate_id, "name": name, "party": party, "state": state,
        "district": district, "race_id": race_id, "incumbent_challenge": status, "primary_result": None,
    }


def totals(candidate_id, external, pulled_at=PULLED_AT):
    """One candidate_totals row with only the fields the analysis reads."""
    return {"candidate_id": candidate_id, "pulled_at": pulled_at, "external_contributions": external}


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    create_schema(connection)
    yield connection
    connection.close()


def load(conn, candidates, money):
    upsert_rows(conn, "candidates", candidates)
    upsert_rows(conn, "candidate_totals", money)


def by_id(frame):
    return frame.set_index("candidate_id").to_dict("index")


def test_status_from_incumbent_challenge(conn):
    load(conn, [
        candidate("H1", "SMITH, ANN", "TX-01", "I"),
        candidate("H2", "JONES, BO", "TX-02", "O"),
        candidate("H3", "LEE, CY", "TX-01", "C"),
    ], [totals("H1", 50_000), totals("H2", 50_000), totals("H3", 50_000)])
    result = by_id(classify_primary(conn))
    assert [result[i]["status"] for i in ("H1", "H2", "H3")] == ["incumbent", "open_seat", "challenger"]


def test_contested_needs_two_funded_candidates(conn):
    load(conn, [
        candidate("H1", "SMITH, ANN", "TX-01", "O"),
        candidate("H2", "JONES, BO", "TX-01", "O"),
        # A Democrat in the same race never makes the Republican primary contested
        candidate("H3", "LEE, CY", "TX-01", "O", party="DEM"),
    ], [totals("H1", 50_000), totals("H2", 10_000), totals("H3", 900_000)])
    result = by_id(classify_primary(conn))
    assert result["H1"]["contested"] and result["H2"]["contested"]
    assert not result["H3"]["contested"]


def test_one_funded_candidate_is_uncontested(conn):
    load(conn, [
        candidate("H1", "SMITH, ANN", "TX-01", "I"),
        candidate("H2", "JONES, BO", "TX-01", "C"),
    ], [totals("H1", 500_000), totals("H2", 9_999)])
    result = by_id(classify_primary(conn))
    assert not result["H1"]["contested"] and not result["H2"]["contested"]


def test_duplicate_registration_counts_once(conn):
    # One person filed twice: same last name, identical money. Not a contest.
    load(conn, [
        candidate("H8MO09146", "ONDER JR, ROBERT FRANK", "MO-03", "I"),
        candidate("H4MO03221", "ONDER, ROBERT FOR JR.", "MO-03", "I"),
    ], [totals("H8MO09146", 1_049_405.05), totals("H4MO03221", 1_049_405.05)])
    result = by_id(classify_primary(conn))
    assert not result["H8MO09146"]["contested"]


def test_top_fundraiser_flag(conn):
    load(conn, [
        candidate("H1", "SMITH, ANN", "TX-01", "O"),
        candidate("H2", "JONES, BO", "TX-01", "O"),
    ], [totals("H1", 50_000), totals("H2", 80_000),
        # An older pull must not be read
        totals("H1", 999_999, pulled_at="2026-09-01")])
    result = by_id(classify_primary(conn))
    assert result["H2"]["top_fundraiser"] and not result["H1"]["top_fundraiser"]


def test_classify_limits_to_requested_ids(conn):
    load(conn, [
        candidate("H1", "SMITH, ANN", "TX-01", "O"),
        candidate("H2", "JONES, BO", "TX-01", "O"),
    ], [totals("H1", 50_000), totals("H2", 80_000)])
    result = classify_primary(conn, candidate_ids=["H1"])
    # Only H1 is returned, but H2 still counts toward the contest
    assert list(result["candidate_id"]) == ["H1"] and bool(result["contested"].iloc[0])


DATES_HEADER = "state,districts,primary_date,runoff_date,source_url,note\n"


def test_primary_date_requires_source(tmp_path):
    path = tmp_path / "primary_dates.csv"
    path.write_text(DATES_HEADER + "TX,,2026-03-03,2026-05-26,,\n")
    with pytest.raises(ValueError, match="source_url"):
        load_primary_dates(path)


def test_district_dates_override_the_state(tmp_path):
    # Alabama split its 2026 House primaries by district
    path = tmp_path / "primary_dates.csv"
    path.write_text(
        DATES_HEADER
        + "AL,03;04;05,2026-05-19,2026-06-16,https://fec.example,\n"
        + "AL,01;02;06;07,2026-08-11,,https://fec.example,\n"
        + "TX,,2026-03-03,2026-05-26,https://fec.example,\n"
    )
    dates = load_primary_dates(path)
    assert primary_dates_for("AL-01", dates)["primary_date"] == "2026-08-11"
    assert primary_dates_for("AL-03", dates)["runoff_date"] == "2026-06-16"
    assert primary_dates_for("TX-22", dates)["primary_date"] == "2026-03-03"
    assert primary_dates_for("ZZ-01", dates) is None


def test_real_primary_dates_load():
    dates = load_primary_dates()
    assert primary_dates_for("AL-01", dates)["primary_date"] == "2026-08-11"
    assert primary_dates_for("CA-07", dates)["primary_date"] == "2026-06-02"
