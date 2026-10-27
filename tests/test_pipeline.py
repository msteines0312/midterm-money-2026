"""Tests for src/pipeline.py, using saved API fixtures instead of the network."""

import json
from pathlib import Path

import pytest

from src.config import DB_PATH, SAMPLE_DB_PATH
from src.db import connect, create_schema, upsert_rows
from src.pipeline import ENDPOINTS, database_for, main, orphan_counts, rebuild_outside_spending, run_pull

FIXTURES = Path(__file__).parent / "fixtures"
# Real rows from the FEC bulk summary file: 3 House campaigns and 1 Senate
SUMMARY = (FIXTURES / "webl_sample.txt").read_text(encoding="latin-1")
# Real rows from the FEC bulk independent expenditure file, including CLF rows with no candidate ID
IE_SAMPLE = (FIXTURES / "ie_sample.csv").read_text(encoding="latin-1")
FIXTURE_FOR_PATH = {path: name for name, (path, _) in ENDPOINTS.items()}

RACES = [{
    "race_id": "TX-31", "state": "TX", "district": "31",
    "cook_rating": "Solid R", "cook_pvi": "R+12", "rating_source": "inferred",
}]


class FakeClient:
    """Serves each endpoint's saved fixture and records every request."""

    def __init__(self, candidates=None):
        self.calls = []
        self.candidates = candidates

    def iter_results(self, path, params=None, max_pages=None):
        self.calls.append((path, dict(params or {})))
        if path == "/candidates/" and self.candidates is not None:
            return iter(self.candidates)
        return iter(json.loads((FIXTURES / f"{FIXTURE_FOR_PATH[path]}.json").read_text())["results"])


@pytest.fixture
def conn(tmp_path):
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def pull(client, conn, pulled_at):
    return run_pull(client, conn, pulled_at, RACES, SUMMARY, IE_SAMPLE, pac_industries=[])


def test_run_pull_fills_every_table(conn):
    counts = pull(FakeClient(), conn, "2026-10-20")
    assert counts["pac_industries"] == 0
    assert all(n > 0 for table, n in counts.items() if table != "pac_industries")


def test_rerun_same_day_does_not_duplicate(conn):
    pull(FakeClient(), conn, "2026-10-20")
    first = count(conn, "candidate_totals")
    pull(FakeClient(), conn, "2026-10-20")
    assert count(conn, "candidate_totals") == first


def test_new_day_appends_snapshot(conn):
    pull(FakeClient(), conn, "2026-10-20")
    first_totals, first_candidates = count(conn, "candidate_totals"), count(conn, "candidates")
    pull(FakeClient(), conn, "2026-10-23")
    assert count(conn, "candidate_totals") == 2 * first_totals
    assert count(conn, "candidates") == first_candidates


def test_no_outside_spending_api_calls(conn):
    # Outside spending now comes from the bulk file, so the API is never asked for it
    client = FakeClient()
    pull(client, conn, "2026-10-20")
    assert not any("/schedules/" in path for path, _ in client.calls)


def test_rerun_same_day_does_not_duplicate_spending(conn):
    pull(FakeClient(), conn, "2026-10-20")
    first = count(conn, "outside_spending")
    pull(FakeClient(), conn, "2026-10-20")
    assert count(conn, "outside_spending") == first


def test_sample_pull_uses_a_separate_database():
    assert database_for(sample=True) == SAMPLE_DB_PATH
    assert database_for(sample=False) == DB_PATH
    assert SAMPLE_DB_PATH != DB_PATH


def test_orphan_counts_reports_missing_race(conn):
    create_schema(conn)
    upsert_rows(conn, "candidates", [{
        "candidate_id": "H6DC00001", "name": "DELEGATE", "party": "DEM", "state": "DC",
        "district": "00", "race_id": "DC-00", "incumbent_challenge": "I", "primary_result": None,
    }])
    assert orphan_counts(conn)["candidates_without_race"] == 1


def test_orphan_counts_reports_unmatched_spending(conn):
    # The fixture's CLF rows have no candidate ID and none of the fixture
    # candidates are in WA-05, so they stay unmatched
    pull(FakeClient(), conn, "2026-10-20")
    assert orphan_counts(conn)["spending_without_candidate"] >= 1


LABEL = {"network": "Net", "industry": "crypto", "source_url": "http://example.com"}


def test_committee_removed_from_labels_disappears(conn):
    # A committee taken out of pac_industries.csv must stop counting on the next pull
    labels = [{"committee_id": "C1", **LABEL}, {"committee_id": "C2", **LABEL}]
    run_pull(FakeClient(), conn, "2026-10-20", RACES, SUMMARY, IE_SAMPLE, pac_industries=labels)
    run_pull(FakeClient(), conn, "2026-10-20", RACES, SUMMARY, IE_SAMPLE, pac_industries=labels[:1])
    assert [row[0] for row in conn.execute("SELECT committee_id FROM pac_industries")] == ["C1"]


# A candidates-table row for the fixture's CLF candidate, whose filings have no ID
BAUMGARTNER = {
    "candidate_id": "H6WA05999", "name": "BAUMGARTNER, MICHAEL", "party": "REP", "state": "WA",
    "district": "05", "race_id": "WA-05", "incumbent_challenge": "I", "primary_result": None,
}
CLF = "C00504530"


def clf_keys(conn, pulled_at):
    sql = "SELECT candidate_key FROM outside_spending WHERE committee_id = ? AND pulled_at = ?"
    return [row[0] for row in conn.execute(sql, (CLF, pulled_at))]


def test_rebuild_replaces_only_that_dates_outside_spending(conn):
    pull(FakeClient(), conn, "2026-10-20")
    pull(FakeClient(), conn, "2026-10-23")
    assert clf_keys(conn, "2026-10-23") == ["WA-05|BAUMGARTNER"]
    totals_before = conn.execute("SELECT * FROM candidate_totals ORDER BY candidate_id, pulled_at").fetchall()
    spending_rows = count(conn, "outside_spending")

    # The candidate shows up in `candidates` later, so the rebuild can match the CLF rows
    upsert_rows(conn, "candidates", [BAUMGARTNER])
    rebuild_outside_spending(conn, IE_SAMPLE, "2026-10-23")

    # The old key is deleted rather than left beside the new one, which would double count
    assert clf_keys(conn, "2026-10-23") == ["H6WA05999"]
    assert clf_keys(conn, "2026-10-20") == ["WA-05|BAUMGARTNER"]
    assert count(conn, "outside_spending") == spending_rows
    assert conn.execute("SELECT * FROM candidate_totals ORDER BY candidate_id, pulled_at").fetchall() == totals_before


def test_rebuild_flag_uses_saved_file_and_no_api(conn, monkeypatch):
    pull(FakeClient(), conn, "2026-10-23")
    upsert_rows(conn, "candidates", [BAUMGARTNER])
    read_dates = []

    def fake_read(pulled_at):
        read_dates.append(pulled_at)
        return IE_SAMPLE

    def no_api(*args, **kwargs):
        raise AssertionError("a rebuild must not call the FEC API")

    monkeypatch.setattr("src.pipeline.read_saved_independent_expenditures", fake_read)
    monkeypatch.setattr("src.pipeline.FecClient", no_api)
    # main() closes the connection it opens, so hand it a second one to the same file
    db_file = conn.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setattr("src.pipeline.database_for", lambda sample: db_file)
    main(["--rebuild-outside-spending", "2026-10-23"])

    assert read_dates == ["2026-10-23"]
    assert clf_keys(conn, "2026-10-23") == ["H6WA05999"]
