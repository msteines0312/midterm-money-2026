"""Endorsements: who was endorsed, in what kind of primary, and who won.

The question is how often endorsed candidates won their 2026 House
primaries, split by incumbents, open seats, and contested primaries. Raw win
rates flatter endorsers, because they tend to back favorites, so every rate
here is reported next to a baseline for all candidates in the same kind of
race.

This module holds the primary context: primary dates, each candidate's
status, and whether their party's primary was a real contest.
"""

import math

import pandas as pd

from src.analysis.billionaires import PRIMARY_SPENDING, primary_outcomes
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
        One row per candidate with candidate_id, name (FEC spelling),
        race_id, party, status (incumbent, open_seat, or challenger),
        external, contested, and top_fundraiser (raised the most of their
        party in the race).
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
    columns = ["candidate_id", "name", "race_id", "party", "status", "external", "contested", "top_fundraiser"]
    return candidates[columns].reset_index(drop=True)


# Outcomes

def _timing(endorsement_date, dates):
    """When an endorsement came relative to the race's primary.

    Returns
    -------
    str
        before (on or before primary day), runoff (after the primary but on
        or before the runoff), after, or unknown (no date, or no primary
        date for the state).
    """
    if not endorsement_date or not dates:
        return "unknown"
    if endorsement_date <= dates["primary_date"]:
        return "before"
    if dates["runoff_date"] and endorsement_date <= dates["runoff_date"]:
        return "runoff"
    return "after"


def _someone_else_won(row, people, nominee_ids):
    """Whether the race's nominee is a different person who shares this candidate's last name.

    `primary_outcomes` falls back to a last-name match so a duplicate FEC
    filing still counts. That fallback also credits Mayra Flores (TX-34)
    with Eric Flores's nomination. When the nominee's own filing is in the
    candidates table and is not the same person (same last name and same
    money, as in `_person_key`), the name match is wrong.
    """
    rivals = people[(people["race_id"] == row["race_id"]) & (people["party"] == row["party"])
                    & people["candidate_id"].isin(nominee_ids) & (people["candidate_id"] != row["candidate_id"])]
    if rivals.empty:
        return False
    return all(_person_key(rival) != _person_key(row) for _, rival in rivals.iterrows())


def _score(frame, nominee_ids, nominees, primary_dates, as_of, people=None):
    """Add an outcome column: won, lost, review, or pending.

    Outcomes come from `primary_outcomes` in the billionaire section, so a
    nominee means the same thing in both sections. A race whose primary is
    still to come (the Louisiana House primaries moved to Nov 3) is
    pending, never a loss. `people` (classify_primary rows, defaulting to
    `frame`) is where a name match is checked against the nominee's own filing.
    """
    people = frame if people is None else people
    support = frame.assign(candidate_name=frame["name"], support_oppose="S")
    scored = primary_outcomes(support, nominee_ids, nominees)
    outcome = scored["outcome"].tolist()
    for i, (matched_by, (_, row)) in enumerate(zip(scored["matched_by"], frame.iterrows())):
        if matched_by == "name" and _someone_else_won(row, people, nominee_ids):
            outcome[i] = "lost"
    for i, race_id in enumerate(frame["race_id"]):
        dates = primary_dates_for(race_id, primary_dates)
        if dates and dates["primary_date"] > as_of:
            outcome[i] = "pending"
    return frame.assign(outcome=outcome)


# What a source says happened, in Ballotpedia's words. Only two outcomes
# override the nominee test: a candidate who was never on the primary ballot
# (endorsed early, then retired or moved) did not run a primary at all, and
# one who left the ballot only after the primary had already won it.
NOT_ON_PRIMARY_BALLOT = "Not on the ballot primary"
LEFT_AFTER_PRIMARY = "Not on the ballot general"


def _source_override(outcome, source_outcome):
    """Apply the source's own result where the nominee test cannot see it."""
    if source_outcome == NOT_ON_PRIMARY_BALLOT:
        return "withdrew"
    if source_outcome == LEFT_AFTER_PRIMARY and outcome == "lost":
        return "won"
    return outcome


def endorsement_outcomes(endorsements, primary_dates, classified, nominee_ids, nominees, as_of):
    """Join each endorsement to its primary context and outcome.

    Parameters
    ----------
    endorsements : list of dict
        Output of `load_endorsements`.
    primary_dates : dict
        Output of `load_primary_dates`.
    classified : pandas.DataFrame
        Output of `classify_primary`, covering at least the endorsed
        candidates. Passing every candidate lets a name match be checked
        against the nominee's own filing.
    nominee_ids : set of str
        FEC IDs of the November nominees.
    nominees : list of dict
        Nominees with race_id and name, for candidates matched by name.
    as_of : str
        YYYY-MM-DD. Primaries after this date are pending.

    Returns
    -------
    pandas.DataFrame
        One row per endorsement with endorser, candidate_id, race_id, name,
        status, contested, top_fundraiser, timing, hedged (the same endorser
        backed two or more candidates on one party's primary ballot), and
        outcome (won, lost, review, pending, or withdrew for a candidate the
        source says was never on the primary ballot).
    """
    frame = pd.DataFrame(endorsements)
    if "source_outcome" not in frame:
        frame["source_outcome"] = ""
    frame = frame[["endorser", "candidate_id", "endorsement_date", "source_outcome"]]
    frame = frame.merge(classified, on="candidate_id", how="left")
    frame["timing"] = [
        _timing(day, primary_dates_for(race_id, primary_dates))
        for day, race_id in zip(frame["endorsement_date"], frame["race_id"])
    ]
    # Hedging means backing two candidates on the same primary ballot before
    # the vote. An endorsee who was never on it (an incumbent who retired,
    # replaced by a new endorsement) does not make the second endorsement a
    # hedge. Neither does backing the winner after the primary, which would
    # otherwise hide the earlier endorsee's loss.
    on_ballot = frame[(frame["source_outcome"] != NOT_ON_PRIMARY_BALLOT) & (frame["timing"] == "before")]
    backed = on_ballot.groupby(["endorser", "race_id", "party"])["candidate_id"].transform("nunique")
    frame["hedged"] = (backed > 1).reindex(frame.index, fill_value=False)
    frame = _score(frame, nominee_ids, nominees, primary_dates, as_of, people=classified)
    frame["outcome"] = [_source_override(o, src) for o, src in zip(frame["outcome"], frame["source_outcome"])]
    columns = ["endorser", "candidate_id", "race_id", "name", "status", "contested", "top_fundraiser",
               "timing", "hedged", "outcome"]
    return frame[columns]


# Win rates

def wilson_interval(won, decided, z=1.96):
    """95% Wilson score interval for a win rate.

    The Wilson interval stays inside 0 to 1 and behaves sensibly for small
    counts, where the usual rate plus or minus 1.96 standard errors does not
    (3 of 3 would give an interval from exactly 1 to 1).

    Returns
    -------
    tuple of (float, float) or (None, None)
        The bounds, or Nones when nothing was decided.
    """
    if decided == 0:
        return None, None
    p = won / decided
    denominator = 1 + z**2 / decided
    center = (p + z**2 / (2 * decided)) / denominator
    half_width = z * math.sqrt(p * (1 - p) / decided + z**2 / (4 * decided**2)) / denominator
    return center - half_width, center + half_width


def _headline(outcomes):
    """Endorsements that count toward a win rate.

    Dated on or before the primary, not hedged, with the primary held, and
    with the candidate on the primary ballot.
    """
    return outcomes[(outcomes["timing"] == "before") & ~outcomes["hedged"]
                    & ~outcomes["outcome"].isin(["pending", "withdrew"])]


def _stratum(row):
    """incumbent, open_seat, or challenger for a contested primary, else uncontested."""
    return row["status"] if row["contested"] else "uncontested"


def _rate_rows(frame, group_columns):
    """won, lost, review, rate, low, and high per group and stratum.

    Adds an all_contested row per group that pools the three contested strata.
    """
    columns = group_columns + ["stratum", "won", "lost", "review", "rate", "low", "high"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame = frame.assign(stratum=frame.apply(_stratum, axis=1))
    pooled = frame[frame["stratum"] != "uncontested"].assign(stratum="all_contested")
    rows = []
    for keys, group in pd.concat([frame, pooled]).groupby(group_columns + ["stratum"]):
        won = int((group["outcome"] == "won").sum())
        lost = int((group["outcome"] == "lost").sum())
        low, high = wilson_interval(won, won + lost)
        rows.append({
            **dict(zip(group_columns + ["stratum"], keys)),
            "won": won, "lost": lost, "review": int((group["outcome"] == "review").sum()),
            "rate": won / (won + lost) if won + lost else None, "low": low, "high": high,
        })
    # object dtype keeps None as None instead of turning it into NaN
    return pd.DataFrame(rows, columns=columns).astype(object)


def endorsement_win_rates(outcomes):
    """Win rates of endorsed candidates by endorser and stratum.

    Only headline endorsements count (see `_headline`). Each candidate is
    counted once per endorser.

    Returns
    -------
    pandas.DataFrame
        endorser, stratum (incumbent, open_seat, challenger, all_contested,
        or uncontested), won, lost, review, rate, low, high. Empty if no
        endorsement qualifies.
    """
    headline = _headline(outcomes).drop_duplicates(["endorser", "candidate_id"])
    return _rate_rows(headline, ["endorser"])


def excluded_counts(outcomes):
    """Count, per endorser, the endorsements left out of the win rates and why.

    Returns
    -------
    pandas.DataFrame
        endorser plus one column per reason: after, runoff, unknown, hedged,
        pending, and withdrew. A row can carry more than one reason.
    """
    reasons = {
        "after": outcomes["timing"] == "after",
        "runoff": outcomes["timing"] == "runoff",
        "unknown": outcomes["timing"] == "unknown",
        "hedged": outcomes["hedged"],
        "pending": outcomes["outcome"] == "pending",
        "withdrew": outcomes["outcome"] == "withdrew",
    }
    frame = pd.DataFrame({"endorser": outcomes["endorser"], **reasons})
    return frame.groupby("endorser", as_index=False).sum()


def baseline_rates(classified_all, primary_dates, nominee_ids, nominees, as_of, min_external=10_000,
                   exclude_ids=()):
    """Win rates of all funded candidates, by party and stratum.

    This is roughly what an endorser would score by backing a funded
    candidate at random in the same kind of primary. Candidates under
    `min_external` are left out. Most of them are paper filers who never
    ran, and counting them would make every endorser look good.

    Parameters
    ----------
    classified_all : pandas.DataFrame
        Output of `classify_primary` for every candidate.
    primary_dates, nominee_ids, nominees, as_of
        As in `endorsement_outcomes`.
    min_external : float, optional
        External contributions a candidate needs to be in the baseline.
    exclude_ids : collection of str, optional
        Candidates to leave out, such as the endorsed ones, so the baseline
        does not contain the group it is compared with. Any other filing by
        the same person is left out too.

    Returns
    -------
    pandas.DataFrame
        party, stratum, won, lost, review, rate, low, high.
    """
    # Minnesota Democrats file as the Democratic-Farmer-Labor Party (DFL)
    classified_all = classified_all.assign(party=classified_all["party"].replace("DFL", "DEM"))
    funded = classified_all[
        (classified_all["external"] >= min_external) & classified_all["party"].isin(["REP", "DEM"])
    ]
    # One person filed twice (same last name and same money) counts once,
    # keeping the filing that is the nominee's if either is
    funded = funded.assign(
        person=[_person_key(row) for _, row in funded.iterrows()],
        is_nominee=funded["candidate_id"].isin(nominee_ids),
    ).sort_values("is_nominee", ascending=False)
    excluded = funded[funded["candidate_id"].isin(set(exclude_ids))]
    left_out = set(zip(excluded["race_id"], excluded["party"], excluded["person"]))
    funded = funded[[key not in left_out for key in zip(funded["race_id"], funded["party"], funded["person"])]]
    funded = funded.drop_duplicates(["race_id", "party", "person"]).drop(columns=["person", "is_nominee"])
    scored = _score(funded, nominee_ids, nominees, primary_dates, as_of, people=classified_all)
    return _rate_rows(scored[scored["outcome"] != "pending"], ["party"])


def favorite_check(outcomes):
    """How often headline endorsements in contested primaries went to the top fundraiser.

    If endorsed candidates were usually already the money leaders, their
    wins say more about who endorsers pick than about what an endorsement
    did.

    Returns
    -------
    dict
        n (decided contested headline endorsements), share_top_fundraiser,
        win_rate_if_top, and win_rate_if_not_top (None when a group is empty).
    """
    headline = _headline(outcomes)
    decided = headline[headline["contested"].astype(bool) & headline["outcome"].isin(["won", "lost"])]
    decided = decided.drop_duplicates(["endorser", "candidate_id"])
    top = decided["top_fundraiser"].astype(bool)

    def rate(rows):
        return float((rows["outcome"] == "won").mean()) if len(rows) else None

    return {
        "n": int(len(decided)),
        "share_top_fundraiser": float(top.mean()) if len(decided) else None,
        "win_rate_if_top": rate(decided[top]),
        "win_rate_if_not_top": rate(decided[~top]),
    }


# Super PAC primary spending, treated as backing

def super_pac_backing(conn, pulled_at, min_spend=10_000):
    """List the House primary candidates each super PAC spent to support.

    A super PAC spending heavily for a candidate in their primary is a
    public bet on that candidate, much like an endorsement, and it is filed
    for a specific election, so it is never after the fact. This uses the
    same query and $10,000 floor as the billionaire section. Spending
    against a candidate is not counted as backing their rivals.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database with `outside_spending` and `committees`.
    pulled_at : str
        Date of the outside spending snapshot.
    min_spend : float, optional
        Smallest primary and runoff support for one candidate that counts.

    Returns
    -------
    tuple of (pandas.DataFrame, int)
        One row per PAC and candidate with committee_id, pac (the
        committee's name), candidate_id, and total, and the number of
        qualifying rows left out because the filing named no candidate ID.
    """
    spending = pd.read_sql_query(PRIMARY_SPENDING, conn, params={"pulled_at": pulled_at, "min_spend": min_spend})
    support = spending[spending["support_oppose"] == "S"]
    has_id = support["candidate_id"].notna() & (support["candidate_id"] != "")
    names = dict(conn.execute("SELECT committee_id, name FROM committees"))
    backing = support[has_id].assign(pac=lambda frame: frame["committee_id"].map(names))
    backing = backing[["committee_id", "pac", "candidate_id", "total"]].sort_values(["committee_id", "candidate_id"])
    return backing.reset_index(drop=True), int((~has_id).sum())


def backing_outcomes(backing, classified_all, primary_dates, nominee_ids, nominees, as_of):
    """Score super PAC backing the same way as endorsements.

    Parameters
    ----------
    backing : pandas.DataFrame
        Output of `super_pac_backing`.
    classified_all : pandas.DataFrame
        Output of `classify_primary` for every candidate.
    primary_dates, nominee_ids, nominees, as_of
        As in `endorsement_outcomes`.

    Returns
    -------
    pandas.DataFrame
        The `endorsement_outcomes` columns, with the PAC's name as the
        endorser, timing always "before" (the money was spent for the
        primary), and hedged when a PAC backed two candidates in one
        party's primary.
    """
    frame = backing.assign(endorser=backing["pac"].fillna(backing["committee_id"]))
    frame = frame[["endorser", "committee_id", "candidate_id", "total"]].merge(classified_all, on="candidate_id")
    frame["timing"] = "before"
    backed = frame.groupby(["committee_id", "race_id", "party"])["candidate_id"].transform("nunique")
    frame["hedged"] = backed > 1
    frame = _score(frame, nominee_ids, nominees, primary_dates, as_of, people=classified_all)
    columns = ["endorser", "committee_id", "candidate_id", "race_id", "name", "party", "status", "contested",
               "top_fundraiser", "timing", "hedged", "outcome", "total"]
    return frame[columns].reset_index(drop=True)


def backing_rates_by_party(outcomes):
    """Win rates of super PAC-backed candidates, pooled across PACs, by party.

    A candidate backed by several PACs counts once. Only headline rows
    count (see `_headline`), so a candidate a PAC backed alongside a rival
    counts only if some other PAC backed them alone. Minnesota's DFL counts
    as DEM, and candidates of other parties are left out.

    Returns
    -------
    pandas.DataFrame
        party, stratum, won, lost, review, rate, low, high.
    """
    headline = _headline(outcomes).drop_duplicates("candidate_id")
    headline = headline.assign(party=headline["party"].replace("DFL", "DEM"))
    return _rate_rows(headline[headline["party"].isin(["REP", "DEM"])], ["party"])
