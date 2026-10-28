"""Endorsements: who was endorsed, in what kind of primary, and who won.

The question is how often endorsed candidates won their 2026 House
primaries, split by incumbents, open seats, and contested primaries. Raw win
rates flatter endorsers, because they tend to back favorites, so every rate
here is reported next to a baseline for all candidates in the same kind of
race.

This module holds the primary context: primary dates, each candidate's
status, and whether their party's primary was a real contest.
"""

import pandas as pd

from src.config import PRIMARY_DATES_CSV
from src.manual import _read_stripped, _split_list
from src.predict.simple import _fec_last_name_words

STATUS = {"I": "incumbent", "O": "open_seat", "C": "challenger"}


# Primary dates

def load_primary_dates(path=PRIMARY_DATES_CSV):
    """Read the 2026 House primary and runoff dates.

    Most states have one date. A state that split its House primaries (like
    Alabama after redistricting) has one row per group of districts, listed
    in `districts` as `;`-separated two-digit numbers.

    Parameters
    ----------
    path : pathlib.Path, optional
        CSV with columns state, districts, primary_date, runoff_date,
        source_url, note.

    Returns
    -------
    dict
        Keyed by race_id ("AL-01") for district rows and by state ("TX")
        otherwise. Each value has primary_date and runoff_date ("" if none).

    Raises
    ------
    ValueError
        If a row has no source_url or no primary_date.
    """
    dates = {}
    for row in _read_stripped(path):
        for column in ("source_url", "primary_date"):
            if not row[column]:
                raise ValueError(f"{row['state']} {row['districts']} has no {column}".strip())
        value = {"primary_date": row["primary_date"], "runoff_date": row["runoff_date"]}
        districts = _split_list(row["districts"])
        for key in [f"{row['state']}-{district}" for district in districts] or [row["state"]]:
            dates[key] = value
    return dates


def primary_dates_for(race_id, dates):
    """Look up a race's dates, preferring a district row over its state.

    Returns
    -------
    dict or None
        primary_date and runoff_date, or None if the state is not listed.
    """
    return dates.get(race_id) or dates.get(race_id[:2])


# Primary context for each candidate

def _latest_money(conn):
    """External contributions per candidate on the latest pull, negatives floored at 0."""
    frame = pd.read_sql_query(
        "SELECT candidate_id, external_contributions FROM candidate_totals "
        "WHERE pulled_at = (SELECT MAX(pulled_at) FROM candidate_totals)",
        conn,
    )
    return dict(zip(frame["candidate_id"], frame["external_contributions"].fillna(0).clip(lower=0)))


def _person_key(row):
    """Who a candidates row stands for, so one person filed twice counts once.

    The FEC sometimes holds two IDs for one person (MO-03's Bob Onder). Both
    carry the same money, so last name plus money identifies the person.
    Two different people almost never raise the same amount to the cent.
    """
    return (tuple(_fec_last_name_words(row["name"])), round(row["external"], 2))


def classify_primary(conn, candidate_ids=None, min_external=10_000):
    """Describe each candidate's 2026 primary.

    Parameters
    ----------
    conn : sqlite3.Connection
    candidate_ids : iterable of str, optional
        Candidates to return. Everyone in their race still counts toward
        whether it was contested. Defaults to every candidate.
    min_external : float, optional
        External contributions a candidate needs to count as a real
        contender. Full primary ballots are not in the database, so a
        primary counts as contested when at least two people of the same
        party in the race reach this amount. A hand check of 15 random races
        against Wikipedia's primary results (2026-10-27) agreed on 9 of the
        11 that could be judged. Both misses had a second name on the ballot
        who raised under $10,000 (21% and 8% of the vote), so this measures a
        funded contest, which is stricter than a contested ballot. The other
        four were top-two races with no party primary, or had no results table.

    Returns
    -------
    pandas.DataFrame
        One row per candidate with candidate_id, race_id, party, status
        (incumbent, open_seat, or challenger), external, contested, and
        top_fundraiser (raised the most of their party in the race).
    """
    candidates = pd.read_sql_query(
        "SELECT candidate_id, name, party, race_id, incumbent_challenge FROM candidates", conn
    )
    money = _latest_money(conn)
    candidates["external"] = candidates["candidate_id"].map(money).fillna(0.0)
    candidates["status"] = candidates["incumbent_challenge"].map(STATUS)

    contested, top = {}, {}
    for (race_id, party), group in candidates.groupby(["race_id", "party"]):
        funded = group[group["external"] >= min_external]
        is_contested = len({_person_key(row) for _, row in funded.iterrows()}) >= 2
        best = group["external"].max()
        for _, row in group.iterrows():
            contested[row["candidate_id"]] = is_contested
            top[row["candidate_id"]] = bool(best > 0 and row["external"] == best)

    candidates["contested"] = candidates["candidate_id"].map(contested)
    candidates["top_fundraiser"] = candidates["candidate_id"].map(top)
    if candidate_ids is not None:
        candidates = candidates[candidates["candidate_id"].isin(set(candidate_ids))]
    columns = ["candidate_id", "race_id", "party", "status", "external", "contested", "top_fundraiser"]
    return candidates[columns].reset_index(drop=True)
