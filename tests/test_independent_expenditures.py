"""Tests for src/fec/independent_expenditures.py, run against real rows from the FEC's bulk file.

Fixture rows (tests/fixtures/ie_sample.csv, see scripts/save_fixtures.py):
- CLF (C00504530), blank cand_id, WA-05: two rows, $20,500 and $100,000.
- New Leadership Now (C00900993), CA-04 primary: one transaction filed as
  the original ($51,601), A1 ($64,246) and A2 ($64,250).
- Bennett (NJ-07) and Conley (NY-17): ordinary House rows with a cand_id.
- Begich (AK at-large, district "00"), a Senate row, and a presidential row.
"""

import csv
import io
import os
from datetime import datetime
from pathlib import Path

import pytest

from src.fec.independent_expenditures import (
    drop_superseded,
    house_outside_spending,
    parse_independent_expenditures,
    read_saved_independent_expenditures,
)
from src.fec.transform import race_id

SAMPLE = (Path(__file__).parent / "fixtures" / "ie_sample.csv").read_text(encoding="latin-1")

CLF = "C00504530"
CLF_TOTAL = 20500.0 + 100000.0
SENATE_ID = "S6FL00830"
PRESIDENT_ID = "P00009423"
# What the candidates table would hold for the CLF candidate
BAUMGARTNER = {"candidate_id": "H6XX01234", "race_id": "WA-05", "name": "BAUMGARTNER, MICHAEL", "party": "REP"}


def blanked(text, tran_id, field, value=""):
    """Copy of the fixture text with one field of one real transaction changed."""
    rows = list(csv.DictReader(io.StringIO(text)))
    for row in rows:
        if row["tran_id"] == tran_id:
            row[field] = value
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def clf_row(rows):
    """The single output row for CLF spending, which has no candidate ID in the bulk file."""
    (row,) = [r for r in rows if r["committee_id"] == CLF]
    return row


def test_drop_superseded_keeps_only_latest_amendment():
    rows = drop_superseded(parse_independent_expenditures(SAMPLE))
    versions = [r for r in rows if r["tran_id"] == "WFT2026441236-1"]
    assert len(versions) == 1
    assert versions[0]["amndt_ind"] == "A2"
    assert versions[0]["exp_amo"] == "64250"


def test_drop_superseded_removes_filings_listed_as_previous():
    rows = drop_superseded(parse_independent_expenditures(SAMPLE))
    previous = {r["prev_file_num"] for r in rows if r["prev_file_num"]}
    assert not previous & {r["file_num"] for r in rows}


def test_house_only():
    rows = house_outside_spending(SAMPLE, [], "2026-10-23")
    assert rows
    ids = {r["candidate_id"] for r in rows}
    assert SENATE_ID not in ids
    assert PRESIDENT_ID not in ids
    assert all(r["race_id"] != "FL-00" for r in rows)


def test_aggregates_by_committee_candidate_support_election():
    # Both CLF rows are for the same candidate, support, and general election
    row = clf_row(house_outside_spending(SAMPLE, [], "2026-10-23"))
    assert row["total"] == CLF_TOTAL
    assert row["count"] == 2


def test_blank_id_matched_by_race_and_last_name():
    row = clf_row(house_outside_spending(SAMPLE, [BAUMGARTNER], "2026-10-23"))
    assert row["candidate_id"] == "H6XX01234"
    assert row["candidate_key"] == "H6XX01234"
    assert row["party"] == "REP"


def test_blank_id_unmatched_keeps_race_and_money():
    row = clf_row(house_outside_spending(SAMPLE, [], "2026-10-23"))
    assert row["candidate_id"] is None
    assert row["race_id"] == "WA-05"
    assert row["total"] == CLF_TOTAL
    assert row["candidate_key"] == "WA-05|BAUMGARTNER"


def test_blank_id_ambiguous_last_name_not_guessed():
    twin = {**BAUMGARTNER, "candidate_id": "H6XX09999", "name": "BAUMGARTNER, JANE", "party": "DEM"}
    row = clf_row(house_outside_spending(SAMPLE, [BAUMGARTNER, twin], "2026-10-23"))
    assert row["candidate_id"] is None
    assert row["candidate_key"] == "WA-05|BAUMGARTNER"


def test_election_type_kept():
    rows = house_outside_spending(SAMPLE, [], "2026-10-23")
    (primary,) = [r for r in rows if r["committee_id"] == "C00900993"]
    assert primary["election_type"] == "P"
    # Only the A2 amount counts, not the three versions added together
    assert primary["total"] == 64250.0
    assert primary["count"] == 1


def test_party_comes_from_candidates_table_when_known():
    known = {"candidate_id": "H6NJ07201", "race_id": "NJ-07", "name": "BENNETT, REBECCA", "party": "DEM"}
    rows = house_outside_spending(SAMPLE, [known], "2026-10-23")
    (bennett,) = [r for r in rows if r["candidate_id"] == "H6NJ07201"]
    assert bennett["party"] == "DEM"
    # Not in `candidates`, so the bulk file's wording is translated to a code
    (conley,) = [r for r in rows if r["candidate_id"] == "H6NY17171"]
    assert conley["party"] == "DEM"


def test_unmapped_party_is_kept_as_written():
    text = blanked(SAMPLE, "500370948", "cand_pty_aff", "INDEPENDENT")
    rows = house_outside_spending(text, [], "2026-10-23")
    (conley,) = [r for r in rows if r["candidate_id"] == "H6NY17171"]
    assert conley["party"] == "INDEPENDENT"


def test_race_id_matches_transform():
    rows = house_outside_spending(SAMPLE, [], "2026-10-23")
    (begich,) = [r for r in rows if r["candidate_id"] == "H2AK01083"]
    assert begich["race_id"] == race_id("AK", "00") == "AK-00"


def test_rows_match_table_columns():
    expected = {
        "committee_id", "candidate_key", "candidate_id", "candidate_name", "party",
        "race_id", "election_type", "support_oppose", "pulled_at", "total", "count",
    }
    rows = house_outside_spending(SAMPLE, [], "2026-10-23")
    assert all(set(r) == expected for r in rows)
    assert {r["pulled_at"] for r in rows} == {"2026-10-23"}


def test_parse_turns_blanks_into_none():
    rows = parse_independent_expenditures(SAMPLE)
    clf = [r for r in rows if r["spe_id"] == CLF]
    assert all(r["cand_id"] is None for r in clf)
    assert clf[0]["exp_amo"] == "20500"


def test_blank_amount_row_is_skipped():
    text = blanked(SAMPLE, "SE24.6708", "exp_amo")
    row = clf_row(house_outside_spending(text, [], "2026-10-23"))
    assert row["total"] == 20500.0
    assert row["count"] == 1


def test_blank_support_oppose_row_is_skipped():
    # Real filings exist with no S or O. They can't be counted as either side.
    text = blanked(SAMPLE, "SE24.6708", "sup_opp")
    row = clf_row(house_outside_spending(text, [], "2026-10-23"))
    assert row["total"] == 20500.0
    assert row["count"] == 1


def test_blank_candidate_name_does_not_crash():
    text = blanked(SAMPLE, "SE24.6747", "cand_name")
    rows = house_outside_spending(text, [BAUMGARTNER], "2026-10-23")
    # The nameless row can't be matched, so it sits apart from the named one
    assert sorted(r["candidate_id"] or "" for r in rows if r["committee_id"] == CLF) == ["", "H6XX01234"]


def test_blank_file_number_does_not_crash():
    text = blanked(SAMPLE, "SE24.6747", "file_num")
    rows = drop_superseded(parse_independent_expenditures(text))
    assert any(r["tran_id"] == "SE24.6747" for r in rows)


def test_blank_district_uses_known_candidates_race():
    text = blanked(SAMPLE, "500370948", "can_office_dis")
    conley = {"candidate_id": "H6NY17171", "race_id": "NY-17", "name": "CONLEY, CAIT", "party": "DEM"}
    rows = house_outside_spending(text, [conley], "2026-10-23")
    (row,) = [r for r in rows if r["candidate_id"] == "H6NY17171"]
    assert row["race_id"] == "NY-17"


def test_blank_district_unknown_candidate_has_no_race():
    text = blanked(SAMPLE, "500370948", "can_office_dis")
    rows = house_outside_spending(text, [], "2026-10-23")
    (row,) = [r for r in rows if r["candidate_id"] == "H6NY17171"]
    assert row["race_id"] is None


def test_blank_district_and_id_keys_on_state_and_last_name():
    text = blanked(blanked(SAMPLE, "SE24.6747", "can_office_dis"), "SE24.6708", "can_office_dis")
    row = clf_row(house_outside_spending(text, [BAUMGARTNER], "2026-10-23"))
    assert row["race_id"] is None
    assert row["candidate_id"] is None
    assert row["candidate_key"] == "WA|BAUMGARTNER"
    assert row["total"] == CLF_TOTAL


# Bennett as the candidates table would hold her. The tests below give her
# fixture row a different ID, like a candidate who got a new FEC ID.
BENNETT = {"candidate_id": "H6NJ07201", "race_id": "NJ-07", "name": "BENNETT, REBECCA", "party": "DEM"}
UNKNOWN_ID = "H6NJ07999"


def test_unknown_id_matched_by_race_and_last_name():
    text = blanked(SAMPLE, "500370949", "cand_id", UNKNOWN_ID)
    rows = house_outside_spending(text, [BENNETT], "2026-10-23")
    (bennett,) = [r for r in rows if r["candidate_name"] == "BENNETT, REBECCA"]
    assert bennett["candidate_id"] == "H6NJ07201"
    assert bennett["candidate_key"] == "H6NJ07201"
    assert bennett["party"] == "DEM"


def test_unknown_id_kept_when_no_candidate_matches():
    text = blanked(SAMPLE, "500370949", "cand_id", UNKNOWN_ID)
    rows = house_outside_spending(text, [], "2026-10-23")
    (bennett,) = [r for r in rows if r["candidate_name"] == "BENNETT, REBECCA"]
    assert bennett["candidate_id"] == UNKNOWN_ID
    assert bennett["candidate_key"] == UNKNOWN_ID


def test_unknown_id_kept_when_last_name_is_ambiguous():
    twin = {**BENNETT, "candidate_id": "H6NJ07888", "name": "BENNETT, JOHN", "party": "REP"}
    text = blanked(SAMPLE, "500370949", "cand_id", UNKNOWN_ID)
    rows = house_outside_spending(text, [BENNETT, twin], "2026-10-23")
    (bennett,) = [r for r in rows if r["candidate_name"] == "BENNETT, REBECCA"]
    assert bennett["candidate_id"] == UNKNOWN_ID


def saved_copy(tmp_path, saved_on):
    """Write the fixture where a pull would save it, dated as if downloaded on `saved_on`."""
    path = tmp_path / "independent_expenditure_2026.csv"
    path.write_bytes(SAMPLE.encode("latin-1"))
    stamp = datetime.fromisoformat(f"{saved_on}T21:10:00").timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_read_saved_file_from_the_pull_date(tmp_path):
    path = saved_copy(tmp_path, "2026-10-23")
    assert read_saved_independent_expenditures("2026-10-23", path) == SAMPLE


def test_read_saved_file_refuses_a_newer_download(tmp_path):
    # A file saved by a later pull holds newer filings, which must not get the old date
    path = saved_copy(tmp_path, "2026-10-24")
    with pytest.raises(ValueError, match="2026-10-24"):
        read_saved_independent_expenditures("2026-10-23", path)
