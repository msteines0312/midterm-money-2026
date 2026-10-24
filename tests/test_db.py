"""Tests for src/db.py and src/schema.sql."""

import pytest

from src.db import connect, create_schema, upsert_rows

TABLES = {"races", "candidates", "committees", "candidate_totals", "outside_spending", "pac_industries"}


def totals(pulled_at, receipts=1000.0):
    return {
        "candidate_id": "H6XX00001", "pulled_at": pulled_at, "coverage_end_date": "2026-09-30",
        "receipts": receipts, "disbursements": 500.0, "cash_on_hand": 500.0, "debts_owed": 0.0,
        "individual_contributions": 900.0, "pac_contributions": 100.0, "party_contributions": 0.0,
        "candidate_self_funding": 0.0, "external_contributions": 1000.0,
    }


def candidate(name):
    return {
        "candidate_id": "H6XX00001", "name": name, "party": "DEM", "state": "XX",
        "district": "01", "race_id": "XX-01", "incumbent_challenge": "C", "primary_result": None,
    }


@pytest.fixture
def conn(tmp_path):
    conn = connect(tmp_path / "test.db")
    create_schema(conn)
    yield conn
    conn.close()


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_create_schema_is_repeatable(conn):
    create_schema(conn)
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert TABLES <= names


def test_upsert_same_row_twice_keeps_one(conn):
    upsert_rows(conn, "candidates", [candidate("First Name")])
    upsert_rows(conn, "candidates", [candidate("Second Name")])
    assert count(conn, "candidates") == 1
    assert conn.execute("SELECT name FROM candidates").fetchone()[0] == "Second Name"


def test_new_pulled_at_appends_snapshot(conn):
    upsert_rows(conn, "candidate_totals", [totals("2026-10-20")])
    upsert_rows(conn, "candidate_totals", [totals("2026-10-23")])
    assert count(conn, "candidate_totals") == 2


def test_upsert_rejects_unknown_table(conn):
    with pytest.raises(ValueError, match="nope"):
        upsert_rows(conn, "nope", [{"a": 1}])


def test_null_money_stays_null(conn):
    upsert_rows(conn, "candidate_totals", [totals("2026-10-20", receipts=None)])
    assert conn.execute("SELECT receipts FROM candidate_totals").fetchone()[0] is None


def new_style_spending_row():
    return {
        "committee_id": "C00000001", "candidate_key": "XX-01|SMITH", "candidate_id": None,
        "candidate_name": "SMITH, JANE", "party": "DEM", "race_id": "XX-01",
        "election_type": "G", "support_oppose": "S", "pulled_at": "2026-10-23",
        "total": 250.0, "count": 1,
    }


def test_create_schema_moves_old_outside_spending(tmp_path):
    conn = connect(tmp_path / "old.db")
    # The table as the Oct 23 pull built it, before election_type existed
    conn.execute(
        """CREATE TABLE outside_spending (
            committee_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
            support_oppose TEXT NOT NULL, pulled_at TEXT NOT NULL,
            total REAL, count INTEGER,
            PRIMARY KEY (committee_id, candidate_id, support_oppose, pulled_at))"""
    )
    conn.execute(
        "INSERT INTO outside_spending VALUES ('C00000001', 'H6XX00001', 'S', '2026-10-23', 100.0, 2)"
    )
    conn.commit()

    create_schema(conn)

    assert count(conn, "outside_spending_by_candidate_endpoint") == 1
    assert count(conn, "outside_spending") == 0
    columns = {row[1] for row in conn.execute("PRAGMA table_info(outside_spending)")}
    assert "election_type" in columns
    conn.close()


def test_create_schema_twice_keeps_new_rows(conn):
    upsert_rows(conn, "outside_spending", [new_style_spending_row()])
    create_schema(conn)
    assert count(conn, "outside_spending") == 1
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "outside_spending_by_candidate_endpoint" not in names


def test_create_schema_rebuilds_pac_industries_without_network(tmp_path):
    conn = connect(tmp_path / "old.db")
    # The label table as it was before the network column was added
    conn.execute(
        """CREATE TABLE pac_industries (
            committee_id TEXT PRIMARY KEY, industry TEXT NOT NULL, source_url TEXT NOT NULL)"""
    )
    conn.commit()

    create_schema(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(pac_industries)")}
    assert "network" in columns
    conn.close()


def test_create_schema_twice_keeps_pac_industries_rows(conn):
    row = {"committee_id": "C001", "network": "Fairshake", "industry": "crypto", "source_url": "https://a"}
    upsert_rows(conn, "pac_industries", [row])
    create_schema(conn)
    assert count(conn, "pac_industries") == 1
