"""Tests for src/history_results.py.

Results rows are real rows of the FEC's 2022 House results sheet, saved by
`python scripts/save_fixtures.py results` with the sheet's own header and
cell types. The Wikipedia samples are real tables from the pinned 2022 and
2024 pages, trimmed to a few districts.
"""

from pathlib import Path

import pytest

from src.fec.bulk import parse_summary
from src.history_results import (
    build_history_races,
    dem_vs_rep_races,
    parse_fec_results,
    parse_wiki_results,
    read_sheet_rows,
)
from src.ratings import parse_pvi_tables

FIXTURES = Path(__file__).parent / "fixtures"
SHEET_ROWS = read_sheet_rows(FIXTURES / "fec_results_2022_sample.xlsx")
SUMMARY = parse_summary((FIXTURES / "webl22_sample.txt").read_text(encoding="latin-1"))
PVI_2022 = (FIXTURES / "pvi_2022_sample.html").read_text(encoding="utf-8")
PVI_2024 = (FIXTURES / "pvi_2024_sample.html").read_text(encoding="utf-8")
RATINGS_2022 = (FIXTURES / "ratings_2022_sample.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def results():
    return parse_fec_results(SHEET_ROWS, 2022, SUMMARY)


def _race(results, race_id):
    return {row["name"]: row for row in results if row["race_id"] == race_id}


def test_general_rows_only(results):
    # GA-02: Jeremy Hunt lost the Republican primary runoff, so he was never
    # on the November ballot and must not appear
    assert set(_race(results, "GA-02")) == {"Bishop, Sanford", "West, Chris"}
    # LA-02: Louisiana's November jungle election is its general. Carter won
    # outright, so there was no December runoff.
    louisiana = _race(results, "LA-02")
    assert louisiana["Carter, Troy A."]["won"] == 1
    assert louisiana["Lux, \"Dan\""]["won"] == 0
    # IN-02 had a same-day special for the unexpired term. Only the regular
    # full-term general counts, and Walorski (who died before November) is gone.
    indiana = _race(results, "IN-02")
    assert "Walorski, Jackie" not in indiana
    assert indiana["Yakym, Rudolph (Rudy), III"]["votes"] == 125537


def test_one_winner_per_race(results):
    race_ids = {row["race_id"] for row in results}
    for race_id in race_ids:
        winners = [row["name"] for row in results if row["race_id"] == race_id and row["won"] == 1]
        assert len(winners) == 1, (race_id, winners)
    # The FEC left IN-02's full-term winner unmarked. Yakym had the most votes.
    assert _race(results, "IN-02")["Yakym, Rudolph (Rudy), III"]["won"] == 1


def test_at_large_race_id(results):
    alaska = _race(results, "AK-00")
    assert alaska["Peltola, Mary S."]["won"] == 1
    assert alaska["Peltola, Mary S."]["party"] == "DEM"
    # Non-voting delegates (DC and the territories) are left out
    assert not [row for row in results if row["race_id"].startswith("DC")]


def test_fusion_candidate_is_one_row(results):
    # NY-01: LaLota ran on the Republican and Conservative lines. He gets one
    # row with his combined votes and his major party.
    new_york = _race(results, "NY-01")
    assert set(new_york) == {"LaLota, Nicholas J.", "Fleming, Bridget"}
    assert new_york["LaLota, Nicholas J."]["votes"] == 177040
    assert new_york["LaLota, Nicholas J."]["party"] == "REP"
    assert new_york["Fleming, Bridget"]["party"] == "DEM"
    assert new_york["Fleming, Bridget"]["candidate_id"] == "H0NY01202"


def test_write_in_democrat_is_not_a_dem_nominee(results):
    # WI-08: Julie Hancock ran as a Democratic write-in (labeled "W(D)/W"),
    # so the race has no Democrat on the ballot
    assert _race(results, "WI-08")["Hancock, Julie"]["party"] != "DEM"


def test_incumbent_flag_from_summary_file(results):
    assert _race(results, "AK-00")["Peltola, Mary S."]["incumbent_challenge"] == "I"
    assert _race(results, "GA-02")["West, Chris"]["incumbent_challenge"] == "C"
    # LaLota's results ID is not in webl22, so his flag is unknown
    assert _race(results, "NY-01")["LaLota, Nicholas J."]["incumbent_challenge"] is None


def test_dem_vs_rep_races(results):
    # AK-00 has two Republicans and WI-08 has no Democrat on the ballot
    assert dem_vs_rep_races(results) == {"GA-02", "IN-02", "LA-02", "NJ-07", "NY-01"}


def test_past_pvi_parsed():
    # The 2024 page has a summary table listing NY-19 as EVEN (its pre-redraw
    # number) while the New York table says R+1. Reading only the per-state
    # tables avoids the conflict.
    assert _pvi(PVI_2024) == {"AK-00": "R+8", "NY-04": "D+5", "NY-19": "R+1"}
    assert _pvi(PVI_2022) == {"AK-00": "R+8", "WI-03": "R+4", "WI-08": "R+10"}


def _pvi(html):
    """race_id to PVI from the per-state tables (the ones with a Candidates column)."""
    pvi = parse_pvi_tables(html, required_header="Candidates")
    return dict(zip(pvi["race_id"], pvi["cook_pvi"]))


def test_past_ratings_inferred_solid():
    rows = {row["race_id"]: row for row in build_history_races(2022, PVI_2022, RATINGS_2022)}
    assert rows["AK-00"] == {
        "cycle": 2022, "race_id": "AK-00", "cook_pvi": "R+8",
        "cook_rating": "Lean D", "rating_source": "cook",
    }
    assert rows["WI-03"]["cook_rating"] == "Likely R"
    # WI-08 isn't on the ratings page, so it's inferred Solid from its PVI
    assert rows["WI-08"]["cook_rating"] == "Solid R"
    assert rows["WI-08"]["rating_source"] == "inferred"


def test_stale_sheet_id_matched_by_last_name(results):
    # The sheet lists Malinowski as H2NJ06210, which isn't in webl22. The
    # file's only Democrat named Malinowski in NJ-07 is H8NJ07223.
    malinowski = _race(results, "NJ-07")["Malinowski, Tom"]
    assert malinowski["candidate_id"] == "H8NJ07223"
    assert malinowski["incumbent_challenge"] == "I"


LALOTA_OVERRIDE = {
    "cycle": "2022", "race_id": "NY-01", "name": "LaLota, Nicholas J.", "candidate_id": "H2NY01190",
    "note": "webl22 files him with first and last names swapped (NICK, LALOTA)",
}


def test_override_wins():
    rows = parse_fec_results(SHEET_ROWS, 2022, SUMMARY, overrides=[LALOTA_OVERRIDE])
    lalota = _race(rows, "NY-01")["LaLota, Nicholas J."]
    assert lalota["candidate_id"] == "H2NY01190"
    assert lalota["incumbent_challenge"] == "O"
    # An override for another cycle doesn't apply
    rows = parse_fec_results(SHEET_ROWS, 2022, SUMMARY, overrides=[{**LALOTA_OVERRIDE, "cycle": "2024"}])
    assert _race(rows, "NY-01")["LaLota, Nicholas J."]["candidate_id"] == "H0NY02200"


def test_sheet_incumbent_flag_and_vote_share(results):
    # is_incumbent comes from the sheet's own "(I)" column. Peltola is "(I)*",
    # a 2022 special election winner, and still counts.
    assert _race(results, "AK-00")["Peltola, Mary S."]["is_incumbent"] == 1
    assert _race(results, "GA-02")["Bishop, Sanford"]["is_incumbent"] == 1
    assert _race(results, "NY-01")["LaLota, Nicholas J."]["is_incumbent"] == 0
    # Vote share in percent; a fusion candidate gets the combined share
    assert _race(results, "GA-02")["Bishop, Sanford"]["vote_share"] == pytest.approx(54.974, abs=0.001)
    assert _race(results, "NY-01")["LaLota, Nicholas J."]["vote_share"] == pytest.approx(55.499, abs=0.001)


# 2024: real tables from the post-certification revision of the elections page
WIKI_2024 = (FIXTURES / "results_2024_sample.html").read_text(encoding="utf-8")
SUMMARY_2024 = parse_summary((FIXTURES / "webl24_sample.txt").read_text(encoding="latin-1"))


@pytest.fixture(scope="module")
def wiki_results():
    return parse_wiki_results(WIKI_2024, 2024, SUMMARY_2024)


def test_wiki_winner_from_check_mark(wiki_results):
    # CA-13 rounds to 50.0% each, so only the check mark says who won
    california = _race(wiki_results, "CA-13")
    assert california["Adam Gray"]["won"] == 1
    assert california["John Duarte"]["won"] == 0
    assert california["Adam Gray"]["vote_share"] == 50.0
    # Wikipedia lists shares, not vote counts
    assert california["Adam Gray"]["votes"] is None


def test_wiki_ranked_choice_uses_first_round_and_final_winner(wiki_results):
    # Both Begich and Peltola have a check mark in the first round (they
    # advanced). Only the instant runoff decides the winner.
    alaska = _race(wiki_results, "AK-00")
    assert set(alaska) == {"Nick Begich III", "Mary Peltola", "John Howe", "Eric Hafner"}
    assert [name for name, row in alaska.items() if row["won"]] == ["Nick Begich III"]
    assert alaska["Nick Begich III"]["vote_share"] == 48.4


def test_wiki_race_without_shares(wiki_results):
    indiana = _race(wiki_results, "IN-01")
    assert len(indiana) == 3
    assert indiana["Frank J. Mrvan"]["won"] == 1
    assert all(row["vote_share"] is None for row in indiana.values())


def test_wiki_one_winner_per_race(wiki_results):
    race_ids = {row["race_id"] for row in wiki_results}
    assert race_ids == {"AL-01", "AK-00", "CA-13", "GA-02", "GA-11", "IN-01", "LA-06", "NJ-07"}
    for race_id in race_ids:
        assert sum(row["won"] for row in wiki_results if row["race_id"] == race_id) == 1


def test_wiki_is_incumbent(wiki_results):
    # AL-01 lists two incumbents. Moore, on the continuation row, is the nominee.
    assert _race(wiki_results, "AL-01")["Barry Moore"]["is_incumbent"] == 1
    assert _race(wiki_results, "AL-01")["Tom Holmes"]["is_incumbent"] == 0
    assert _race(wiki_results, "AK-00")["Mary Peltola"]["is_incumbent"] == 1
    assert _race(wiki_results, "CA-13")["John Duarte"]["is_incumbent"] == 1
    assert _race(wiki_results, "CA-13")["Adam Gray"]["is_incumbent"] == 0
    # Nickname: the incumbent column says "Thomas Kean Jr."
    assert _race(wiki_results, "NJ-07")["Tom Kean Jr."]["is_incumbent"] == 1


def test_wiki_ids_matched_by_race_and_last_name(wiki_results):
    georgia = _race(wiki_results, "GA-02")
    assert georgia["Sanford Bishop"]["candidate_id"] == "H2GA02031"
    # FEC: "JOHNSON, ARTHUR WAYNE"
    assert georgia["Wayne Johnson"]["candidate_id"] == "H2GA02163"
    assert georgia["Wayne Johnson"]["incumbent_challenge"] == "C"
    assert _race(wiki_results, "AK-00")["Nick Begich III"]["candidate_id"] == "H2AK01083"
    # Elbert Guillory has two FEC registrations with one committee and
    # identical totals (H4LA06229, H4LA06237). They are one campaign, so the
    # first ID is used instead of leaving him unmatched.
    assert _race(wiki_results, "LA-06")["Elbert Guillory"]["candidate_id"] == "H4LA06229"


def test_wiki_parties_and_notes(wiki_results):
    assert _race(wiki_results, "GA-02")["Sanford Bishop"]["party"] == "DEM"
    # "(Ind. Democrat) (write-in)": the note is dropped, and the party isn't DEM
    assert _race(wiki_results, "GA-11")["Tracey Verhoeven"]["party"] == "Ind. Democrat"
    # Louisiana's November jungle election: four Democrats, so not D versus R
    assert _race(wiki_results, "LA-06")["Cleo Fields"]["won"] == 1
    assert "LA-06" not in dem_vs_rep_races(wiki_results)
