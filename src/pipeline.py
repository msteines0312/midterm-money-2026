"""Build or refresh the database from OpenFEC, FEC bulk data, Cook ratings, and hand-built CSVs.

Outside spending comes from the FEC bulk independent expenditure file, not the API.

Run from the repo root:
    python -m src.pipeline            full pull
    python -m src.pipeline --sample   one page per endpoint, to check things work
    python -m src.pipeline --rebuild-outside-spending 2026-10-23
                                      rebuild one date's outside spending from
                                      the saved bulk file, with no downloads
    python -m src.pipeline --history  load 2022 and 2024 results, PVI, and
                                      ratings for the model (history_money is
                                      loaded by scripts/load_history_money.py)
"""

import argparse
from datetime import date

from src.config import CYCLE, DB_PATH, HISTORY_CYCLES, SAMPLE_DB_PATH, load_api_key
from src.db import connect, create_schema, replace_rows, upsert_rows
from src.fec.bulk import download_summary, house_totals
from src.fec.client import FecClient
from src.fec.independent_expenditures import (
    download_independent_expenditures,
    house_outside_spending,
    read_saved_independent_expenditures,
)
from src.fec.transform import candidate_row, committee_row
from src.history_results import dem_vs_rep_races, load_history_races, load_history_results
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

    if pac_industries is None:
        pac_industries = load_pac_industries()

    return {
        "races": upsert_rows(conn, "races", races),
        "candidates": upsert_rows(conn, "candidates", candidates),
        "committees": upsert_rows(conn, "committees", committees),
        "candidate_totals": upsert_rows(conn, "candidate_totals", totals),
        "outside_spending": write_outside_spending(conn, ie_text, candidates, pulled_at),
        # Replaced, not upserted, so a committee taken out of the CSV stops
        # counting instead of lingering in the table from an earlier pull
        "pac_industries": replace_rows(conn, "pac_industries", pac_industries),
    }


def write_outside_spending(conn, ie_text, candidates, pulled_at):
    """Build one date's `outside_spending` rows and replace that date's old ones.

    The old rows are deleted first rather than upserted over. A row's
    `candidate_key` can change between builds (a filing matched to a
    candidate ID this time was keyed by race and name last time), and an
    upsert would keep the old row next to the new one and count it twice.
    Other dates are not touched.

    Parameters
    ----------
    conn : sqlite3.Connection
    ie_text : str
        Contents of the FEC bulk independent expenditure file.
    candidates : list of dict
        Rows of the `candidates` table.
    pulled_at : str
        ISO date of the snapshot.

    Returns
    -------
    int
        Rows written.
    """
    spending = house_outside_spending(ie_text, candidates, pulled_at)
    return replace_rows(conn, "outside_spending", spending, pulled_at=pulled_at)


def rebuild_outside_spending(conn, ie_text, pulled_at):
    """Rebuild one date's `outside_spending` from a saved file and the current `candidates`.

    For when the matching code changes after a pull. Nothing is downloaded
    and no other table is written, so newer FEC data never gets the old date.

    Parameters
    ----------
    conn : sqlite3.Connection
    ie_text : str
        The bulk file saved by that date's pull.
    pulled_at : str
        ISO date of the snapshot to rebuild.

    Returns
    -------
    int
        Rows written.
    """
    cursor = conn.execute("SELECT * FROM candidates")
    columns = [col[0] for col in cursor.description]
    candidates = [dict(zip(columns, row)) for row in cursor]
    return write_outside_spending(conn, ie_text, candidates, pulled_at)


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


def write_history(conn, cycle, results, races):
    """Replace one cycle's `history_results` and `history_races` rows.

    Other cycles and every 2026 table are left alone. Deleting first means a
    candidate dropped by a parser fix doesn't linger from an earlier load.

    Parameters
    ----------
    conn : sqlite3.Connection
    cycle : int
    results : list of dict
        `history_results` rows for that cycle.
    races : list of dict
        `history_races` rows for that cycle.

    Returns
    -------
    dict
        Rows written per table.
    """
    create_schema(conn)
    written = {}
    for table, rows in (("history_results", results), ("history_races", races)):
        # `with conn` rolls back the DELETE if the insert fails, as in replace_rows
        with conn:
            conn.execute(f"DELETE FROM {table} WHERE cycle = ?", (cycle,))
            written[table] = upsert_rows(conn, table, rows)
    return written


def _rows(conn, sql, params):
    """Run a query and return each row as a dict."""
    cursor = conn.execute(sql, params)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor]


def history_summary(conn, cycle):
    """Count one cycle's history rows and how many D versus R candidates have money.

    A candidate counts as matched when their FEC ID has a `history_money` row
    for the same cycle. Some committees are principal for two candidate IDs,
    so `history_money` can hold the same money under both. Matching is by the
    results sheet's own ID, so nothing is added across them.

    Parameters
    ----------
    conn : sqlite3.Connection
    cycle : int

    Returns
    -------
    dict
        Counts, plus `unmatched` as (race_id, name, candidate_id) tuples.
    """
    results = _rows(conn, "SELECT * FROM history_results WHERE cycle = ?", (cycle,))
    money_ids = {row[0] for row in conn.execute("SELECT candidate_id FROM history_money WHERE cycle = ?", (cycle,))}
    dvr = dem_vs_rep_races(results)
    candidates = [r for r in results if r["race_id"] in dvr and r["party"] in ("DEM", "REP")]
    unmatched = [r for r in candidates if r["candidate_id"] not in money_ids]
    return {
        "races": conn.execute("SELECT COUNT(*) FROM history_races WHERE cycle = ?", (cycle,)).fetchone()[0],
        "result_races": len({r["race_id"] for r in results}),
        "dem_vs_rep_races": len(dvr),
        "winners": sum(r["won"] for r in results),
        "dem_vs_rep_candidates": len(candidates),
        "matched_to_money": len(candidates) - len(unmatched),
        "unmatched": sorted((r["race_id"], r["name"], r["candidate_id"]) for r in unmatched),
    }


def load_history(conn, cycles=HISTORY_CYCLES):
    """Fill the history tables for each cycle and print what was loaded.

    Parameters
    ----------
    conn : sqlite3.Connection
    cycles : iterable of int, optional
    """
    for cycle in cycles:
        written = write_history(conn, cycle, load_history_results(cycle), load_history_races(cycle))
        summary = history_summary(conn, cycle)
        unmatched = summary.pop("unmatched")
        if summary["matched_to_money"] == 0:
            print(f"{cycle}: history_money is empty for this cycle. Run scripts/load_history_money.py first.")
        print(f"{cycle}: rows written {written}")
        print(f"{cycle}: {summary}")
        for race_id, name, candidate_id in unmatched:
            print(f"  no pre-general money: {race_id} {name} ({candidate_id})")


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
    parser.add_argument("--rebuild-outside-spending", metavar="YYYY-MM-DD",
                        help="rebuild that date's outside spending from the saved bulk file instead of pulling")
    parser.add_argument("--history", action="store_true",
                        help="load 2022 and 2024 House results, PVI, and ratings for the model")
    args = parser.parse_args(argv)

    conn = connect(database_for(args.sample))
    if args.history:
        load_history(conn)
        conn.close()
        return

    if args.rebuild_outside_spending:
        pulled_at = args.rebuild_outside_spending
        written = rebuild_outside_spending(conn, read_saved_independent_expenditures(pulled_at), pulled_at)
        print(f"Rebuilt outside_spending for {pulled_at}: {written} rows")
        print("Unmatched rows:", orphan_counts(conn))
        conn.close()
        return

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
