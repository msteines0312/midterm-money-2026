"""Build or refresh the database from OpenFEC, Cook ratings, and hand-built CSVs.

Run from the repo root:
    python -m src.pipeline            full pull
    python -m src.pipeline --sample   one page per endpoint, to check things work
"""

import argparse
from datetime import date

from src.config import CYCLE, DB_PATH, SAMPLE_DB_PATH, load_api_key
from src.db import connect, create_schema, upsert_rows
from src.fec.client import FecClient
from src.fec.transform import candidate_row, committee_row, outside_spending_row, totals_row
from src.manual import load_pac_industries
from src.ratings import load_races

# Endpoint path and query parameters for each FEC table
ENDPOINTS = {
    "candidates": ("/candidates/", {"office": "H", "election_year": CYCLE, "has_raised_funds": "true"}),
    "totals": ("/candidates/totals/", {"office": "H", "election_year": CYCLE, "cycle": CYCLE}),
    # O = super PAC, V and W = hybrid PACs that also run super PAC accounts
    "committees": ("/committees/", {"cycle": CYCLE, "committee_type": ["O", "V", "W"]}),
}

# The outside spending endpoint won't take office="house" without also naming
# a state and district, which would mean 435+ separate queries. It does accept
# a list of candidate IDs, so it's queried in batches of House candidates instead.
OUTSIDE_SPENDING_PATH = "/schedules/schedule_e/by_candidate/"
CANDIDATE_BATCH_SIZE = 100


def _batches(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def run_pull(client, conn, pulled_at, races, pac_industries=None, max_pages=None):
    """Pull every table and write it to the database.

    Parameters
    ----------
    client : FecClient
        Anything with an `iter_results(path, params, max_pages)` method.
    conn : sqlite3.Connection
    pulled_at : str
        ISO date stamped on the money snapshots.
    races : list of dict
        Rows for the `races` table, from `ratings.load_races()`. Passed in so
        this function can be tested without downloading Wikipedia pages.
    pac_industries : list of dict, optional
        Industry labels. Defaults to reading data/manual/pac_industries.csv.
    max_pages : int, optional
        Page limit per request, for a quick sample pull.

    Returns
    -------
    dict
        Rows written per table.
    """
    create_schema(conn)

    def fetch(name, transform):
        path, params = ENDPOINTS[name]
        return [transform(rec) for rec in client.iter_results(path, params, max_pages=max_pages)]

    candidates = fetch("candidates", candidate_row)
    totals = fetch("totals", lambda rec: totals_row(rec, pulled_at))
    committees = fetch("committees", committee_row)

    # /candidates/ only returns candidates flagged has_raised_funds, while
    # /candidates/totals/ returns more (about 3,800 vs 2,500). Querying spending
    # for both sets means outside money aimed at the extra candidates isn't lost.
    candidate_ids = sorted({c["candidate_id"] for c in candidates} | {t["candidate_id"] for t in totals})
    spending = []
    for batch in _batches(candidate_ids, CANDIDATE_BATCH_SIZE):
        params = {"cycle": CYCLE, "candidate_id": batch}
        spending += [outside_spending_row(rec, pulled_at)
                     for rec in client.iter_results(OUTSIDE_SPENDING_PATH, params, max_pages=max_pages)]
        if max_pages:
            break  # a sample pull only needs the first batch

    if pac_industries is None:
        pac_industries = load_pac_industries()

    return {
        "races": upsert_rows(conn, "races", races),
        "candidates": upsert_rows(conn, "candidates", candidates),
        "committees": upsert_rows(conn, "committees", committees),
        "candidate_totals": upsert_rows(conn, "candidate_totals", totals),
        "outside_spending": upsert_rows(conn, "outside_spending", spending),
        "pac_industries": upsert_rows(conn, "pac_industries", pac_industries),
    }


def orphan_counts(conn):
    """Count rows that don't match across tables.

    The schema has no foreign keys because FEC endpoints filter candidates
    differently, so some mismatches are expected. This makes them visible.

    Parameters
    ----------
    conn : sqlite3.Connection

    Returns
    -------
    dict
        Number of unmatched rows for each check.
    """
    checks = {
        "totals_without_candidate":
            "SELECT COUNT(*) FROM candidate_totals WHERE candidate_id NOT IN (SELECT candidate_id FROM candidates)",
        "spending_without_candidate":
            "SELECT COUNT(*) FROM outside_spending WHERE candidate_id NOT IN (SELECT candidate_id FROM candidates)",
        # DC and territory delegates land here by design: they have no Cook rating
        "candidates_without_race":
            "SELECT COUNT(*) FROM candidates WHERE race_id NOT IN (SELECT race_id FROM races)",
    }
    return {name: conn.execute(sql).fetchone()[0] for name, sql in checks.items()}


def database_for(sample):
    """Pick the database file for a pull.

    Sample pulls get their own file. Otherwise a 100-candidate sample would sit
    in the real database looking like a full snapshot for that date.

    Parameters
    ----------
    sample : bool
        True for a `--sample` run.

    Returns
    -------
    pathlib.Path
    """
    return SAMPLE_DB_PATH if sample else DB_PATH


def main(argv=None):
    """Run the pipeline from the command line.

    Parameters
    ----------
    argv : list of str, optional
        Arguments to parse. Defaults to the real command line.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", action="store_true", help="pull one page per endpoint")
    args = parser.parse_args(argv)

    conn = connect(database_for(args.sample))
    counts = run_pull(
        FecClient(load_api_key()), conn, date.today().isoformat(), load_races(),
        max_pages=1 if args.sample else None,
    )
    print("Rows written:", counts)
    print("Unmatched rows:", orphan_counts(conn))
    conn.close()


if __name__ == "__main__":
    main()
