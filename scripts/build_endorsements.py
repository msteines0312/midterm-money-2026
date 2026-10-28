"""Build data/manual/endorsements.csv from the three endorsers' list pages.

Sources, one per endorser in data/manual/endorsers.csv:

- Donald Trump: Ballotpedia's tracker, saved from a browser to
  data/raw/ballotpedia_trump_2026-10-27.html (Ballotpedia blocks automated
  reads). Each endorsement is dated by its Truth Social post.
- Club for Growth PAC and Justice Democrats: their own list pages have no
  dates, so Wayback Machine copies from 2025 on are read (one a week, see
  `weekly`), and each candidate is dated by the first copy that shows them.
  The real endorsement came on or before that date, so the date is
  conservative.

Snapshots are cached in data/raw/wayback/ so a rerun does not download them
again. Rows that cannot be matched to an FEC candidate are printed for hand
review and are not written.

Run from the repo root:
    python scripts/build_endorsements.py
    python scripts/build_endorsements.py --only "Donald Trump"
"""

import argparse
import csv
import datetime as dt
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import DB_PATH, ENDORSEMENTS_CSV, RAW_DIR  # noqa: E402
from src.endorsements_match import SIDE_PARTY, house_only, match_candidates, parse_endorsement_list  # noqa: E402
from src.manual import load_endorsers, load_nominee_matches  # noqa: E402

TRUMP_PAGE = RAW_DIR / "ballotpedia_trump_2026-10-27.html"
WAYBACK_DIR = RAW_DIR / "wayback"
CDX_URL = "https://web.archive.org/cdx/search/cdx"

# Endorser name to (list page parser, Wayback URL or None for the saved page)
SOURCES = {
    "Donald Trump": ("ballotpedia_trump", None),
    "Club for Growth PAC": ("club_for_growth", "www.clubforgrowth.org/elections/pac-endorsed-candidates/"),
    "Justice Democrats": ("justice_democrats", "justicedemocrats.com/candidates"),
}

# Snapshots before mid-2025 may still show the 2024 slate. A candidate first
# seen before this date is flagged so the date can be checked by hand.
SLATE_CHECK_BEFORE = "2025-07-01"

COLUMNS = ["endorser", "candidate_id", "race_id", "candidate_name", "endorsement_date", "date_basis", "source_url",
           "source_outcome", "note"]


def list_snapshots(url, start="20250101", end="20261027"):
    """List one Wayback snapshot per day for a URL.

    Returns
    -------
    list of str
        Snapshot timestamps (YYYYMMDDhhmmss), oldest first.
    """
    params = {"url": url, "from": start, "to": end, "output": "json", "fl": "timestamp",
              "filter": "statuscode:200", "collapse": "timestamp:8"}
    response = requests.get(CDX_URL, params=params, timeout=120)
    response.raise_for_status()
    return [row[0] for row in response.json()[1:]]


def weekly(timestamps, cached=()):
    """Keep the first snapshot of each week, plus any already downloaded.

    The archive starts refusing requests (HTTP 429) after a few dozen
    downloads, so reading every daily copy is not practical. One copy a week
    still dates each candidate to within seven days, and since the date is
    the first copy that lists them, a later copy can only push the date
    later, which makes the before-the-primary test stricter, never looser.
    Copies already on disk cost nothing, so they are kept for a closer date.

    Parameters
    ----------
    timestamps : list of str
        Snapshot timestamps (YYYYMMDDhhmmss), oldest first.
    cached : collection of str
        Timestamps already saved in the cache.

    Returns
    -------
    list of str
        The kept timestamps, oldest first.
    """
    kept, weeks = [], set()
    for timestamp in timestamps:
        week = dt.date(int(timestamp[:4]), int(timestamp[4:6]), int(timestamp[6:8])).isocalendar()[:2]
        if timestamp in cached or week not in weeks:
            kept.append(timestamp)
            weeks.add(week)
    return kept


def fetch_snapshot(url, timestamp, slug):
    """Return one snapshot's HTML, downloading it only if it is not cached.

    The `id_` form of the Wayback URL returns the page as archived, without
    the Wayback toolbar. Asking for gzip keeps the archive from sending zstd,
    which requests cannot decode.
    """
    path = WAYBACK_DIR / slug / f"{timestamp}.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    # The archive answers 429 when asked too quickly. Its block lasts a while,
    # so each retry waits longer (10, 20, 30, then 40 minutes) rather than
    # failing the whole build
    for attempt in range(5):
        try:
            response = requests.get(f"https://web.archive.org/web/{timestamp}id_/https://{url}",
                                    headers={"Accept-Encoding": "gzip"}, timeout=120)
            response.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 4:
                raise
            time.sleep(600 * (attempt + 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.text, encoding="utf-8")
    time.sleep(30)  # stay under the archive's rate limit
    return response.text


def snapshot_url(url, timestamp):
    """The public Wayback link for a snapshot, used as the row's source."""
    return f"https://web.archive.org/web/{timestamp}/https://{url}"


def first_listings(list_format, url, slug):
    """Read every snapshot of a list and keep each House candidate's first appearance.

    Returns
    -------
    tuple of (list of dict, int, int)
        One row per candidate dated by the first snapshot that lists them,
        the number of distinct non-House names dropped, and the snapshot count.
    """
    first_seen, non_house = {}, set()
    cached = {path.stem for path in (WAYBACK_DIR / slug).glob("*.html")}
    timestamps = weekly(list_snapshots(url), cached)
    for timestamp in timestamps:
        rows = parse_endorsement_list(fetch_snapshot(url, timestamp, slug), list_format)
        house, _ = house_only(rows)
        non_house |= {(row["name"], row["office"]) for row in rows if row["office"] != "house"}
        for row in house:
            key = (row["state"], row["district"], row["name"])
            if key not in first_seen:
                day = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
                first_seen[key] = {**row, "date": day, "source_url": snapshot_url(url, timestamp)}
    return list(first_seen.values()), len(non_house), len(timestamps)


def trump_rows():
    """Read the saved Ballotpedia page and keep primary endorsements.

    Ballotpedia marks each endorsement as Primary, Primary Runoff, General,
    or "Primary, General". Rows marked General only were made for the
    general election and are not primary endorsements, so they are dropped.
    Special elections are dropped too, because their primaries run on
    their own calendar and are not the 2026 regular primaries studied here.

    Returns
    -------
    tuple of (list of dict, str)
        The primary endorsement rows and a summary of what was dropped.
    """
    rows = parse_endorsement_list(TRUMP_PAGE.read_text(encoding="utf-8", errors="ignore"), "ballotpedia_trump")
    general_only = [row for row in rows if "Primary" not in row["endorsement_type"]]
    special = [row for row in rows if row["special"] and row not in general_only]
    kept = [row for row in rows if row not in general_only and row not in special]
    return kept, f"{len(general_only)} general-only and {len(special)} special election rows dropped"


def note_for(endorser, row):
    """A short note recording what the source said about the row."""
    if endorser == "Donald Trump":
        note = f"Ballotpedia: {row['endorsement_type']}, {row['status']}"
        return note if row["date"] else note + ", no Truth Social post to date it"
    note = f"First listed in this snapshot ({row['section']})" if row.get("section") else "First listed in this snapshot"
    if row["date"] < SLATE_CHECK_BEFORE:
        note += ". Seen before mid-2025, check it is the 2026 slate"
    return note


def parse_args():
    """Read the command line options."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", action="append", choices=list(SOURCES), metavar="ENDORSER",
                        help="Build only this endorser (repeatable). Used while the Wayback "
                             "Machine refuses downloads, so the saved Trump page can still be built.")
    return parser.parse_args()


def main():
    args = parse_args()
    endorsers = {row["endorser"]: row for row in load_endorsers()}
    # The hand-checked nominee matches settle duplicate FEC registrations
    # and reversed names, which the endorsement lists run into too
    overrides = load_nominee_matches()
    with sqlite3.connect(DB_PATH) as conn:
        candidates = pd.read_sql("SELECT * FROM candidates", conn)

    out, all_review = [], []
    for endorser, (list_format, url) in SOURCES.items():
        if args.only and endorser not in args.only:
            print(f"{endorser}: skipped")
            continue
        if url is None:
            rows, summary = trump_rows()
        else:
            rows, dropped, n_snapshots = first_listings(list_format, url, list_format)
            summary = f"{n_snapshots} snapshots, {dropped} non-House names dropped"
        party = SIDE_PARTY[endorsers[endorser]["side"]]
        matched, review = match_candidates(rows, candidates, party, overrides=overrides)
        print(f"{endorser}: {len(rows)} House rows, {len(matched)} matched, {len(review)} in review ({summary})")

        for row in matched:
            out.append({
                "endorser": endorser,
                "candidate_id": row["candidate_id"],
                "race_id": row["race_id"],
                "candidate_name": row["name"],
                "endorsement_date": row["date"],
                "date_basis": ("announced" if url is None else "listed_by") if row["date"] else "",
                "source_url": row["source_url"] or endorsers[endorser]["list_url"],
                # Ballotpedia records each primary's result, including candidates
                # who were never on the ballot. The organizations' own lists do not.
                "source_outcome": row.get("outcome", ""),
                "note": note_for(endorser, row),
            })
        all_review += [{**row, "endorser": endorser} for row in review]

    out.sort(key=lambda row: (row["endorser"], row["race_id"], row["candidate_name"]))
    with open(ENDORSEMENTS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(out)
    print(f"Wrote {len(out)} rows to {ENDORSEMENTS_CSV}")

    print("\nReview list (not written):")
    for row in all_review:
        print(f"  {row['endorser']}: {row['name']} {row['race_id']}, {row['review_reason']}")


if __name__ == "__main__":
    main()
