"""Load 2022 and 2024 House money, as of each campaign's pre-general report.

Downloads each cycle's candidate-committee linkage file (saved to
data/raw/fec/), pulls the cycle's reports from the OpenFEC API, and replaces
that cycle's rows in the `history_money` table. 2026 tables are not touched.

Run from the repo root:
    python scripts/load_history_money.py [--cycles 2022 2024]
"""

import argparse
import sys
from pathlib import Path

# Let this script import from src/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import DB_PATH, load_api_key  # noqa: E402
from src.db import connect, create_schema, upsert_rows  # noqa: E402
from src.fec.client import FecClient  # noqa: E402
from src.fec.history import download_ccl, pre_general_money  # noqa: E402


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


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cycles", type=int, nargs="+", default=[2022, 2024])
    args = parser.parse_args()

    client = FecClient(load_api_key())
    conn = connect(DB_PATH)
    create_schema(conn)
    for cycle in args.cycles:
        calls_before = client.request_count
        rows = pre_general_money(client, cycle, download_ccl(cycle))
        written = replace_cycle(conn, cycle, rows)
        print(f"{cycle}: {written} rows written, {client.request_count - calls_before} API calls")
    conn.close()


if __name__ == "__main__":
    main()
