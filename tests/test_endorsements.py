"""Tests for src/analysis/endorsements.py, using a small hand-built database."""

import pandas as pd
import pytest

from src.analysis.endorsements import (
    baseline_rates,
    classify_primary,
    endorsement_outcomes,
    endorsement_win_rates,
    excluded_counts,
    favorite_check,
    load_primary_dates,
    primary_dates_for,
    wilson_interval,
)
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


# Outcomes and win rates

DATES = {
    "TX": {"primary_date": "2026-03-03", "runoff_date": "2026-05-26"},
    "CA": {"primary_date": "2026-06-02", "runoff_date": ""},
    "LA": {"primary_date": "2026-11-03", "runoff_date": "2026-12-12"},
}
AS_OF = "2026-10-27"


def endorsement(candidate_id, race_id, endorsement_date, endorser="Club for Growth PAC", source_outcome=""):
    """One row as load_endorsements returns it."""
    return {
        "endorser": endorser, "candidate_id": candidate_id, "race_id": race_id, "candidate_name": candidate_id,
        "endorsement_date": endorsement_date, "date_basis": "listed_by" if endorsement_date else "",
        "source_url": "https://a", "source_outcome": source_outcome, "note": "",
    }


def classified(*rows):
    """A classify_primary frame from (candidate_id, race_id, status, contested, top_fundraiser) tuples."""
    return pd.DataFrame(
        [{"candidate_id": c, "name": f"{c}, ANN", "race_id": r, "party": "REP", "status": s, "external": 50_000.0,
          "contested": con, "top_fundraiser": top} for c, r, s, con, top in rows]
    )


def outcomes_for(endorsements, frame, nominee_ids, nominees=()):
    return endorsement_outcomes(endorsements, DATES, frame, set(nominee_ids), list(nominees), as_of=AS_OF)


def test_endorsement_after_primary_not_counted():
    frame = classified(("H1", "CA-01", "open_seat", True, True))
    # California has no runoff, so anything after June 2 is after
    out = outcomes_for([endorsement("H1", "CA-01", "2026-06-03")], frame, {"H1"})
    assert out.loc[0, "timing"] == "after"
    assert endorsement_win_rates(out).empty


def test_endorsement_on_primary_day_counts():
    frame = classified(("H1", "TX-01", "open_seat", True, True))
    out = outcomes_for([endorsement("H1", "TX-01", "2026-03-03")], frame, {"H1"})
    assert out.loc[0, "timing"] == "before"


def test_runoff_endorsement_kept_out_of_headline():
    frame = classified(("H1", "TX-01", "open_seat", True, True))
    # May 20 is after the March 3 primary but before the May 26 runoff
    out = outcomes_for([endorsement("H1", "TX-01", "2026-05-20")], frame, {"H1"})
    assert out.loc[0, "timing"] == "runoff"
    assert endorsement_win_rates(out).empty
    # After the runoff date it is simply after
    later = outcomes_for([endorsement("H1", "TX-01", "2026-06-01")], frame, {"H1"})
    assert later.loc[0, "timing"] == "after"


def test_unknown_date_excluded_from_headline():
    frame = classified(("H1", "TX-01", "open_seat", True, True))
    out = outcomes_for([endorsement("H1", "TX-01", "")], frame, {"H1"})
    assert out.loc[0, "timing"] == "unknown"
    assert endorsement_win_rates(out).empty
    assert excluded_counts(out).loc[0, "unknown"] == 1


def test_pending_primary_not_scored():
    frame = classified(("H1", "LA-01", "incumbent", False, True))
    out = outcomes_for([endorsement("H1", "LA-01", "2025-11-03")], frame, set())
    assert out.loc[0, "outcome"] == "pending"
    assert endorsement_win_rates(out).empty


def test_hedged_endorsements_excluded():
    frame = classified(("H1", "TX-01", "open_seat", True, True), ("H2", "TX-01", "open_seat", True, False))
    rows = [endorsement("H1", "TX-01", "2026-01-01"), endorsement("H2", "TX-01", "2026-01-01")]
    out = outcomes_for(rows, frame, {"H1"})
    assert out["hedged"].all()
    assert endorsement_win_rates(out).empty
    # A second endorser backing one of them is not hedging
    other = outcomes_for([endorsement("H1", "TX-01", "2026-01-01"), endorsement("H2", "TX-01", "2026-01-01", "Donald Trump")], frame, {"H1"})
    assert not other["hedged"].any()


def test_uncontested_in_own_stratum():
    frame = classified(("H1", "TX-01", "incumbent", False, True), ("H2", "TX-02", "incumbent", True, True))
    rows = [endorsement("H1", "TX-01", "2026-01-01"), endorsement("H2", "TX-02", "2026-01-01")]
    rates = endorsement_win_rates(outcomes_for(rows, frame, {"H1", "H2"})).set_index("stratum")
    assert rates.loc["uncontested", "won"] == 1
    assert rates.loc["incumbent", "won"] == 1
    # The contested total leaves the uncontested race out
    assert rates.loc["all_contested", "won"] == 1


def test_top_two_advance_is_a_win():
    # Two Democrats advanced in a California top-two race. Both are nominees.
    frame = classified(("H1", "CA-07", "challenger", True, True), ("H2", "CA-07", "incumbent", True, False))
    out = outcomes_for([endorsement("H1", "CA-07", "2026-01-01", "Justice Democrats")], frame, {"H1", "H2"})
    assert out.loc[0, "outcome"] == "won"


def test_withdrawal_is_not_a_win():
    # The race has a nominee, and the endorsed candidate is not it
    frame = classified(("H1", "TX-01", "open_seat", True, False))
    nominees = [{"race_id": "TX-01", "name": "Bo Jones", "party": "rep"}]
    out = outcomes_for([endorsement("H1", "TX-01", "2026-01-01")], frame, {"H9"}, nominees)
    assert out.loc[0, "outcome"] == "lost"


def test_not_on_primary_ballot_is_withdrew_not_lost():
    # Endorsed early, then retired before the primary: never on the ballot
    frame = classified(("H1", "TX-01", "incumbent", True, False))
    rows = [endorsement("H1", "TX-01", "2025-11-03", "Donald Trump", "Not on the ballot primary")]
    out = outcomes_for(rows, frame, {"H9"})
    assert out.loc[0, "outcome"] == "withdrew"
    assert endorsement_win_rates(out).empty
    assert excluded_counts(out).loc[0, "withdrew"] == 1


def test_withdrawn_candidate_does_not_hedge_the_replacement():
    frame = classified(("H1", "TX-01", "incumbent", True, False), ("H2", "TX-01", "open_seat", True, True))
    rows = [endorsement("H1", "TX-01", "2025-11-03", "Donald Trump", "Not on the ballot primary"),
            endorsement("H2", "TX-01", "2026-01-01", "Donald Trump", "Won primary")]
    out = by_id(outcomes_for(rows, frame, {"H2"}))
    assert not out["H2"]["hedged"]
    assert out["H2"]["outcome"] == "won"


def test_won_primary_then_left_ballot_is_a_win():
    # Won the primary, then withdrew before November, so not the nominee
    frame = classified(("H1", "TX-01", "incumbent", True, True))
    nominees = [{"race_id": "TX-01", "name": "Bo Jones", "party": "rep"}]
    rows = [endorsement("H1", "TX-01", "2025-11-03", "Donald Trump", "Not on the ballot general")]
    assert outcomes_for(rows, frame, {"H9"}, nominees).loc[0, "outcome"] == "won"


def test_wilson_interval_known_values():
    low, high = wilson_interval(3, 4)
    assert low == pytest.approx(0.3006, abs=1e-3)
    assert high == pytest.approx(0.9544, abs=1e-3)


def test_rate_is_none_when_nothing_decided():
    assert wilson_interval(0, 0) == (None, None)
    frame = classified(("H1", "TX-01", "open_seat", True, True))
    # No nominees known for the race, so the outcome is review, not a loss
    out = outcomes_for([endorsement("H1", "TX-01", "2026-01-01")], frame, set())
    rates = endorsement_win_rates(out).set_index("stratum")
    assert rates.loc["open_seat", "review"] == 1
    assert rates.loc["open_seat", "rate"] is None


def test_favorite_check_shares():
    frame = classified(
        ("H1", "TX-01", "open_seat", True, True),
        ("H2", "TX-02", "open_seat", True, True),
        ("H3", "TX-03", "open_seat", True, False),
        ("H4", "TX-04", "open_seat", True, False),
    )
    rows = [endorsement(c, f"TX-0{c[1]}", "2026-01-01") for c in ("H1", "H2", "H3", "H4")]
    # TX-04 has a known nominee who is not H4, so H4 lost
    out = outcomes_for(rows, frame, {"H1", "H2", "H3"}, [{"race_id": "TX-04", "name": "Bo Jones", "party": "rep"}])
    check = favorite_check(out)
    assert check["n"] == 4
    assert check["share_top_fundraiser"] == 0.5
    assert check["win_rate_if_top"] == 1.0
    assert check["win_rate_if_not_top"] == 0.5


def test_baseline_uses_funded_candidates_only():
    frame = pd.DataFrame([
        {"candidate_id": "H1", "name": "A, A", "race_id": "TX-01", "party": "REP", "status": "open_seat",
         "external": 50_000.0, "contested": True, "top_fundraiser": True},
        {"candidate_id": "H2", "name": "B, B", "race_id": "TX-01", "party": "REP", "status": "open_seat",
         "external": 20_000.0, "contested": True, "top_fundraiser": False},
        # A paper candidate who raised nothing is not part of the baseline
        {"candidate_id": "H3", "name": "C, C", "race_id": "TX-01", "party": "REP", "status": "open_seat",
         "external": 0.0, "contested": True, "top_fundraiser": False},
    ])
    rates = baseline_rates(frame, DATES, {"H1"}, [{"race_id": "TX-01", "name": "A A", "party": "rep"}], as_of=AS_OF)
    row = rates.set_index(["party", "stratum"]).loc[("REP", "open_seat")]
    assert (row["won"], row["lost"]) == (1, 1)


def person(candidate_id, name, external, status="open_seat", race_id="TX-34", party="REP"):
    """One classify_primary row with a real-looking FEC name."""
    return {"candidate_id": candidate_id, "name": name, "race_id": race_id, "party": party, "status": status,
            "external": external, "contested": True, "top_fundraiser": False}


def test_same_surname_nominee_is_not_a_win():
    # Two different people named Flores in TX-34. Only Eric is the nominee.
    frame = pd.DataFrame([person("H1", "FLORES, MAYRA", 40_000.0), person("H2", "FLORES, ERIC", 90_000.0)])
    nominees = [{"race_id": "TX-34", "name": "Eric Flores", "party": "rep"}]
    out = by_id(outcomes_for([endorsement("H1", "TX-34", "2026-01-01")], frame, {"H2"}, nominees))
    assert out["H1"]["outcome"] == "lost"
    rates = baseline_rates(frame, DATES, {"H2"}, nominees, as_of=AS_OF)
    row = rates.set_index(["party", "stratum"]).loc[("REP", "open_seat")]
    assert (row["won"], row["lost"]) == (1, 1)


def test_duplicate_filing_of_the_nominee_still_wins():
    # One person filed twice. The nominee file carries the other ID.
    frame = pd.DataFrame([person("H1", "FLORES, ERIC", 90_000.0), person("H2", "FLORES, ERIC J", 90_000.0)])
    nominees = [{"race_id": "TX-34", "name": "Eric Flores", "party": "rep"}]
    out = by_id(outcomes_for([endorsement("H1", "TX-34", "2026-01-01")], frame, {"H2"}, nominees))
    assert out["H1"]["outcome"] == "won"


def test_baseline_counts_a_duplicate_filing_once():
    frame = pd.DataFrame([person("H1", "FLORES, ERIC", 90_000.0), person("H2", "FLORES, ERIC J", 90_000.0),
                          person("H3", "SMITH, ANN", 30_000.0)])
    nominees = [{"race_id": "TX-34", "name": "Eric Flores", "party": "rep"}]
    rates = baseline_rates(frame, DATES, {"H2"}, nominees, as_of=AS_OF)
    row = rates.set_index(["party", "stratum"]).loc[("REP", "open_seat")]
    assert (row["won"], row["lost"]) == (1, 1)


def test_baseline_can_leave_out_the_endorsed():
    # The endorsed nominee leaves the baseline, but still stops a same-surname rival scoring a win
    frame = pd.DataFrame([person("H1", "FLORES, MAYRA", 40_000.0), person("H2", "FLORES, ERIC", 90_000.0),
                          person("H3", "SMITH, ANN", 30_000.0)])
    nominees = [{"race_id": "TX-34", "name": "Eric Flores", "party": "rep"}]
    rates = baseline_rates(frame, DATES, {"H2"}, nominees, as_of=AS_OF, exclude_ids={"H2"})
    row = rates.set_index(["party", "stratum"]).loc[("REP", "open_seat")]
    assert (row["won"], row["lost"]) == (0, 2)


def test_endorsing_the_winner_after_the_primary_does_not_hide_a_loss():
    # Backed H1 before the primary, H1 lost, then backed the nominee H2 for the runoff
    frame = classified(("H1", "TX-01", "incumbent", True, True), ("H2", "TX-01", "open_seat", True, False))
    rows = [endorsement("H1", "TX-01", "2025-12-18"), endorsement("H2", "TX-01", "2026-03-11")]
    nominees = [{"race_id": "TX-01", "name": "Ann H2", "party": "rep"}]
    out = by_id(outcomes_for(rows, frame, {"H2"}, nominees))
    assert not out["H1"]["hedged"]
    rates = endorsement_win_rates(outcomes_for(rows, frame, {"H2"}, nominees)).set_index("stratum")
    assert (rates.loc["incumbent", "won"], rates.loc["incumbent", "lost"]) == (0, 1)


def test_real_primary_dates_load():
    dates = load_primary_dates()
    assert primary_dates_for("AL-01", dates)["primary_date"] == "2026-08-11"
    assert primary_dates_for("CA-07", dates)["primary_date"] == "2026-06-02"
