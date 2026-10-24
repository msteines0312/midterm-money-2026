"""Load hand-built CSVs from data/manual/.

These files hold judgment calls the FEC doesn't make for us, like which
super PACs belong to a crypto or AI network. Every row must cite a source so
a reader can check the call.
"""

import csv

from src.config import NOMINEE_MATCHES_CSV, PAC_INDUSTRIES_CSV

# The only industry labels the analysis knows how to group. A typo like
# "AI" or "ai-safety" would quietly split a network in two, so reject it.
INDUSTRIES = {"crypto", "ai_industry", "ai_safety"}


def load_pac_industries(path=PAC_INDUSTRIES_CSV):
    """Read and validate the PAC network labels.

    Parameters
    ----------
    path : pathlib.Path, optional
        CSV with columns committee_id, network, industry, source_url.

    Returns
    -------
    list of dict
        One dict per labeled committee, with whitespace stripped.

    Raises
    ------
    ValueError
        If a row has no network, an unknown industry, or no source, or if a
        committee is labeled twice.
    """
    with open(path, newline="", encoding="utf-8") as f:
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(f)]

    seen = set()
    for row in rows:
        _check_row(row)
        if row["committee_id"] in seen:
            raise ValueError(f"{row['committee_id']} is a duplicate")
        seen.add(row["committee_id"])
    return rows


def _check_row(row):
    """Raise if one label row is missing a required value.

    Parameters
    ----------
    row : dict
        One stripped CSV row.

    Raises
    ------
    ValueError
        If the network is blank, the industry is not in INDUSTRIES, or the
        source_url is blank.
    """
    committee_id = row["committee_id"]
    if not row["network"]:
        raise ValueError(f"{committee_id} has no network")
    if row["industry"] not in INDUSTRIES:
        raise ValueError(f"{committee_id} has unknown industry {row['industry']!r}")
    if not row["source_url"]:
        raise ValueError(f"{committee_id} has no source_url")


def load_nominee_matches(path=NOMINEE_MATCHES_CSV):
    """Read the hand-checked matches from nominees to FEC candidate IDs.

    These override the automatic last-name match, so every row must say
    how the match was checked.

    Parameters
    ----------
    path : pathlib.Path, optional
        CSV with columns race_id, name, candidate_id, note.

    Returns
    -------
    list of dict
        One dict per hand-checked nominee, with whitespace stripped.

    Raises
    ------
    ValueError
        If a row has no race_id, name, candidate_id, or note.
    """
    with open(path, newline="", encoding="utf-8") as f:
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(f)]

    for row in rows:
        for column in ("race_id", "name", "candidate_id", "note"):
            if not row[column]:
                raise ValueError(f"{row['race_id'] or '?'} {row['name'] or '?'} has no {column}")
    return rows
