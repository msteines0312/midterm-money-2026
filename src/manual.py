"""Load hand-built CSVs from data/manual/.

These files hold judgment calls the FEC doesn't make for us, like which
super PACs belong to a crypto or AI network. Every row must cite a source so
a reader can check the call.
"""

import csv
from datetime import date

from src.config import (
    BILLIONAIRES_CSV,
    DONOR_ENTITIES_CSV,
    ENDORSEMENTS_CSV,
    ENDORSERS_CSV,
    NOMINEE_MATCHES_CSV,
    ORG_DONORS_REVIEWED_CSV,
    PAC_INDUSTRIES_CSV,
)

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


# How a person-to-entity link was sourced. Anything else (a guess, a rumor,
# "everyone knows") is not allowed in the file.
EVIDENCE_TYPES = {"fec_filing", "own_statement", "news"}

# Outcomes for every organization donor of $1M or more. Only "attributed"
# rows count toward a billionaire's total.
ORG_CATEGORIES = {
    "attributed",
    "union",
    "trade_group",
    "party_aligned_nonprofit",
    "corporation",
    "other_nonprofit",
    "unknown",
}


def _read_stripped(path):
    """Read a CSV into dicts with whitespace stripped from every value."""
    with open(path, newline="", encoding="utf-8") as f:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(f)]


def _split_list(value):
    """Split a `;`-separated field into a list of stripped, non-empty parts."""
    return [part.strip() for part in value.split(";") if part.strip()]


def load_billionaires(path=BILLIONAIRES_CSV):
    """Read the billionaire households and the FEC spellings of their names.

    Parameters
    ----------
    path : pathlib.Path, optional
        CSV with columns person, household_members, contributor_name_variants,
        forbes_url, note. The two list columns use `;` between items.

    Returns
    -------
    list of dict
        One dict per household. `household_members` and
        `contributor_name_variants` are lists of strings. A blank household
        means the person alone. The variants list can be empty for someone
        who gives only through an entity in donor_entities.csv.

    Raises
    ------
    ValueError
        If a row has no person or no forbes_url.
    """
    rows = _read_stripped(path)
    for row in rows:
        if not row["person"]:
            raise ValueError("a billionaire row has no person")
        if not row["forbes_url"]:
            raise ValueError(f"{row['person']} has no forbes_url")
        row["household_members"] = _split_list(row["household_members"]) or [row["person"]]
        row["contributor_name_variants"] = _split_list(row["contributor_name_variants"])
    return rows


def load_donor_entities(path=DONOR_ENTITIES_CSV):
    """Read the sourced links from organizations to billionaires.

    Parameters
    ----------
    path : pathlib.Path, optional
        CSV with columns entity_name, person, source_url, evidence_type,
        share, note. `share` is the fraction of the entity's giving that
        belongs to the person. It is optional and defaults to 1. It exists
        because some firms' filings split every gift between partners (a16z
        reports each one as half Andreessen, half Horowitz).

    Returns
    -------
    list of dict
        One dict per link, with whitespace stripped and `share` as a float.

    Raises
    ------
    ValueError
        If a row has no entity_name, person, or source_url, its
        evidence_type is not in EVIDENCE_TYPES, its share is not in (0, 1],
        or the shares for one entity add up to more than 1.
    """
    rows = _read_stripped(path)
    share_by_entity = {}
    for row in rows:
        entity = row["entity_name"] or "?"
        for column in ("entity_name", "person", "source_url"):
            if not row[column]:
                raise ValueError(f"{entity} has no {column}")
        if row["evidence_type"] not in EVIDENCE_TYPES:
            raise ValueError(f"{entity} has unknown evidence_type {row['evidence_type']!r}")
        row["share"] = float(row.get("share") or 1)
        if not 0 < row["share"] <= 1:
            raise ValueError(f"{entity} has share {row['share']}, which is not between 0 and 1")
        share_by_entity[entity] = share_by_entity.get(entity, 0) + row["share"]

    # Two people can split one entity, but never more than all of it.
    # The small tolerance absorbs float rounding in splits like 1/3 + 2/3.
    for entity, total_share in share_by_entity.items():
        if total_share > 1 + 1e-9:
            raise ValueError(f"{entity} is attributed {total_share:g} times over")
    return rows


def load_org_donors_reviewed(path=ORG_DONORS_REVIEWED_CSV):
    """Read the outcome of reviewing every organization donor of $1M or more.

    Parameters
    ----------
    path : pathlib.Path, optional
        CSV with columns entity_name, total, category, attributed_to,
        source_url, note.

    Returns
    -------
    list of dict
        One dict per organization, with `total` as a float.

    Raises
    ------
    ValueError
        If the category is not in ORG_CATEGORIES, an attributed row has no
        attributed_to or source_url, or any other row has no note saying how
        it was classified.
    """
    rows = _read_stripped(path)
    for row in rows:
        entity = row["entity_name"] or "?"
        if row["category"] not in ORG_CATEGORIES:
            raise ValueError(f"{entity} has unknown category {row['category']!r}")
        if row["category"] == "attributed":
            for column in ("attributed_to", "source_url"):
                if not row[column]:
                    raise ValueError(f"{entity} is attributed but has no {column}")
        elif not row["note"]:
            raise ValueError(f"{entity} has no note on how it was classified")
        row["total"] = float(row["total"])
    return rows


ENDORSER_SIDES = {"R", "D"}
# official: the endorser's own list page. tracker: a third party (Ballotpedia)
# that compiles the endorser's announcements and links each one.
LIST_KINDS = {"official", "tracker"}
# How an endorsement_date was found. announced: the date of the endorser's own
# post. listed_by: the earliest archived copy of the list that shows the
# candidate, so the real endorsement came on or before that date.
DATE_BASES = {"announced", "listed_by"}


def load_endorsers(path=ENDORSERS_CSV):
    """Read the endorsers tracked in the endorsements section.

    Parameters
    ----------
    path : pathlib.Path, optional
        CSV with columns endorser, side, list_url, list_kind, checked_on,
        note.

    Returns
    -------
    list of dict
        One dict per endorser, with whitespace stripped.

    Raises
    ------
    ValueError
        If a row has no list_url, a side other than R or D, or a list_kind
        not in LIST_KINDS.
    """
    rows = _read_stripped(path)
    for row in rows:
        endorser = row["endorser"] or "?"
        if not row["list_url"]:
            raise ValueError(f"{endorser} has no list_url")
        if row["side"] not in ENDORSER_SIDES:
            raise ValueError(f"{endorser} has side {row['side']!r}, expected R or D")
        if row["list_kind"] not in LIST_KINDS:
            raise ValueError(f"{endorser} has unknown list_kind {row['list_kind']!r}")
    return rows


def load_endorsements(path=ENDORSEMENTS_CSV, endorsers_path=ENDORSERS_CSV):
    """Read the sourced House primary endorsements.

    Parameters
    ----------
    path : pathlib.Path, optional
        CSV with columns endorser, candidate_id, race_id, candidate_name,
        endorsement_date, date_basis, source_url, source_outcome, note.
        source_outcome is the source's own primary result where it gives
        one (Ballotpedia's outcome column), and blank otherwise.
    endorsers_path : pathlib.Path, optional
        The endorsers CSV every row's endorser must appear in.

    Returns
    -------
    list of dict
        One dict per endorsement, with whitespace stripped. A blank
        endorsement_date means the timing is unknown, and the analysis
        keeps those rows out of the headline win rate.

    Raises
    ------
    ValueError
        If a row has no source_url or race_id, names an endorser missing
        from endorsers_path, has a date that is not YYYY-MM-DD, or has a
        date without a date_basis in DATE_BASES.
    """
    known = {row["endorser"] for row in load_endorsers(endorsers_path)}
    rows = _read_stripped(path)
    for row in rows:
        label = f"{row['endorser']} / {row['candidate_name'] or '?'}"
        for column in ("source_url", "race_id"):
            if not row[column]:
                raise ValueError(f"{label} has no {column}")
        if row["endorser"] not in known:
            raise ValueError(f"{label}: endorser is not in endorsers.csv")
        if row["endorsement_date"]:
            try:
                date.fromisoformat(row["endorsement_date"])
            except ValueError:
                raise ValueError(f"{label} has endorsement_date {row['endorsement_date']!r}, expected YYYY-MM-DD")
            if row["date_basis"] not in DATE_BASES:
                raise ValueError(f"{label} has unknown date_basis {row['date_basis']!r}")
    return rows
