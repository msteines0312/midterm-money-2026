"""Tests for src/pipeline.py, using saved API fixtures instead of the network."""

import json
from pathlib import Path

import pytest

from src.config import DB_PATH, SAMPLE_DB_PATH
from src.db import connect, create_schema, upsert_rows
from src.pipeline import ENDPOINTS, database_for, orphan_counts, run_pull

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

