"""Build or refresh the database from OpenFEC, FEC bulk data, Cook ratings, and hand-built CSVs.

Outside spending comes from the FEC bulk independent expenditure file, not the API.

Run from the repo root:
    python -m src.pipeline            full pull
    python -m src.pipeline --sample   one page per endpoint, to check things work
"""

import argparse
from datetime import date

from src.config import CYCLE, DB_PATH, SAMPLE_DB_PATH, load_api_key
from src.db import connect, create_schema, replace_rows, upsert_rows
from src.fec.bulk import download_summary, house_totals
from src.fec.client import FecClient
from src.fec.independent_expenditures import download_independent_expenditures, house_outside_spending
from src.fec.transform import candidate_row, committee_row
from src.manual import load_pac_industries
from src.ratings import load_races

# Endpoint path and query parameters for each FEC table
ENDPOINTS = {
    "candidates": ("/candidates/", {"office": "H", "election_year": CYCLE, "has_raised_funds": "true"}),
    # O = super PAC, V and W = hybrid PACs that also run super PAC accounts
    "committees": ("/committees/", {"cycle": CYCLE, "committee_type": ["O", "V", "W"]}),
}


def run_pull(client, conn, pulled_at, races, summary_text, ie_text, pac_industries=None, max_pages=None):
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
    summary_text : str
        Contents of the FEC bulk summary file (webl26.txt), the source of
        `candidate_totals`. Passed in for the same reason.
    ie_text : str
        Contents of the FEC bulk independent expenditure file, the source of
        `outside_spending`. Passed in for the same reason.
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
    totals = house_totals(summary_text, pulled_at)
    committees = fetch("committees", committee_row)

    spending = house_outside_spending(ie_text, candidates, pulled_at)

    if pac_industries is None:
        pac_industries = load_pac_industries()

    return {
        "races": upsert_rows(conn, "races", races),
        "candidates": upsert_rows(conn, "candidates", candidates),
        "committees": upsert_rows(conn, "committees", committees),
        "candidate_totals": upsert_rows(conn, "candidate_totals", totals),
        "outside_spending": upsert_rows(conn, "outside_spending", spending),
        # Replaced, not upserted, so a committee taken out of the CSV stops
        # counting instead of lingering in the table from an earlier pull
        "pac_industries": replace_rows(conn, "pac_industries", pac_industries),
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
        # Filings with no candidate ID that couldn't be matched by race and name
        # (e.g. CLF rows) have a NULL candidate_id. Counted directly, because
        # NULL NOT IN (...) is never true and would hide them.
        "spending_without_candidate":
            "SELECT COUNT(*) FROM outside_spending WHERE candidate_id IS NULL",
        # No race at all (a filing with no district) or a race missing from the
        # races table. NULL needs its own test for the same NOT IN reason.
        "spending_without_race":
            "SELECT COUNT(*) FROM outside_spending "
            "WHERE race_id IS NULL OR race_id NOT IN (SELECT race_id FROM races)",
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
        FecClient(load_api_key()), conn, date.today().isoformat(), load_races(), download_summary(),
        download_independent_expenditures(),
        max_pages=1 if args.sample else None,
    )
    print("Rows written:", counts)
    print("Unmatched rows:", orphan_counts(conn))
    conn.close()


if __name__ == "__main__":
    main()
