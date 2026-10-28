"""Build data/manual/endorsements.csv from the three endorsers' list pages.

Sources, one per endorser in data/manual/endorsers.csv:

- Donald Trump: Ballotpedia's tracker, saved from a browser to
  data/raw/ballotpedia_trump_2026-10-27.html (Ballotpedia blocks automated
  reads). Each endorsement is dated by its Truth Social post.
- Club for Growth PAC and Justice Democrats: their own list pages have no
  dates, so Wayback Machine copies from 2025 on are read (one a week, see
  `weekly`, or the copies saved by hand with --cached-only). Each candidate
  is dated by the start of the unbroken run of copies that lists them at
  their primary (see `listing_date`). The real endorsement came on or
  before that date, so the date is conservative.

Snapshots are cached in data/raw/wayback/ so a rerun does not download them
again. Rows that cannot be matched to an FEC candidate are printed for hand
review and are not written.

Run from the repo root:
    python scripts/build_endorsements.py
    python scripts/build_endorsements.py --only "Donald Trump"
    python scripts/build_endorsements.py --cached-only
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
from src.analysis.endorsements import load_primary_dates, primary_dates_for  # noqa: E402
from src.endorsements_match import (  # noqa: E402
    SIDE_PARTY,
    house_only,
    listing_date,
    match_candidates,
    parse_endorsement_list,
)
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
    a copy that already lists them, a missing copy can only push the date
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


def is_challenge_page(html):
    """Whether the archive sent its "One moment, please..." bot check instead of a page."""
    return "<title>One moment, please...</title>" in html


def fetch_snapshot(url, timestamp, slug):
    """Return one snapshot's HTML, downloading it only if it is not cached.

    The `id_` form of the Wayback URL returns the page as archived, without
    the Wayback toolbar. Asking for gzip keeps the archive from sending zstd,
    which requests cannot decode.
    """
    path = WAYBACK_DIR / slug / f"{timestamp}.html"
    if path.exists():
        html = path.read_text(encoding="utf-8", errors="ignore")
        # A page saved by hand could be the challenge page instead of the list
        if is_challenge_page(html):
            raise ValueError(f"{path} is the archive's 'One moment, please' page, not a snapshot. Save it again.")
        return html
    # The archive answers 429 when asked too quickly. Its block lasts a while,
    # so each retry waits longer (10, 20, 30, then 40 minutes) rather than
    # failing the whole build
    for attempt in range(5):
        try:
            response = requests.get(f"https://web.archive.org/web/{timestamp}id_/https://{url}",
                                    headers={"Accept-Encoding": "gzip"}, timeout=120)
            response.raise_for_status()
            # The archive sometimes answers 200 with a bot check instead of
            # the page. Treat it like a refusal so it is never cached.
            if is_challenge_page(response.text):
                raise requests.RequestException("challenge page instead of the snapshot")
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


def dated_listings(list_format, url, slug, primary_dates, cached_only=False):
    """Read every snapshot of a list and date each House candidate's endorsement.

    Parameters
    ----------
    list_format : str
        A key of the parsers in src.endorsements_match.
    url : str
        The list page, without the scheme.
    slug : str
        Folder under data/raw/wayback/ holding the cached snapshots.
    primary_dates : dict
        Output of `load_primary_dates`, so each candidate is dated against
        their own primary (see `listing_date`).
    cached_only : bool, optional
        Read only snapshots already on disk (saved by hand when the archive
        refuses scripted downloads) and download nothing.

    Returns
    -------
    tuple of (list of dict, int, int, int)
        One row per candidate still listed at their primary (or listed
        after it), the number of distinct non-House names dropped, the
        number of candidates removed from the list before their primary,
        and the snapshot count.
    """
    present, latest_row, non_house = {}, {}, set()
    cached = {path.stem for path in (WAYBACK_DIR / slug).glob("*.html")}
    timestamps = sorted(cached) if cached_only else weekly(list_snapshots(url), cached)
    for timestamp in timestamps:
        rows = parse_endorsement_list(fetch_snapshot(url, timestamp, slug), list_format)
        house, _ = house_only(rows)
        non_house |= {(row["name"], row["office"]) for row in rows if row["office"] != "house"}
        for row in house:
            key = (row["state"], row["district"], row["name"])
            present.setdefault(key, set()).add(timestamp)
            latest_row[key] = row

    copies = [timestamp[:8] for timestamp in timestamps]
    by_day = dict(zip(copies, timestamps))
    out, removed = [], 0
    for key, seen in present.items():
        dates = primary_dates_for(f"{key[0]}-{key[1]}", primary_dates)
        primary = dates["primary_date"].replace("-", "") if dates else None
        day, status = listing_date(copies, {timestamp[:8] for timestamp in seen}, primary)
        if status == "removed":
            removed += 1
            continue
        out.append({**latest_row[key], "date": f"{day[:4]}-{day[4:6]}-{day[6:8]}",
                    "source_url": snapshot_url(url, by_day[day])})
    return out, len(non_house), removed, len(timestamps)


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
    note = "Dated by the first copy in its unbroken run of listings"
    return f"{note} ({row['section']})" if row.get("section") else note


def parse_args():
    """Read the command line options."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", action="append", choices=list(SOURCES), metavar="ENDORSER",
                        help="Build only this endorser (repeatable). Used while the Wayback "
                             "Machine refuses downloads, so the saved Trump page can still be built.")
    parser.add_argument("--cached-only", action="store_true",
                        help="Read only the Wayback snapshots already in data/raw/wayback/ and "
                             "download nothing, for pages saved from a browser.")
    return parser.parse_args()


def main():
    args = parse_args()
    endorsers = {row["endorser"]: row for row in load_endorsers()}
    # The hand-checked nominee matches settle duplicate FEC registrations
    # and reversed names, which the endorsement lists run into too
    overrides = load_nominee_matches()
    primary_dates = load_primary_dates()
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
            rows, dropped, removed, n_snapshots = dated_listings(list_format, url, list_format, primary_dates,
                                                                 args.cached_only)
            summary = (f"{n_snapshots} snapshots, {dropped} non-House names dropped, "
                       f"{removed} removed from the list before their primary")
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
                "note": ". ".join(filter(None, [note_for(endorser, row), row.get("match_note", "")])),
            })
        all_review += [{**row, "endorser": endorser} for row in review]

    # A list can name one candidate under two districts over time (Club for
    # Growth moved Blake Miguez from LA-05 to LA-06 after the map changed).
    # Keep one row per endorser and candidate, with the earliest date.
    out.sort(key=lambda row: (row["endorser"], row["candidate_id"], row["endorsement_date"] or "9999"))
    out = [row for i, row in enumerate(out)
           if i == 0 or (row["endorser"], row["candidate_id"]) != (out[i - 1]["endorser"], out[i - 1]["candidate_id"])]
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
