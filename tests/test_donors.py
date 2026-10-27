"""Tests for src/fec/donors.py.

The rows come from real Schedule A and committee totals responses saved by
`python scripts/save_fixtures.py donors`, so the field names are the API's own.
"""

import json
from collections import Counter

import pytest

from src.config import PROJECT_ROOT
from src.fec.donors import (
    contribution_row,
    contributions_by_name,
    contributions_to_committee,
    drop_already_processed,
    drop_superseded_efile,
    efile_contribution_row,
    efile_contributions,
    large_contributions,
    net_amount,
    pac_totals_rows,
)

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
PULLED_AT = "2026-10-26"


@pytest.fixture(scope="module")
def schedule_a():
    return json.loads((FIXTURES / "schedule_a_sample.json").read_text())["results"]


@pytest.fixture(scope="module")
def pac_totals():
    return json.loads((FIXTURES / "pac_totals_sample.json").read_text())


class RecordingClient:
    """Stands in for FecClient: records the query and returns canned rows."""

    def __init__(self, rows=None, totals=None):
        self.rows, self.totals, self.calls = rows or [], totals or {}, []

    def iter_keyset(self, path, params=None, max_pages=None):
        self.calls.append((path, dict(params)))
        yield from self.rows

    def iter_results(self, path, params=None, max_pages=None):
        self.calls.append((path, dict(params)))
        yield from self.rows

    def get(self, path, params=None):
        self.calls.append((path, dict(params)))
        return self.totals[path.split("/")[2]]


def test_contribution_row_fields(schedule_a):
    individual = next(r for r in schedule_a if r["entity_type"] == "IND" and r["memo_code"] != "X")
    row = contribution_row(individual, PULLED_AT)
    assert row == {
        "sub_id": individual["sub_id"],
        "cycle": 2026,
        "committee_id": individual["committee_id"],
        "contributor_name": individual["contributor_name"],
        "entity_type": "IND",
        "amount": individual["contribution_receipt_amount"],
        "receipt_date": individual["contribution_receipt_date"],
        "memo_code": individual["memo_code"],
        "pulled_at": PULLED_AT,
    }


def test_sample_covers_every_entity_type_and_a_memo_row(schedule_a):
    assert {"IND", "ORG", "PAC"} <= {r["entity_type"] for r in schedule_a}
    assert any(r["memo_code"] == "X" for r in schedule_a)


def test_memo_rows_excluded_from_net(schedule_a):
    rows = [contribution_row(r, PULLED_AT) for r in schedule_a]
    memo_total = sum(r["amount"] for r in rows if r["memo_code"] == "X")
    all_total = sum(r["amount"] for r in rows)
    assert memo_total != 0
    assert net_amount(rows) == pytest.approx(all_total - memo_total)


def test_refunds_reduce_net(schedule_a):
    refunds = [contribution_row(r, PULLED_AT) for r in schedule_a
               if r["contribution_receipt_amount"] < 0 and r["memo_code"] != "X"]
    gift = {"amount": 1_000_000.0, "memo_code": None}
    assert refunds
    assert net_amount([gift, *refunds]) == pytest.approx(1_000_000.0 + sum(r["amount"] for r in refunds))
    assert net_amount([gift, *refunds]) < 1_000_000.0


def test_pac_totals_row_fields(pac_totals):
    client = RecordingClient(totals=pac_totals)
    rows = pac_totals_rows(client, 2026, ["C00879510"], PULLED_AT)
    source = pac_totals["C00879510"]["results"][0]
    assert rows == [{
        "committee_id": "C00879510",
        "cycle": 2026,
        "receipts": source["receipts"],
        "independent_expenditures": source["independent_expenditures"],
        "coverage_end_date": source["coverage_end_date"][:10],
        "pulled_at": PULLED_AT,
    }]
    assert client.calls == [("/committee/C00879510/totals/", {"cycle": 2026})]


def test_large_contributions_query(schedule_a):
    client = RecordingClient(rows=schedule_a)
    assert large_contributions(client, 2026, 250000) == schedule_a
    path, params = client.calls[0]
    assert path == "/schedules/schedule_a/"
    assert params["two_year_transaction_period"] == 2026
    assert params["min_amount"] == 250000
    assert params["recipient_committee_type"] == ["O", "V", "W"]
    assert params["sort"] == "-contribution_receipt_amount"


def test_by_name_and_by_committee_queries():
    client = RecordingClient()
    contributions_by_name(client, 2026, "MUSK, ELON")
    contributions_to_committee(client, 2026, "C00879510")
    by_name, by_committee = (call[1] for call in client.calls)
    assert by_name["contributor_name"] == "MUSK, ELON"
    assert by_name["recipient_committee_type"] == ["O", "V", "W"]
    assert "min_amount" not in by_name
    assert by_committee["committee_id"] == "C00879510"


# ---- Raw e-filings, for reports the processed Schedule A does not have yet ----


@pytest.fixture(scope="module")
def efile():
    return json.loads((FIXTURES / "efile_schedule_a_sample.json").read_text())["results"]


def test_efile_row_fields_and_cleaned_name(efile):
    """The raw name has a doubled space, which is collapsed so it matches Schedule A spellings."""
    gift = next(r for r in efile if r["contribution_receipt_amount"] == 43_200_000)
    assert efile_contribution_row(gift, PULLED_AT) == {
        "sub_id": "efile-2038959-SA11A.1249",
        "cycle": 2026,
        "committee_id": "C00879510",
        "contributor_name": "MUSK, ELON",
        "entity_type": "IND",
        "amount": 43_200_000.0,
        "receipt_date": "2026-10-14",
        "memo_code": None,
        "pulled_at": PULLED_AT,
    }


def test_efile_trailing_comma_removed(efile):
    org = next(r for r in efile if r["entity_type"] == "ORG")
    assert efile_contribution_row(org, PULLED_AT)["contributor_name"] == "UNITED STATES OF AMERICA INC"


def test_efile_keeps_memo_code(efile):
    """Memo rows are kept as filed. The totals leave them out, the same as for Schedule A."""
    memo = next(r for r in efile if r["memo_code"] == "X")
    assert efile_contribution_row(memo, PULLED_AT)["memo_code"] == "X"


def test_efile_contributions_queries_the_efile_endpoint(efile):
    client = RecordingClient(rows=efile)
    assert efile_contributions(client, "C00879510", "2026-07-01") == efile
    path, params = client.calls[0]
    assert path == "/schedules/schedule_a/efile/"
    assert params["committee_id"] == "C00879510" and params["min_date"] == "2026-07-01"


def test_amended_filing_replaces_the_original(efile):
    """An amendment repeats the transaction under a higher file number. Only it counts."""
    original = efile[2]
    amended = {**original, "file_number": original["file_number"] + 1, "contribution_receipt_amount": 40_000_000.0}
    kept = drop_superseded_efile([original, amended, efile[3]])
    assert amended in kept and original not in kept and efile[3] in kept


def processed_counts(*rows):
    """How many processed Schedule A rows share each (committee, date, amount, memo) key."""
    return Counter((r["committee_id"], r["receipt_date"], r["amount"], r["memo_code"]) for r in rows)


def test_rows_schedule_a_already_has_are_dropped(efile):
    """Once the API processes a filing the same gift appears there, so it must not count twice."""
    row = efile_contribution_row(efile[2], PULLED_AT)
    other = efile_contribution_row(efile[3], PULLED_AT)
    assert drop_already_processed([row, other], processed_counts(row)) == [other]


def test_efile_mixed_case_name_is_uppercased(efile):
    """Raw filings often say "Yass, Jeff" where Schedule A says "YASS, JEFF"."""
    gift = {**efile[2], "contributor_name": "Yass,  Jeff"}
    assert efile_contribution_row(gift, PULLED_AT)["contributor_name"] == "YASS, JEFF"


def test_same_gift_spelled_differently_is_recognized_as_already_processed(efile):
    """Schedule A says "YASS, JEFF MR." where the raw filing says "YASS, MR. JEFF". The name is not the key."""
    raw = efile_contribution_row({**efile[2], "contributor_name": "Musk, Mr. Elon"}, PULLED_AT)
    processed = {**raw, "contributor_name": "MUSK, ELON MR."}
    assert drop_already_processed([raw], processed_counts(processed)) == []


def test_two_equal_gifts_on_one_day_are_not_merged(efile):
    """Two real $43.2M gifts on one day are two gifts. One processed copy cancels only one raw copy."""
    raw = efile_contribution_row(efile[2], PULLED_AT)
    second = {**raw, "sub_id": "efile-2038959-SA11A.9999"}
    assert drop_already_processed([raw, second], processed_counts(raw)) == [second]
