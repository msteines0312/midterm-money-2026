"""Check the bulk-built outside spending against FEC committee totals.

For each committee, this compares the independent expenditures we computed from
the bulk file with what the committee itself reported to the FEC through its
last periodic report (`/committee/{id}/totals/`). If a few large, well-known
committees match, the aggregation (superseded filings dropped, blank IDs kept)
can be trusted for the rest.

Run from the repo root: python scripts/check_outside_spending.py
"""

import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# Let this script import from src/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import CYCLE, DB_PATH, RAW_DIR, load_api_key  # noqa: E402
from src.db import connect  # noqa: E402
from src.fec.client import FecClient  # noqa: E402
from src.fec.independent_expenditures import drop_superseded, parse_independent_expenditures  # noqa: E402
from src.fec.transform import to_money  # noqa: E402

# Pass means every labeled network committee and the top-10 total are within this
TOLERANCE_PCT = 5.0

# The two largest House-focused super PACs, named in the brief
CLF_ID = "C00504530"
HMP_ID = "C00495028"


def parse_bulk_date(text):
    """Parse the bulk file's "20-OCT-26" dates, returning None for a blank."""
    return datetime.strptime(text, "%d-%b-%y").date() if text else None


def bulk_sum_through(rows, committee_id, coverage_end):
    """Sum one committee's independent expenditures dated on or before a cutoff.

    All offices are included (House, Senate, President), because the committee
    totals endpoint is all-office. Each row is dated by `exp_date`, falling
    back to `dissem_dt` when that is blank. Periodic reports date independent
    expenditures by expenditure date, and the comparison bears that out: dating
    by `dissem_dt` instead left several committees several percent low.

    Parameters
    ----------
    rows : list of dict
        Parsed bulk rows with superseded filings already dropped.
    committee_id : str
    coverage_end : datetime.date
        Last day covered by the committee's periodic reports.

    Returns
    -------
    float
    """
    total = 0.0
    for row in rows:
        if row["spe_id"] != committee_id or row["exp_amo"] is None:
            continue
        spent_on = parse_bulk_date(row["exp_date"] or row["dissem_dt"])
        # A row with neither date can't be placed against the coverage window
        if spent_on is not None and spent_on <= coverage_end:
            total += to_money(row["exp_amo"])
    return total


def percent_difference(ours, reported):
    """Percent our figure differs from the FEC-reported one.

    A zero reported figure has no percentage. If we also have zero, the two
    agree and the result is NaN (nothing to judge). If we have money the
    committee did not report, the result is infinity, which fails the check.
    """
    if reported == 0:
        return float("nan") if ours == 0 else float("inf")
    return (ours - reported) / reported * 100


def compare_to_committee_totals(conn, client, pulled_at, committee_ids):
    """Compare bulk-file totals with the FEC's reported committee totals.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database holding `committees` and the `outside_spending` snapshot.
    client : FecClient
    pulled_at : str
        Snapshot date. Used to confirm the snapshot exists, so the check is
        never run against an empty table.
    committee_ids : list of str

    Returns
    -------
    pandas.DataFrame
        Columns: committee_id, name, bulk_through_coverage, fec_reported,
        coverage_end_date, pct_diff.
    """
    snapshot_rows = conn.execute(
        "SELECT COUNT(*) FROM outside_spending WHERE pulled_at = ?", (pulled_at,)
    ).fetchone()[0]
    if snapshot_rows == 0:
        raise ValueError(f"No outside_spending rows for {pulled_at}. Run the pipeline first.")

    bulk_text = (RAW_DIR / "fec" / f"independent_expenditure_{CYCLE}.csv").read_text(encoding="latin-1")
    bulk_rows = drop_superseded(parse_independent_expenditures(bulk_text))
    names = dict(conn.execute("SELECT committee_id, name FROM committees"))

    records = []
    for committee_id in committee_ids:
        response = client.get(f"/committee/{committee_id}/totals/", {"cycle": CYCLE})
        totals = response["results"][0] if response["results"] else {}
        fec_reported = totals.get("independent_expenditures") or 0.0
        coverage_text = totals.get("coverage_end_date")
        coverage_end = datetime.fromisoformat(coverage_text).date() if coverage_text else date.min
        bulk_total = bulk_sum_through(bulk_rows, committee_id, coverage_end)
        records.append({
            "committee_id": committee_id,
            "name": names.get(committee_id),
            "bulk_through_coverage": bulk_total,
            "fec_reported": fec_reported,
            "coverage_end_date": coverage_text[:10] if coverage_text else None,
            "pct_diff": percent_difference(bulk_total, fec_reported),
        })
    return pd.DataFrame(records)


def top_super_pacs(conn, pulled_at, limit=10):
    """Committee IDs of the largest super PACs by House independent spending.

    Joined to `committees` so only registered super PAC types (O, V, W) count.
    An individual filer with a bogus multi-billion-dollar filing (see the
    README caveats) is in the bulk file but is not a super PAC.
    """
    rows = conn.execute(
        "SELECT o.committee_id FROM outside_spending o "
        "JOIN committees c ON c.committee_id = o.committee_id "
        "WHERE o.pulled_at = ? GROUP BY o.committee_id ORDER BY SUM(o.total) DESC LIMIT ?",
        (pulled_at, limit),
    )
    return [row[0] for row in rows]


def judge(table, network_ids, top_ids):
    """Apply the pass rule and return (passed, worst network diff, top-10 diff).

    Decision on zero-dollar committees: a committee that reports $0 and that we
    also have $0 for (for example a brand new network PAC) agrees trivially, so
    its NaN pct_diff is skipped rather than counted as a pass or a failure. A
    committee we have money for but the FEC reports $0 for is a real mismatch
    (infinite pct_diff) and fails.
    """
    networks = table[table["committee_id"].isin(network_ids)]
    worst_network = networks["pct_diff"].abs().max()  # max() skips NaN
    top = table[table["committee_id"].isin(top_ids)]
    top_diff = percent_difference(top["bulk_through_coverage"].sum(), top["fec_reported"].sum())
    passed = worst_network <= TOLERANCE_PCT and abs(top_diff) <= TOLERANCE_PCT
    return passed, worst_network, top_diff


def main():
    """Pull the committee totals, print the comparison, and print the verdict."""
    conn = connect(DB_PATH)
    pulled_at = conn.execute("SELECT MAX(pulled_at) FROM outside_spending").fetchone()[0]
    network_ids = [row[0] for row in conn.execute("SELECT committee_id FROM pac_industries")]
    top_ids = top_super_pacs(conn, pulled_at)
    committee_ids = list(dict.fromkeys(network_ids + [CLF_ID, HMP_ID] + top_ids))

    table = compare_to_committee_totals(conn, FecClient(load_api_key()), pulled_at, committee_ids)
    pd.set_option("display.width", 250, "display.max_columns", None, "display.float_format", "{:,.2f}".format)
    print(f"Snapshot {pulled_at}")
    print(table.to_string(index=False))

    passed, worst_network, top_diff = judge(table, network_ids, top_ids)
    print(f"\nWorst network pct_diff: {worst_network:.2f}%")
    print(f"Top 10 super PACs total pct_diff: {top_diff:.2f}%")
    print("VERDICT:", "PASS" if passed else "FALLBACK (a): network spending only")
    conn.close()


if __name__ == "__main__":
    main()
