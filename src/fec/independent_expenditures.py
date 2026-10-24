"""Outside spending from the FEC's bulk independent expenditure file.

The API's /schedules/schedule_e/by_candidate/ endpoint drops filings that
have no candidate ID, and the Congressional Leadership Fund (C00504530)
files that way: it names the candidate and race but leaves the ID blank.
The bulk file keeps those rows, so this module builds the `outside_spending`
table from it instead.

Two things in the file need care:

* Amended filings. A report that was amended shows up once per version, and
  every version is in the file. Counting all of them would double count.
* Missing candidate IDs. Those rows are matched to a candidate by race and
  last name, and left unmatched (but still counted) when that is ambiguous.

Column layout: https://www.fec.gov/campaign-finance-data/independent-expenditure-file-description/
"""

import csv
import io
import urllib.request
from collections import defaultdict

from src.config import CYCLE, RAW_DIR
from src.fec.bulk import USER_AGENT
from src.fec.transform import race_id, to_money


# The bulk file spells parties out. These are the three major spellings in the
# file; anything else (INDEPENDENT, LIBERTARIAN PARTY, ...) is kept as written.
PARTY_CODES = {
    "DEMOCRATIC PARTY": "DEM",
    "REPUBLICAN PARTY": "REP",
    "DEMOCRATIC-FARMER-LABOR": "DFL",
}


def download_independent_expenditures(cycle=CYCLE):
    """Download the bulk independent expenditure CSV and return its text.

    The file is saved to data/raw/fec/ so the exact file behind a pull can be
    checked later. The FEC refreshes it often, so each pull downloads again.

    Parameters
    ----------
    cycle : int, optional
        Election cycle, e.g. 2026.

    Returns
    -------
    str
        Contents of the CSV, header row included.
    """
    out_dir = RAW_DIR / "fec"
    out_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://www.fec.gov/files/bulk-downloads/{cycle}/independent_expenditure_{cycle}.csv"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    (out_dir / f"independent_expenditure_{cycle}.csv").write_bytes(data)
    # Names in the file are Latin-1, not UTF-8
    return data.decode("latin-1")


def parse_independent_expenditures(text):
    """Split the CSV into one dict per row, keyed by the header.

    Parameters
    ----------
    text : str
        Contents of the CSV.

    Returns
    -------
    list of dict
        Column name to value. Values are stripped, and empty ones are None.
    """
    reader = csv.DictReader(io.StringIO(text))
    return [{column: (value or "").strip() or None for column, value in row.items()} for row in reader]


def _file_number(row):
    """The row's filing number as an int, 0 when the file left it blank."""
    return int(row["file_num"] or 0)


def drop_superseded(rows):
    """Keep only the latest version of each expenditure.

    An amendment names the filing it replaces in `prev_file_num`, so any
    filing listed there is out of date. A transaction can also be reported in
    more than one filing without a link between them, so after that the
    highest `file_num` wins for each (committee, transaction) pair.

    Parameters
    ----------
    rows : list of dict
        Output of `parse_independent_expenditures`.

    Returns
    -------
    list of dict
    """
    replaced_filings = {row["prev_file_num"] for row in rows if row["prev_file_num"]}
    current = [row for row in rows if row["file_num"] not in replaced_filings]

    latest = {}
    for row in current:
        key = (row["spe_id"], row["tran_id"])
        # file_num is a number in a text column, so compare as ints ("999" > "1000" as text).
        # A missing one counts as 0, so any numbered version beats it.
        if key not in latest or _file_number(row) > _file_number(latest[key]):
            latest[key] = row
    return list(latest.values())


def _last_name(full_name):
    """Uppercased text before the first comma, e.g. "Lawler, Michael" -> "LAWLER"."""
    # A missing name becomes "", which matches nobody
    return (full_name or "").split(",")[0].strip().upper()


def _candidates_by_race_and_last_name(candidates):
    """Index candidates so a name in a bulk row can be looked up within its race."""
    index = defaultdict(list)
    for candidate in candidates:
        index[(candidate["race_id"], _last_name(candidate["name"]))].append(candidate)
    return index


def _resolve_candidate(row, race, candidates_by_id, candidates_by_name):
    """Work out the candidate ID and party for one bulk row.

    Parameters
    ----------
    row : dict
        One row from `parse_independent_expenditures`.
    race : str
        The row's `race_id`.
    candidates_by_id : dict
        `candidates` rows keyed by candidate_id.
    candidates_by_name : dict
        `candidates` rows keyed by (race_id, uppercased last name).

    Returns
    -------
    tuple of (str or None, str or None)
        Candidate ID and party. The ID is None when the row has none and no
        single candidate in the race shares the last name.
    """
    candidate_id = row["cand_id"]
    if candidate_id is None:
        matches = candidates_by_name.get((race, _last_name(row["cand_name"])), [])
        # Two candidates with the same last name in one race: don't guess
        candidate_id = matches[0]["candidate_id"] if len(matches) == 1 else None

    # Prefer the party code from `candidates` (DEM, REP, ...) so it matches the
    # rest of the database. Otherwise translate the bulk file's spelled-out name.
    known = candidates_by_id.get(candidate_id)
    if known and known["party"]:
        return candidate_id, known["party"]
    return candidate_id, PARTY_CODES.get(row["cand_pty_aff"], row["cand_pty_aff"])


def _race_for_row(row, candidates_by_id):
    """Find the race for a House row, or None when it can't be told.

    race_id() would turn a blank district into "ST-00", which looks like an
    at-large seat but is really "unknown", and would join to the wrong race.
    So with no district, borrow the race of the candidate named by cand_id,
    and give up (None) if that candidate isn't in `candidates`.
    """
    if row["can_office_dis"] is not None:
        return race_id(row["can_office_state"], row["can_office_dis"])
    known = candidates_by_id.get(row["cand_id"])
    return known["race_id"] if known else None


def house_outside_spending(text, candidates, pulled_at):
    """Build `outside_spending` rows for House races from the bulk file.

    Parameters
    ----------
    text : str
        Contents of the bulk CSV.
    candidates : list of dict
        Rows of the `candidates` table, used to find a candidate ID for rows
        that have none.
    pulled_at : str
        ISO date of this pull.

    Returns
    -------
    list of dict
        One row per committee, candidate, support/oppose, and election type.
    """
    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    candidates_by_name = _candidates_by_race_and_last_name(candidates)

    groups = {}
    for row in drop_superseded(parse_independent_expenditures(text)):
        # A House row without a state can't be placed in a race. A row with no
        # amount has nothing to add (and would break the sum), so it is skipped too.
        # A few real filings leave support/oppose blank. They can't be counted as
        # either side, and the table requires one, so they are skipped as well.
        if (row["can_office"] != "H" or row["can_office_state"] is None
                or row["exp_amo"] is None or row["sup_opp"] is None):
            continue
        race = _race_for_row(row, candidates_by_id)
        candidate_id, party = _resolve_candidate(row, race, candidates_by_id, candidates_by_name)
        # Without an ID, race plus last name still keeps one candidate's money together
        # (a row with no district falls back to the state alone)
        candidate_key = candidate_id or f"{race or row['can_office_state']}|{_last_name(row['cand_name'])}"

        key = (row["spe_id"], candidate_key, row["sup_opp"], row["ele_type"])
        if key not in groups:
            groups[key] = {
                "committee_id": row["spe_id"],
                "candidate_key": candidate_key,
                "candidate_id": candidate_id,
                "candidate_name": row["cand_name"],
                "party": party,
                "race_id": race,
                "election_type": row["ele_type"],
                "support_oppose": row["sup_opp"],
                "pulled_at": pulled_at,
                "total": 0.0,
                "count": 0,
            }
        groups[key]["total"] += to_money(row["exp_amo"])
        groups[key]["count"] += 1
    return list(groups.values())
