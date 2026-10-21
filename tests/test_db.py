"""Tests for src/db.py and src/schema.sql."""

import pytest

from src.db import connect, create_schema, upsert_rows

TABLES = {"races", "candidates", "committees", "candidate_totals", "outside_spending", "pac_industries"}


def totals(pulled_at, receipts=1000.0):
    return {
        "candidate_id": "H6XX00001", "pulled_at": pulled_at, "receipts": receipts,
        "disbursements": 500.0, "cash_on_hand": 500.0,
        "individual_contributions": 900.0, "pac_contributions": 100.0,
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
