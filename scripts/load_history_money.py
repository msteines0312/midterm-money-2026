"""Load 2022 and 2024 House money, as of each campaign's pre-general report.

Downloads each cycle's candidate-committee linkage file (saved to
data/raw/fec/), pulls the cycle's reports from the OpenFEC API, and replaces
that cycle's rows in the `history_money` table. 2026 tables are not touched.

Run from the repo root:
    python scripts/load_history_money.py [--cycles 2022 2024]
    python scripts/load_history_money.py --supplement [--cycles 2022 2024]

`--supplement` runs after `python -m src.pipeline --history`. It adds rows
for Democratic and Republican general election candidates in
`history_results` who have no `history_money` row because the linkage file
leaves them out, looking up their committees through the API. It only adds
rows for those candidates. A plain run replaces the whole cycle, so run
`--supplement` again after one.
"""

import argparse
import sys
from pathlib import Path

# Let this script import from src/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import DB_PATH, load_api_key  # noqa: E402
from src.db import connect, create_schema, upsert_rows  # noqa: E402
from src.fec.client import FecClient  # noqa: E402
from src.fec.history import (  # noqa: E402
    api_pre_general_cutoff,
    api_principal_committees,
    download_ccl,
    pre_general_money,
    supplemental_money,
)


def replace_cycle(conn, cycle, rows):
    """Delete one cycle's `history_money` rows and insert the new ones.

    Both steps run in one transaction, so a failed insert keeps the old rows.

    Parameters
    ----------
    conn : sqlite3.Connection
    cycle : int
    rows : list of dict

    Returns
    -------
    int
        Number of rows written.
    """
    with conn:
        conn.execute("DELETE FROM history_money WHERE cycle = ?", (cycle,))
        return upsert_rows(conn, "history_money", rows)


def missing_candidates(conn, cycle):
    """Major-party general candidates in `history_results` with no `history_money` row.

    Parameters
    ----------
    conn : sqlite3.Connection
    cycle : int

    Returns
    -------
    list of str
        Candidate IDs.
    """
    sql = """
        SELECT DISTINCT candidate_id FROM history_results
        WHERE cycle = ? AND party IN ('DEM', 'REP') AND candidate_id IS NOT NULL
          AND candidate_id NOT IN (SELECT candidate_id FROM history_money WHERE cycle = ?)
        ORDER BY candidate_id
    """
    return [row[0] for row in conn.execute(sql, (cycle, cycle))]


def supplement_cycle(client, conn, cycle):
    """Add `history_money` rows for one cycle's missing candidates.

    Returns
    -------
    int
        Rows written.
    """
    missing = missing_candidates(conn, cycle)
    committees = {cid: api_principal_committees(client, cid, cycle) for cid in missing}
    rows = supplemental_money(client, cycle, committees, api_pre_general_cutoff(client, cycle))
    print(f"{cycle}: {len(missing)} candidates without money, {len(rows)} found through the API")
    for row in rows:
        print(f"  {row['candidate_id']} {row['committee_id']} ${row['external_contributions']:,.0f}")
    return upsert_rows(conn, "history_money", rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cycles", type=int, nargs="+", default=[2022, 2024])
    parser.add_argument("--supplement", action="store_true",
                        help="only add rows for history_results candidates the linkage file misses")
    args = parser.parse_args()

    client = FecClient(load_api_key())
    conn = connect(DB_PATH)
    create_schema(conn)
    for cycle in args.cycles:
        if args.supplement:
            supplement_cycle(client, conn, cycle)
            continue
        calls_before = client.request_count
        rows = pre_general_money(client, cycle, download_ccl(cycle))
        written = replace_cycle(conn, cycle, rows)
        print(f"{cycle}: {written} rows written, {client.request_count - calls_before} API calls")
    conn.close()


if __name__ == "__main__":
    main()
