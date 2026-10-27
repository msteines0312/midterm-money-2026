"""Simple predictions for the 2026 House general elections.

Two rules, no model. The money rule picks the nominee with more external
money (individuals, PACs and parties, never the candidate's own money). The
Cook favorite is the party Cook rates ahead in the race. Both are written next
to each other so a reader can see where they disagree.

Nominees come from Wikipedia (see `src/nominees.py`) and money comes from the
FEC, so the first job is matching one to the other by race and last name.
"""

import re
import unicodedata

import pandas as pd

from src.analysis.tech_money import SUPER_PAC_SPENDING
from src.fec.independent_expenditures import _last_name
from src.manual import load_nominee_matches

# Wikipedia's party words, mapped to FEC party codes. Anything not listed
# (Independent, Libertarian, Green, ...) is a third party.
PARTY_CODES = {
    "Democratic": "DEM",
    "DFL": "DEM",
    "Democratic-NPL": "DEM",
    "Democratic-Farmer-Labor": "DEM",
    "Republican": "REP",
}

# Name suffixes that sit after the last name and must not be mistaken for it
SUFFIXES = {"JR", "SR", "II", "III", "IV"}

OUTPUT_COLUMNS = [
    "race_id", "status", "race_type",
    "dem_name", "dem_candidate_id", "rep_name", "rep_candidate_id",
    "dem_money", "rep_money", "dem_money_share", "money_leader_party",
    "cook_rating", "cook_favorite_party", "incumbent_party",
    "outside_support_dem", "outside_oppose_dem", "outside_support_rep", "outside_oppose_rep",
    "money_and_cook_agree", "third_party_outraised", "notes",
]


# Matching nominees to FEC candidates

def _normalize(text):
    """Uppercase, drop accents and punctuation, and split into words.

    Accents are removed for comparison only, so "Hernández" meets the FEC's
    "HERNANDEZ" while the nominee's displayed name keeps its accent.

    Returns
    -------
    list of str
    """
    unaccented = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", unaccented.upper()).split()


def _fec_last_name_words(fec_name):
    """Last name words from an FEC "LAST, FIRST" name, suffix removed."""
    words = _normalize(_last_name(fec_name))
    return [word for word in words if word not in SUFFIXES]


def _nominee_name_words(name):
    """Words of a nominee's "First Last Jr." name, suffix removed."""
    words = _normalize(name)
    while words and words[-1] in SUFFIXES:
        words.pop()
    return words


def _last_name_matches(nominee_name, fec_name):
    """True when the nominee's name ends with the candidate's FEC last name.

    Comparing the end of the full name handles last names with several words
    ("Van Drew", "De La Cruz") without guessing where the first name stops.
    """
    last_name = _fec_last_name_words(fec_name)
    words = _nominee_name_words(nominee_name)
    return bool(last_name) and len(words) > len(last_name) - 1 and words[-len(last_name):] == last_name


def match_nominees(nominees, candidates, overrides):
    """Attach an FEC candidate ID to each nominee.

    A hand-checked override wins. Otherwise the nominee needs exactly one
    candidate with the same last name in the same race, and no other nominee
    in the race with that last name. Anything less certain stays unmatched
    (None), because a wrong match would put someone else's money on a nominee.

    Parameters
    ----------
    nominees : list of dict
        Output of `parse_nominees`.
    candidates : list of dict
        Rows of the `candidates` table.
    overrides : list of dict
        Output of `load_nominee_matches`.

    Returns
    -------
    list of dict
        The nominees, each with a `candidate_id` key (str or None).
    """
    override_ids = {(row["race_id"], row["name"]): row["candidate_id"] for row in overrides}
    matched = []
    for nominee in nominees:
        key = (nominee["race_id"], nominee["name"])
        if key in override_ids:
            candidate_id = override_ids[key]
        else:
            candidate_id = _last_name_match(nominee, nominees, candidates)
        matched.append({**nominee, "candidate_id": candidate_id})
    return matched


def _last_name_match(nominee, race_nominees, candidates):
    """Candidate ID for the one same-race last-name match, else None."""
    race = nominee["race_id"]
    same_last_name = [
        other for other in race_nominees
        if other["race_id"] == race and _same_last_name(other["name"], nominee["name"])
    ]
    if len(same_last_name) > 1:
        return None
    hits = [
        candidate for candidate in candidates
        if candidate["race_id"] == race and _last_name_matches(nominee["name"], candidate["name"])
    ]
    return hits[0]["candidate_id"] if len(hits) == 1 else None


def _same_last_name(name_a, name_b):
    """True when two nominee names end with the same word (suffixes ignored)."""
    words_a, words_b = _nominee_name_words(name_a), _nominee_name_words(name_b)
    return bool(words_a) and bool(words_b) and words_a[-1] == words_b[-1]


# Loading the numbers

def _load_money(conn, pulled_at):
    """External money by candidate ID, negatives floored at 0.

    Self-funding is never read: it is not fundraising.
    """
    frame = pd.read_sql_query(
        "SELECT candidate_id, external_contributions FROM candidate_totals WHERE pulled_at = ?",
        conn, params=(pulled_at,),
    )
    money = frame["external_contributions"].fillna(0).clip(lower=0)
    return dict(zip(frame["candidate_id"], money))


def _load_outside(conn, pulled_at):
    """General-election super PAC spending by (candidate ID, S or O).

    Only election_type 'G' counts, so primary and runoff spending never
    shows up beside a general election prediction. The committee filter is
    the one the tech money report uses.
    """
    sql = f"""
        SELECT candidate_id, support_oppose, SUM(total) AS total
        FROM ({SUPER_PAC_SPENDING})
        WHERE election_type = 'G' AND candidate_id IS NOT NULL
        GROUP BY candidate_id, support_oppose
    """
    frame = pd.read_sql_query(sql, conn, params={"pulled_at": pulled_at})
    return {(row.candidate_id, row.support_oppose): row.total for row in frame.itertuples()}


def _load_cook(conn):
    """Cook rating by race ID (None when the race is not in `races`)."""
    frame = pd.read_sql_query("SELECT race_id, cook_rating FROM races", conn)
    return dict(zip(frame["race_id"], frame["cook_rating"]))


def _load_candidates(conn):
    """Rows of the `candidates` table as dicts."""
    return pd.read_sql_query("SELECT * FROM candidates", conn).to_dict("records")


# Building one race

def _party_code(nominee):
    """DEM, REP, or the nominee's own party word for a third party."""
    return PARTY_CODES.get(nominee["party"], "OTHER")


def _race_type(nominees):
    """Classify a race by who is on the ballot.

    Returns
    -------
    str
        D_vs_R (one Democrat and one Republican, third parties allowed),
        unopposed, same_party (two nominees from one major party), or other.
    """
    codes = [_party_code(nominee) for nominee in nominees]
    if codes.count("DEM") == 1 and codes.count("REP") == 1:
        return "D_vs_R"
    if len(nominees) == 1:
        return "unopposed"
    if len(nominees) == 2 and codes[0] == codes[1] and codes[0] in ("DEM", "REP"):
        return "same_party"
    return "other"


def _cook_favorite(rating):
    """DEM or REP for a Lean, Likely or Solid rating, None for Toss Up or no rating."""
    if rating and rating[-2:] in (" D", " R"):
        return "DEM" if rating.endswith("D") else "REP"
    return None


def _outside(outside, nominee):
    """(support, oppose) general election outside spending for one nominee."""
    candidate_id = nominee["candidate_id"] if nominee else None
    return outside.get((candidate_id, "S"), 0.0), outside.get((candidate_id, "O"), 0.0)


def _pick_two(race_type, nominees):
    """Choose the nominees for the dem_* and rep_* columns.

    D_vs_R uses the Democrat and the Republican. Other races use the top two
    by money, richest first. An unopposed race fills only one slot.

    Returns
    -------
    tuple of (dict or None, dict or None)
    """
    if race_type == "D_vs_R":
        dem = next(n for n in nominees if n["party_code"] == "DEM")
        rep = next(n for n in nominees if n["party_code"] == "REP")
        return dem, rep
    ranked = sorted(nominees, key=lambda n: -n["money"])
    if race_type == "unopposed":
        only = ranked[0]
        return (None, only) if only["party_code"] == "REP" else (only, None)
    return ranked[0], ranked[1]


def _money_share(first_money, second_money):
    """First nominee's share of the pair's money, or None when both have none."""
    total = first_money + second_money
    return first_money / total if total > 0 else None


def _leader_party(share, first, second):
    """Party code of the money leader, or None for a tie, no money, or a third party."""
    if share is None or share == 0.5:
        return None
    leader = first if share > 0.5 else second
    return leader["party_code"] if leader["party_code"] in ("DEM", "REP") else None


def _notes(race_type, nominees, picked):
    """Plain-language notes for races that are not a clean Democrat versus Republican pair."""
    notes = []
    if race_type in ("same_party", "other"):
        names = " and ".join(n["name"] for n in picked if n)
        notes.append(f"{race_type} race: dem and rep columns hold the top two by money ({names}); no Cook favorite")
    if race_type == "other":
        notes.append(f"{len(nominees)} nominees, not one Democrat against one Republican")
    if race_type == "unopposed":
        notes.append("unopposed: listed but not scored")
    unmatched = [n["name"] for n in nominees if n["candidate_id"] is None]
    if unmatched:
        notes.append("no FEC match, counted as $0: " + ", ".join(unmatched))
    return "; ".join(notes)


def _build_race(race_id, nominees, ctx):
    """One output row for one race.

    Parameters
    ----------
    race_id : str
    nominees : list of dict
        This race's nominees, already matched.
    ctx : dict
        Lookups: `money`, `outside`, `cook`, `incumbents`.
    """
    for nominee in nominees:
        nominee["party_code"] = _party_code(nominee)
        nominee["money"] = ctx["money"].get(nominee["candidate_id"], 0.0)
    race_type = _race_type(nominees)
    dem, rep = _pick_two(race_type, nominees)

    dem_money = dem["money"] if dem else 0.0
    rep_money = rep["money"] if rep else 0.0
    share = _money_share(dem_money, rep_money) if dem and rep else None
    leader = _leader_party(share, dem, rep) if dem and rep else None
    favorite = _cook_favorite(ctx["cook"].get(race_id)) if race_type == "D_vs_R" else None

    support_dem, oppose_dem = _outside(ctx["outside"], dem)
    support_rep, oppose_rep = _outside(ctx["outside"], rep)
    incumbent = next((n for n in nominees if ctx["incumbents"].get(n["candidate_id"]) == "I"), None)
    # A third party counts as outraising when it beats at least one major nominee, which
    # means the Democrat and Republican are no longer the top two in the race.
    # A third-party nominee with no FEC match or no money row counts as $0
    # here (the 0.0 default above), so it can never outraise a major nominee.
    others = [n for n in nominees if n is not dem and n is not rep]
    outraised = race_type == "D_vs_R" and any(n["money"] > min(dem_money, rep_money) for n in others)

    return {
        "race_id": race_id,
        "status": "unconfirmed" if any(n["status"] != "confirmed" for n in nominees) else "confirmed",
        "race_type": race_type,
        "dem_name": dem["name"] if dem else None,
        "dem_candidate_id": dem["candidate_id"] if dem else None,
        "rep_name": rep["name"] if rep else None,
        "rep_candidate_id": rep["candidate_id"] if rep else None,
        "dem_money": dem_money,
        "rep_money": rep_money,
        "dem_money_share": share,
        "money_leader_party": leader,
        "cook_rating": ctx["cook"].get(race_id),
        "cook_favorite_party": favorite,
        "incumbent_party": incumbent["party_code"] if incumbent else None,
        "outside_support_dem": support_dem,
        "outside_oppose_dem": oppose_dem,
        "outside_support_rep": support_rep,
        "outside_oppose_rep": oppose_rep,
        "money_and_cook_agree": (leader == favorite) if leader and favorite else None,
        "third_party_outraised": outraised,
        "notes": _notes(race_type, nominees, (dem, rep)),
    }


def simple_predictions(conn, nominees, pulled_at):
    """Build the money rule and Cook favorite for every race.

    Money is each nominee's `external_contributions` from the snapshot, with
    negatives floored at 0 and unmatched nominees at $0. Outside spending is
    context only and counts general election (election_type 'G') spending by
    super PACs and hybrid PACs, the same committees as the tech money report.

    Parameters
    ----------
    conn : sqlite3.Connection
    nominees : list of dict
        Output of `parse_nominees`.
    pulled_at : str
        ISO date of the snapshot, such as "2026-10-23".

    Returns
    -------
    pandas.DataFrame
        One row per race, with the columns in OUTPUT_COLUMNS. `dem_*` and
        `rep_*` hold the Democratic and Republican nominees in D_vs_R races,
        and the top two by money (richest first) in same_party and other races.
        `money_leader_party` and `cook_favorite_party` are None when the rule
        abstains.
    """
    candidates = _load_candidates(conn)
    matched = match_nominees(nominees, candidates, load_nominee_matches())
    ctx = {
        "money": _load_money(conn, pulled_at),
        "outside": _load_outside(conn, pulled_at),
        "cook": _load_cook(conn),
        "incumbents": {c["candidate_id"]: c["incumbent_challenge"] for c in candidates},
    }
    by_race = {}
    for nominee in matched:
        by_race.setdefault(nominee["race_id"], []).append(nominee)

    rows = [_build_race(race_id, race_nominees, ctx) for race_id, race_nominees in sorted(by_race.items())]
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
