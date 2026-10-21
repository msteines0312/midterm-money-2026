"""Tests for src/pipeline.py, using saved API fixtures instead of the network."""

import json
from pathlib import Path

import pytest

from src.config import DB_PATH, SAMPLE_DB_PATH
from src.db import connect, create_schema, upsert_rows
from src.pipeline import ENDPOINTS, OUTSIDE_SPENDING_PATH, database_for, orphan_counts, run_pull

FIXTURES = Path(__file__).parent / "fixtures"
# Real rows from the FEC bulk summary file: 3 House campaigns and 1 Senate
SUMMARY = (FIXTURES / "webl_sample.txt").read_text(encoding="latin-1")
SUMMARY_HOUSE_IDS = {"H6KY06259", "H6FL13239", "H2AK01083"}
FIXTURE_FOR_PATH = {**{path: name for name, (path, _) in ENDPOINTS.items()}, OUTSIDE_SPENDING_PATH: "outside_spending"}

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
    return run_pull(client, conn, pulled_at, RACES, SUMMARY, pac_industries=[])


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


def test_outside_spending_is_requested_in_batches_of_100(conn):
    template = json.loads((FIXTURES / "candidates.json").read_text())["results"][0]
    candidates = [{**template, "candidate_id": f"H6XX{i:05d}"} for i in range(250)]
    client = FakeClient(candidates=candidates)
    pull(client, conn, "2026-10-20")

    batches = [params["candidate_id"] for path, params in client.calls if path == OUTSIDE_SPENDING_PATH]
    # 250 from /candidates/ plus the 3 House campaigns in the summary fixture = 253 IDs
    assert [len(b) for b in batches] == [100, 100, 53]


def test_outside_spending_covers_candidates_from_both_sources(conn):
    # The API candidate list and the bulk summary file don't contain exactly the
    # same campaigns, so spending is requested for both or some money is never seen
    client = FakeClient()
    pull(client, conn, "2026-10-20")

    api_ids = {r["candidate_id"] for r in json.loads((FIXTURES / "candidates.json").read_text())["results"]}

    requested = {cid for path, params in client.calls if path == OUTSIDE_SPENDING_PATH
                 for cid in params["candidate_id"]}
    assert requested == api_ids | SUMMARY_HOUSE_IDS


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
