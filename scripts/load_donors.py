"""Load contributions to super PACs, plus those PACs' committee totals.

Pulls FEC Schedule A rows into `donor_contributions` and each receiving
committee's cycle totals into `pac_totals`. Both are new tables. Rerunning on
the same day overwrites that day's rows, and no other table is touched.

Run from the repo root:
    python scripts/load_donors.py --large
    python scripts/load_donors.py --names names.txt
    python scripts/load_donors.py --committees committees.txt
    python scripts/load_donors.py --efile committees.txt --efile-since 2026-07-01

`--large` loads every 2026 contribution of $250,000 or more to a super PAC.
`--names` and `--committees` read a text file with one contributor name (as
the FEC files it, "LAST, FIRST") or one committee ID per line, and load
contributions of any size for each. Blank lines and lines starting with # are
skipped. The modes can be combined in one run.

`--efile` reads committee IDs the same way and loads their raw e-filed
contributions since `--efile-since`. The processed Schedule A lags new filings
(reports filed Oct 15 and Oct 22, 2026 had no itemized rows yet), so this fills
the gap. It replaces that committee's earlier e-file rows each run and skips
rows Schedule A already has, so rerunning after Schedule A catches up cannot
count a gift twice.
"""

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

# Let this script import from src/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import CYCLE, DB_PATH, load_api_key  # noqa: E402
from src.db import connect, create_schema, upsert_rows  # noqa: E402
from src.fec.client import FecClient  # noqa: E402
from src.fec.donors import (  # noqa: E402
    contribution_row,
    contributions_by_name,
    contributions_to_committee,
    drop_already_processed,
    drop_superseded_efile,
    efile_contribution_row,
    efile_contributions,
    large_contributions,
    pac_totals_rows,
)

LARGE_MINIMUM = 250_000


def read_list(path):
    """Read one value per line, skipping blank lines and # comments."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def collect_records(client, args):
    """Run the requested Schedule A queries and return all raw records."""
    records = []
    if args.large:
        records += large_contributions(client, CYCLE, LARGE_MINIMUM)
        print(f"--large: {len(records)} rows of ${LARGE_MINIMUM:,} or more")
    for name in read_list(args.names) if args.names else []:
        found = contributions_by_name(client, CYCLE, name)
        print(f"--names {name}: {len(found)} rows")
        records += found
    for committee_id in read_list(args.committees) if args.committees else []:
        found = contributions_to_committee(client, CYCLE, committee_id)
        print(f"--committees {committee_id}: {len(found)} rows")
        records += found
    return records


def load_efile(client, conn, committee_ids, since, pulled_at):
    """Load raw e-filed contributions that the processed Schedule A lacks.

    Parameters
    ----------
    client : FecClient
    conn : sqlite3.Connection
    committee_ids : list of str
    since : str
        YYYY-MM-DD. Earlier gifts are left to Schedule A.
    pulled_at : str

    Returns
    -------
    int
        Rows written.
    """
    # Start clean for these committees: an earlier run's raw rows may now have
    # processed twins, and a fresh fetch is cheap
    marks = ",".join("?" for _ in committee_ids)
    conn.execute(f"DELETE FROM donor_contributions WHERE sub_id LIKE 'efile-%' AND committee_id IN ({marks})", committee_ids)
    processed = Counter(conn.execute(
        "SELECT committee_id, receipt_date, amount, memo_code FROM donor_contributions "
        "WHERE sub_id NOT LIKE 'efile-%'"))
    rows = []
    for committee_id in committee_ids:
        raw = drop_superseded_efile(efile_contributions(client, committee_id, since))
        found = drop_already_processed([efile_contribution_row(rec, pulled_at) for rec in raw], processed)
        print(f"--efile {committee_id}: {len(raw)} raw rows, {len(found)} not in Schedule A")
        rows += found
    return upsert_rows(conn, "donor_contributions", rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--large", action="store_true", help="all $250K+ contributions for 2026")
    parser.add_argument("--names", help="text file of contributor names, one per line")
    parser.add_argument("--committees", help="text file of committee IDs, one per line")
    parser.add_argument("--efile", help="text file of committee IDs whose raw e-filings to load")
    parser.add_argument("--efile-since", default="2026-07-01", help="earliest gift date for --efile")
    args = parser.parse_args()
    if not (args.large or args.names or args.committees or args.efile):
        parser.error("choose at least one of --large, --names, --committees, --efile")

    pulled_at = date.today().isoformat()
    client = FecClient(load_api_key())
    conn = connect(DB_PATH)
    create_schema(conn)

    if args.efile:
        written = load_efile(client, conn, read_list(args.efile), args.efile_since, pulled_at)
        conn.commit()
        print(f"donor_contributions: {written} e-file rows written")
        # With only --efile there is nothing else to load
        if not (args.large or args.names or args.committees):
            conn.close()
            return

    records = collect_records(client, args)
    schedule_a_calls = client.request_count

    # A row is keyed by sub_id, so a contribution found by two modes is stored once
    contributions = {rec["sub_id"]: contribution_row(rec, pulled_at) for rec in records}
    written = upsert_rows(conn, "donor_contributions", list(contributions.values()))

    committee_ids = sorted({row["committee_id"] for row in contributions.values()})
    totals = pac_totals_rows(client, CYCLE, committee_ids, pulled_at)
    totals_written = upsert_rows(conn, "pac_totals", totals)
    conn.close()

    print(f"donor_contributions: {written} rows written ({len(records) - written} duplicates dropped)")
    print(f"pac_totals: {totals_written} rows written for {len(committee_ids)} committees")
    print(f"API calls: {schedule_a_calls} for Schedule A, {client.request_count - schedule_a_calls} for totals")


if __name__ == "__main__":
    main()
