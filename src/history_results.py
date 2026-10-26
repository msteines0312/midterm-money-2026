"""House general election results, PVI, and Cook ratings for 2022 and 2024.

These are the training rows for the money model: who ran in each November
general, who won, and how partisan and how competitive each district looked
before the election. Money comes separately, from `history_money` (built by
src/fec/history.py and scripts/load_history_money.py), joined on candidate ID.

2022 results come from the FEC's "Federal Elections" publication, whose
House sheet has one row per candidate per ballot line, each with an FEC
candidate ID. The FEC hasn't published 2024, so 2024 results come from the
certified per-state tables on Wikipedia (vote shares, no counts), matched to
FEC IDs by race and last name. PVI and ratings come from each cycle's own
Wikipedia pages, pinned to the last revision before election day, and parsed
with the same code as 2026.
"""

import re
import urllib.request
import zipfile

from bs4 import BeautifulSoup
from openpyxl import load_workbook

from src.config import (
    FEC_RESULTS_URLS,
    HISTORY_MATCHES_CSV,
    HISTORY_PVI_PAGES,
    HISTORY_RATINGS_PAGES,
    RAW_DIR,
    RESULTS_DIR,
    WIKI_RESULTS_PAGES,
)
from src.fec.bulk import USER_AGENT, download_summary, parse_summary
from src.fec.transform import race_id
from src.manual import load_nominee_matches
from src.nominees import NOTE, PARTY_BAR, _candidates_header_present
from src.predict.simple import PARTY_CODES, _fec_last_name_words, _nominee_name_words, match_nominees
from src.ratings import (
    DISTRICT_LABEL,
    PVI_HEADER,
    _find_column,
    _rows,
    build_races,
    cell_text,
    download_page,
    label_to_race_id,
    parse_cook_ratings,
    parse_pvi_tables,
)

# The House results sheet in the FEC workbook
HOUSE_SHEET = "8. US House Results by State"

# DC and the territories elect non-voting delegates, who aren't part of the model
NON_VOTING = {"DC", "AS", "GU", "MP", "PR", "VI"}

# The DISTRICT cell is "01", sometimes with a trailing space. A district with
# a same-day special election is split into "02-Full Term" (the regular
# general, kept) and "02-Unexpired Term" (the special, which doesn't match).
DISTRICT_CELL = re.compile(r"^(\d{2})(-Full Term)?$")

# On a fusion candidate's (NY, CT) summary line, PARTY holds this label and
# the combined votes across party lines sit in the COMBINED column
COMBINED_LABEL = "Combined Parties:"
COMBINED_COLUMN = "COMBINED GE PARTY TOTALS (when applicable)"
COMBINED_SHARE_COLUMN = "COMBINED GE PARTY % (when applicable)"
# Votes in a general runoff (Georgia and Louisiana, in December)
RUNOFF_COLUMN = "GE RUNOFF ELECTION VOTES (when applicable)"

# Ballot-line party labels that mean a major party. A label can list several
# lines ("D/IP/WF"), and a "*" marks a convention-endorsed candidate. "W(D)"
# alone is a Democratic write-in, which is not a nominee on the ballot.
DEM_LABELS = {"D", "DFL"}
REP_LABELS = {"R"}

# One candidate on the 2024 Wikipedia page: an optional "Y" (the {{Aye}}
# check mark that marks the winner), "Name (Party)", and a vote share. Some
# states (Indiana, Kansas) have no shares listed. Party names can carry
# stray spaces, as in "( Socialist Workers )".
WIKI_CANDIDATE = re.compile(
    r"^(?P<check>Y\s+)?(?P<name>[^()]+?)\s*\(\s*(?P<party>[^()]+?)\s*\)\s*(?:(?P<share>\d+(?:\.\d+)?)%)?$"
)
# Labels in Alaska's ranked-choice cell
FIRST_ROUND = "First round:"
INSTANT_RUNOFF = "Instant runoff"


def download_fec_results(cycle):
    """Save the FEC's results workbook to data/raw/results/, if not already saved.

    The publication is final, so a saved copy is never downloaded again.

    Parameters
    ----------
    cycle : int
        Election year with an entry in FEC_RESULTS_URLS.

    Returns
    -------
    pathlib.Path
        Location of the saved workbook.
    """
    url = FEC_RESULTS_URLS[cycle]
    path = RESULTS_DIR / url.rsplit("/", 1)[-1]
    if not path.exists():
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            path.write_bytes(response.read())
    return path


def read_sheet_rows(path):
    """Read every row of the House results sheet, header row first.

    Parameters
    ----------
    path : pathlib.Path
        An FEC "Federal Elections" workbook, or a test sample with the same sheet.

    Returns
    -------
    list of tuple
        Cell values as openpyxl gives them (int, float, str, or None).
    """
    # read_only streams the sheet instead of loading the whole workbook
    book = load_workbook(path, read_only=True)
    try:
        return list(book[HOUSE_SHEET].iter_rows(values_only=True))
    finally:
        book.close()


def summary_text(cycle):
    """Text of a past cycle's FEC bulk summary file (webl22, webl24).

    These files are final for past cycles, so a copy saved in data/raw/fec/
    is reused instead of downloading again. They are used for candidate IDs
    and the incumbent flag only, never for money: their totals run to the end
    of the cycle and would include money raised after election day.

    Parameters
    ----------
    cycle : int
        Election year, e.g. 2022.

    Returns
    -------
    str
    """
    name = f"webl{str(cycle)[-2:]}"
    saved = RAW_DIR / "fec" / f"{name}.zip"
    if not saved.exists():
        return download_summary(cycle)
    with zipfile.ZipFile(saved) as archive:
        # Names in the file are Latin-1, as in src/fec/bulk.py
        return archive.read(f"{name}.txt").decode("latin-1")


def house_filings(summary_records):
    """House candidates from a webl file, with duplicate registrations folded into one.

    Some candidates have two FEC IDs whose principal committee is the same,
    so the webl file shows two identical campaigns (Rebecca Cooke, WI-03 in
    2024, is H2WI03130 and H4WI03169) and `history_money` holds the same
    money under both IDs. A last-name match would see two hits and give up.
    Records in the same race with the same last name and identical receipts,
    spending, and cash on hand are one campaign, so only the first ID (in
    sorted order) is kept. Either ID finds the same money row, and nothing
    is added across them.

    Parameters
    ----------
    summary_records : list of dict
        Output of `parse_summary`.

    Returns
    -------
    list of dict
    """
    kept = {}
    for rec in sorted(summary_records, key=lambda r: r["CAND_ID"]):
        if not rec["CAND_ID"].startswith("H"):
            continue
        key = (
            race_id(rec["CAND_OFFICE_ST"], rec["CAND_OFFICE_DISTRICT"]),
            tuple(_fec_last_name_words(rec["CAND_NAME"])),
            rec["TTL_RECEIPTS"], rec["TTL_DISB"], rec["COH_COP"],
        )
        kept.setdefault(key, rec)
    return list(kept.values())


# Parsing the FEC results sheet

def sheet_records(sheet_rows):
    """Turn the sheet's rows into dicts keyed by its header.

    Header cells are stripped because some have trailing spaces ("GENERAL VOTES ").

    Parameters
    ----------
    sheet_rows : list of tuple
        Output of `read_sheet_rows`, header first.

    Returns
    -------
    list of dict
    """
    header = [_text(cell) for cell in sheet_rows[0]]
    return [dict(zip(header, row)) for row in sheet_rows[1:]]


def _text(value):
    """A cell as stripped text, with None as an empty string."""
    return str(value).strip() if value is not None else ""


def _race_id(rec):
    """race_id for a line in a voting state's regular general, else None."""
    state = _text(rec["STATE ABBREVIATION"])
    match = DISTRICT_CELL.match(_text(rec["DISTRICT"]))
    if match is None or state in NON_VOTING:
        return None
    return race_id(state, match.group(1))


def _is_general_line(rec):
    """True for a line with November general votes, a general runoff, or fusion totals.

    "Unopposed" in GENERAL VOTES counts too: the candidate was the only one on
    the ballot. Primary-only and primary runoff candidates have none of these.
    """
    columns = ("GENERAL VOTES", RUNOFF_COLUMN, COMBINED_COLUMN)
    return any(rec[column] is not None for column in columns)


def _votes(value):
    """Votes as an int, or None for "Unopposed" and blanks."""
    return value if isinstance(value, int) else None


def _clean_name(raw):
    """Candidate name without the sheet's footnote marks ("Bye, Chris  #" -> "Bye, Chris")."""
    return re.sub(r"[\s#*]+$", "", _text(raw))


def _party(labels):
    """DEM or REP when any ballot line is a major party's, else the labels as listed.

    Parameters
    ----------
    labels : list of str
        PARTY cells from a candidate's lines, e.g. ["D", "WF"] or ["D/IP/WF"].

    Returns
    -------
    str
    """
    tokens = {token.strip(" *") for label in labels for token in label.split("/")}
    if tokens & DEM_LABELS:
        return "DEM"
    if tokens & REP_LABELS:
        return "REP"
    return "/".join(labels)


def general_lines(records):
    """Group a voting state's general election lines by race and candidate.

    Lines without an FEC ID are write-in tallies ("Scattered", "All Others",
    named write-ins) and vote totals. They are dropped, but a Democratic or
    Republican line without an ID raises, so a nominee can't vanish silently.

    Parameters
    ----------
    records : list of dict
        Output of `sheet_records`.

    Returns
    -------
    dict of (str, str) to list of dict
        (race_id, candidate_id) to that candidate's lines.

    Raises
    ------
    ValueError
        If a major-party general line has no FEC ID.
    """
    grouped = {}
    for rec in records:
        rid = _race_id(rec)
        if rid is None or not _is_general_line(rec):
            continue
        # Some IDs carry a trailing space in the sheet; missing ones are "n/a"
        candidate_id = _text(rec["FEC ID"])
        if not candidate_id.startswith("H"):
            if _party([_text(rec["PARTY"])]) in ("DEM", "REP"):
                raise ValueError(f"Major-party general line with no FEC ID in {rid}: {rec['CANDIDATE NAME']!r}")
            continue
        grouped.setdefault((rid, candidate_id), []).append(rec)
    return grouped


def _total_votes(lines, party_lines):
    """A candidate's November votes, or None if they were unopposed.

    A fusion candidate's combined total is repeated on each of their lines.
    Anyone else has a single line, so its general votes are the total.
    """
    combined = [rec[COMBINED_COLUMN] for rec in lines if isinstance(rec[COMBINED_COLUMN], int)]
    if combined:
        return max(combined)
    counted = [_votes(rec["GENERAL VOTES"]) for rec in party_lines]
    return sum(v for v in counted if v is not None) if any(v is not None for v in counted) else None


def _total_share(lines, party_lines):
    """A candidate's November vote share in percent, or None if they were unopposed.

    The sheet stores shares as fractions. Fusion works as in `_total_votes`.
    """
    combined = [rec[COMBINED_SHARE_COLUMN] for rec in lines if isinstance(rec[COMBINED_SHARE_COLUMN], float)]
    if combined:
        return 100 * max(combined)
    shares = [rec["GENERAL %"] for rec in party_lines if isinstance(rec["GENERAL %"], (int, float))]
    return 100 * sum(shares) if shares else None


def _candidate(cycle, rid, candidate_id, lines):
    """Build one `history_results` row from a candidate's lines.

    `won` is the sheet's own winner flag here and may still be settled by
    `_settle_winner`. `_runoff_votes` helps with that and is not stored.
    The ID and incumbent flag are finished in `parse_fec_results`.
    """
    party_lines = [rec for rec in lines if _text(rec["PARTY"]) != COMBINED_LABEL]
    runoff = [_votes(rec[RUNOFF_COLUMN]) for rec in party_lines]
    return {
        "cycle": cycle,
        "race_id": rid,
        "candidate_id": candidate_id,
        "name": _clean_name(party_lines[0]["CANDIDATE NAME"]),
        "party": _party([_text(rec["PARTY"]) for rec in party_lines]),
        "votes": _total_votes(lines, party_lines),
        "vote_share": _total_share(lines, party_lines),
        "won": int(any(_text(rec["GE WINNER INDICATOR"]).startswith("W") for rec in lines)),
        "incumbent_challenge": None,
        # "(I)", or "(I)*" for someone who won a special election earlier in the cycle
        "is_incumbent": int(any(_text(rec["(I) INCUMBENT INDICATOR"]).startswith("(I)") for rec in lines)),
        "_runoff_votes": max((v for v in runoff if v is not None), default=None),
    }


def _settle_winner(rid, candidates):
    """Make sure a race has exactly one winner.

    The sheet's GE WINNER INDICATOR marks the final general winner, which for
    a Georgia or Louisiana general runoff is the runoff winner. If no one is
    marked, the winner is the candidate with the most general runoff votes,
    or else the most November votes. This fallback is a workaround for a gap
    in the sheet. It happens once in 2022 (IN-02, where Yakym replaced the
    late Rep. Walorski on the ballot), and is printed whenever it is used.

    Raises
    ------
    ValueError
        If two candidates are marked as winners.
    """
    marked = [c for c in candidates if c["won"]]
    if len(marked) > 1:
        raise ValueError(f"{rid} has {len(marked)} marked winners")
    if not marked:
        top = max(candidates, key=lambda c: (c["_runoff_votes"] or -1, c["votes"] or -1))
        top["won"] = 1
        print(f"  {rid}: no GE winner marked in the FEC sheet, using most votes ({top['name']})")


def parse_fec_results(sheet_rows, cycle, summary_records, overrides=()):
    """Build `history_results` rows from the FEC's House results sheet.

    Parameters
    ----------
    sheet_rows : list of tuple
        Output of `read_sheet_rows`.
    cycle : int
        Election year.
    summary_records : list of dict
        That cycle's bulk summary file (webl22, webl24) from `parse_summary`.
        It is the source of the incumbent flag, and the list that stale
        sheet IDs are matched against (see `resolve_candidate_id`).
    overrides : list of dict, optional
        Hand-checked matches (data/manual/history_matches.csv), with columns
        cycle, race_id, name, candidate_id, note.

    Returns
    -------
    list of dict
        One row per general election candidate in the 50 states, with
        `won` = 1 for exactly one candidate per race.

    Raises
    ------
    ValueError
        If two candidates in a race share a name (the table's primary key).
    """
    filed = {rec["CAND_ID"]: rec for rec in house_filings(summary_records)}
    override_ids = {
        (row["race_id"], row["name"]): row["candidate_id"]
        for row in overrides if int(row["cycle"]) == cycle
    }
    races = {}
    for (rid, sheet_id), lines in general_lines(sheet_records(sheet_rows)).items():
        candidate = _candidate(cycle, rid, sheet_id, lines)
        candidate["candidate_id"] = override_ids.get((rid, candidate["name"])) or resolve_candidate_id(candidate, filed)
        # CAND_ICI: I = incumbent, C = challenger, O = open seat
        filing = filed.get(candidate["candidate_id"])
        candidate["incumbent_challenge"] = (filing["CAND_ICI"] or None) if filing else None
        races.setdefault(rid, []).append(candidate)

    rows = []
    for rid, candidates in races.items():
        names = [c["name"] for c in candidates]
        if len(set(names)) != len(names):
            raise ValueError(f"Two candidates share a name in {rid}: {names}")
        _settle_winner(rid, candidates)
        rows += [{k: v for k, v in c.items() if not k.startswith("_")} for c in candidates]
    return rows


def resolve_candidate_id(candidate, filed):
    """The candidate's FEC ID, swapped for the filed one when the sheet's ID is stale.

    About 50 of the 2022 sheet's IDs aren't in that cycle's webl file (often
    an ID from an earlier run for office), so they would never meet the
    candidate's money. When that happens, the candidate is matched to the one
    filed candidate in the same race and party with the same last name. The
    last-name rules are the ones src/predict/simple.py uses for 2026 nominees
    (accents and suffixes ignored). Anything less certain keeps the sheet's ID.

    Parameters
    ----------
    candidate : dict
        A row from `_candidate`.
    filed : dict of str to dict
        webl records for House candidates, by CAND_ID.

    Returns
    -------
    str
    """
    if candidate["candidate_id"] in filed:
        return candidate["candidate_id"]
    last_name = _fec_last_name_words(candidate["name"])
    hits = [
        rec["CAND_ID"] for rec in filed.values()
        if race_id(rec["CAND_OFFICE_ST"], rec["CAND_OFFICE_DISTRICT"]) == candidate["race_id"]
        and rec["CAND_PTY_AFFILIATION"] == candidate["party"]
        and _fec_last_name_words(rec["CAND_NAME"]) == last_name
    ]
    return hits[0] if len(hits) == 1 else candidate["candidate_id"]


def dem_vs_rep_races(rows):
    """race_ids with exactly one Democrat and one Republican on the general ballot.

    Third-party candidates are allowed, matching `_race_type` in
    src/predict/simple.py. These are the races the model trains on.

    Parameters
    ----------
    rows : list of dict
        `history_results` rows for one cycle.

    Returns
    -------
    set of str
    """
    parties = {}
    for row in rows:
        parties.setdefault(row["race_id"], []).append(row["party"])
    return {
        rid for rid, listed in parties.items()
        if listed.count("DEM") == 1 and listed.count("REP") == 1
    }


# Parsing the 2024 results from Wikipedia

def _wiki_candidate(text):
    """Read one "Y Name (Party) 56.3%" entry from a candidates cell.

    Returns
    -------
    dict
        `name`, `party` (as Wikipedia words it), `vote_share` (float or
        None), and `checked` (True if the entry has the winner's check mark).

    Raises
    ------
    ValueError
        If the text doesn't have that shape, so a layout change fails loudly.
    """
    match = WIKI_CANDIDATE.match(NOTE.sub("", text).strip())
    if match is None:
        raise ValueError(f"Not a recognizable candidate: {text!r}")
    share = match.group("share")
    return {
        "name": match.group("name").strip(),
        "party": match.group("party").strip(),
        "vote_share": float(share) if share else None,
        "checked": bool(match.group("check")),
    }


def wiki_candidates(cell_value):
    """Read every candidate in one district's candidates cell, and mark the winner.

    The check mark ({{Aye}}, which renders as "Y") marks the winner. Alaska's
    ranked-choice cell lists a first round, where the top four all get a
    check mark for advancing, and then an instant runoff. Candidates and
    shares come from the first round, matching the FEC sheet's convention for
    2022, and the winner is the one checked in the instant runoff.

    Parameters
    ----------
    cell_value : str
        Cleaned text of the cell, from `ratings.cell_text`.

    Returns
    -------
    list of dict
        Output of `_wiki_candidate` plus `won` (0 or 1).
    """
    first_round, _, final_round = cell_value.partition(INSTANT_RUNOFF)
    first_round = first_round.replace(FIRST_ROUND, "")
    candidates = [_wiki_candidate(part) for part in _split_on_bar(first_round)]
    if final_round:
        winners = {c["name"] for c in map(_wiki_candidate, _split_on_bar(final_round.lstrip(" :"))) if c["checked"]}
    else:
        winners = {c["name"] for c in candidates if c["checked"]}
    return [{**c, "won": int(c["name"] in winners)} for c in candidates]


def _split_on_bar(text):
    """Split candidates text on the party stripe, as `nominees.split_nominees` does."""
    return [part.strip() for part in text.split(PARTY_BAR) if part.strip()]


def _same_person(nominee_name, member_name):
    """True when a nominee is the district's incumbent.

    Names are compared without accents, punctuation, or suffixes. The last
    name must match, and so must the first initial, which allows a nickname
    ("Tom Kean Jr." for the incumbent column's "Thomas Kean Jr.") but still
    keeps apart two people with one last name (SD-00's Dusty and Sheryl Johnson).
    """
    nominee, member = _nominee_name_words(nominee_name), _nominee_name_words(member_name)
    return bool(nominee) and bool(member) and nominee[-1] == member[-1] and nominee[0][0] == member[0][0]


def _member_name(cell):
    """An incumbent's name from the Member cell (the hCard name when there is one)."""
    card = cell.find(class_="fn")
    return cell_text(card) if card else cell_text(cell)


def wiki_districts(html):
    """Read each district's incumbents and candidates cell from the per-state tables.

    Parameters
    ----------
    html : str
        The elections page after certification.

    Returns
    -------
    dict of str to dict
        race_id to `members` (incumbent names; two when redistricting put
        two in one seat) and `candidates` (the cell's cleaned text).

    Raises
    ------
    ValueError
        If a district appears in two tables.
    """
    districts = {}
    current = None
    for table in BeautifulSoup(html, "html.parser").find_all("table", class_="wikitable"):
        rows = _rows(table)
        # Same test as nominees.parse_nominees: PVI plus Candidates marks a state table
        if _find_column(rows[:2], PVI_HEADER) is None or not _candidates_header_present(rows):
            continue
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if not cells or row.find("th", colspan=True) or cell_text(cells[0]) in ("Location", ""):
                continue
            if DISTRICT_LABEL.match(cell_text(cells[0])):
                rid = label_to_race_id(cell_text(cells[0]))
                if rid in districts:
                    raise ValueError(f"District listed twice: {rid}")
                # Candidates is always the last cell of a district's first row
                current = districts[rid] = {"members": [_member_name(cells[2])], "candidates": cell_text(cells[-1])}
            elif current is not None:
                # A second incumbent's continuation row starts with their Member cell
                current["members"].append(_member_name(cells[0]))
    return districts


def parse_wiki_results(html, cycle, summary_records, overrides=()):
    """Build `history_results` rows from the elections page's per-state tables.

    The fallback for a cycle without an FEC results sheet (2024). Wikipedia
    gives vote shares, not counts, so `votes` is None. Candidates are matched
    to FEC IDs by race and last name against the cycle's webl file, with the
    same rules (and override format) as the 2026 nominees.

    Parameters
    ----------
    html : str
        The elections page after certification.
    cycle : int
    summary_records : list of dict
        That cycle's webl file from `parse_summary`.
    overrides : list of dict, optional
        Rows of data/manual/history_matches.csv.

    Returns
    -------
    list of dict
        One row per general election candidate, `won` = 1 for one per race.

    Raises
    ------
    ValueError
        If a race has no winner, more than one, or two candidates share a name.
    """
    filed = house_filings(summary_records)
    fec_candidates = [
        {"race_id": race_id(rec["CAND_OFFICE_ST"], rec["CAND_OFFICE_DISTRICT"]),
         "name": rec["CAND_NAME"], "candidate_id": rec["CAND_ID"]}
        for rec in filed
    ]
    incumbency = {rec["CAND_ID"]: rec["CAND_ICI"] or None for rec in filed}
    cycle_overrides = [row for row in overrides if int(row["cycle"]) == cycle]

    rows = []
    for rid, district in wiki_districts(html).items():
        candidates = [{"race_id": rid, **c} for c in wiki_candidates(district["candidates"])]
        names = [c["name"] for c in candidates]
        if sum(c["won"] for c in candidates) != 1 or len(set(names)) != len(names):
            raise ValueError(f"{rid} needs one winner and distinct names: {candidates}")
        for c in match_nominees(candidates, fec_candidates, cycle_overrides):
            rows.append({
                "cycle": cycle,
                "race_id": rid,
                "candidate_id": c["candidate_id"],
                "name": c["name"],
                "party": PARTY_CODES.get(c["party"], c["party"]),
                "votes": None,
                "vote_share": c["vote_share"],
                "won": c["won"],
                "incumbent_challenge": incumbency.get(c["candidate_id"]),
                "is_incumbent": int(any(_same_person(c["name"], m) for m in district["members"])),
            })
    return rows


# PVI and ratings

def build_history_races(cycle, pvi_html, ratings_html):
    """Build `history_races` rows from a past cycle's two pinned Wikipedia pages.

    Same method as 2026 (src/ratings.py): every district's PVI from the
    per-state tables, Cook's rating where the ratings page lists one, and
    Solid D or Solid R from the PVI's sign otherwise.

    Parameters
    ----------
    cycle : int
    pvi_html : str
        The cycle's elections page.
    ratings_html : str
        The cycle's ratings page.

    Returns
    -------
    list of dict
    """
    # "Candidates" keeps only the per-state tables (see parse_pvi_tables)
    pvi = parse_pvi_tables(pvi_html, required_header="Candidates")
    races = build_races(pvi, parse_cook_ratings(ratings_html))
    columns = ["race_id", "cook_pvi", "cook_rating", "rating_source"]
    return [{"cycle": cycle, **{column: race[column] for column in columns}} for race in races]


# Loading

def load_history_results(cycle):
    """Download (if needed) and parse one cycle's House general results.

    Uses the FEC results sheet when the cycle has one (2022), and otherwise
    the certified Wikipedia tables (2024).

    Parameters
    ----------
    cycle : int

    Returns
    -------
    list of dict
        `history_results` rows.

    Raises
    ------
    ValueError
        If no results source is set up for the cycle.
    """
    summary = parse_summary(summary_text(cycle))
    # load_nominee_matches checks that every row has a race, name, ID, and note
    overrides = load_nominee_matches(HISTORY_MATCHES_CSV)
    if cycle in FEC_RESULTS_URLS:
        return parse_fec_results(read_sheet_rows(download_fec_results(cycle)), cycle, summary, overrides)
    if cycle in WIKI_RESULTS_PAGES:
        html = download_page(WIKI_RESULTS_PAGES[cycle]).read_text(encoding="utf-8")
        return parse_wiki_results(html, cycle, summary, overrides)
    raise ValueError(f"No House results source is set up for {cycle}")


def load_history_races(cycle):
    """Download (if needed) one cycle's pinned pages and build `history_races` rows.

    Parameters
    ----------
    cycle : int

    Returns
    -------
    list of dict
    """
    pvi_html = download_page(HISTORY_PVI_PAGES[cycle]).read_text(encoding="utf-8")
    ratings_html = download_page(HISTORY_RATINGS_PAGES[cycle]).read_text(encoding="utf-8")
    return build_history_races(cycle, pvi_html, ratings_html)
