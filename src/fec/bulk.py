"""Candidate fundraising totals from the FEC's bulk "current campaigns" file.

The API's /candidates/totals/ endpoint doesn't say how much of a candidate's
money is their own, and only reports itemized (over $200) individual
donations. The bulk summary file (webl26) has both, for every 2026 House and
Senate campaign, in one small download that the FEC refreshes daily.

That matters for the analysis: a candidate who writes their campaign a $3M
check would otherwise look like a $3M fundraiser. `external_contributions`
counts only money raised from other people.

Column layout: https://www.fec.gov/campaign-finance-data/all-candidates-file-description/
"""

import io
import urllib.request
import zipfile

from src.config import CYCLE, RAW_DIR

USER_AGENT = "midterm-money-research/0.1 (portfolio project)"

# The file has no header row. These are the 30 columns in order, from the
# FEC's file description.
SUMMARY_COLUMNS = [
    "CAND_ID", "CAND_NAME", "CAND_ICI", "PTY_CD", "CAND_PTY_AFFILIATION",
    "TTL_RECEIPTS", "TRANS_FROM_AUTH", "TTL_DISB", "TRANS_TO_AUTH", "COH_BOP",
    "COH_COP", "CAND_CONTRIB", "CAND_LOANS", "OTHER_LOANS", "CAND_LOAN_REPAY",
    "OTHER_LOAN_REPAY", "DEBTS_OWED_BY", "TTL_INDIV_CONTRIB", "CAND_OFFICE_ST",
    "CAND_OFFICE_DISTRICT", "SPEC_ELECTION", "PRIM_ELECTION", "RUN_ELECTION",
    "GEN_ELECTION", "GEN_ELECTION_PRECENT", "OTHER_POL_CMTE_CONTRIB",
    "POL_PTY_CONTRIB", "CVG_END_DT", "INDIV_REFUNDS", "CMTE_REFUNDS",
]


def parse_summary(text):
    """Split the pipe-delimited summary file into one dict per campaign.

    Parameters
    ----------
    text : str
        Contents of webl26.txt.

    Returns
    -------
    list of dict
        Column name to raw string value.
    """
    return [dict(zip(SUMMARY_COLUMNS, line.split("|"))) for line in text.splitlines() if line]


def _amount(value):
    """Turn a money field into a float. The FEC writes 0 for "none", so a blank means missing."""
    return float(value) if value else None


def _iso_date(value):
    """Convert the file's MM/DD/YYYY dates to ISO YYYY-MM-DD."""
    if not value:
        return None
    month, day, year = value.split("/")
    return f"{year}-{month}-{day}"


def _total(*amounts):
    """Add amounts, treating missing parts as 0."""
    return sum(a or 0.0 for a in amounts)


def bulk_totals_row(rec, pulled_at):
    """Map one summary-file record to a `candidate_totals` row.

    Parameters
    ----------
    rec : dict
        One record from `parse_summary`.
    pulled_at : str
        ISO date of this pull.

    Returns
    -------
    dict
    """
    individual = _amount(rec["TTL_INDIV_CONTRIB"])
    pac = _amount(rec["OTHER_POL_CMTE_CONTRIB"])
    party = _amount(rec["POL_PTY_CONTRIB"])
    return {
        "candidate_id": rec["CAND_ID"],
        "pulled_at": pulled_at,
        # Campaigns that dropped out or closed stop filing, so an old date
        # here is how the analysis tells active candidates from inactive ones
        "coverage_end_date": _iso_date(rec["CVG_END_DT"]),
        "receipts": _amount(rec["TTL_RECEIPTS"]),
        "disbursements": _amount(rec["TTL_DISB"]),
        # Can be negative: a campaign that spent more than it raised and owes debts
        "cash_on_hand": _amount(rec["COH_COP"]),
        "debts_owed": _amount(rec["DEBTS_OWED_BY"]),
        "individual_contributions": individual,  # all donors, including under $200
        "pac_contributions": pac,
        "party_contributions": party,
        # Loans count as self-funding even if they're repaid later, because
        # the money still came from the candidate when it was spent
        "candidate_self_funding": _total(_amount(rec["CAND_CONTRIB"]), _amount(rec["CAND_LOANS"])),
        # Money raised from other people, net of refunds returned to donors
        "external_contributions": _total(
            individual, -_total(_amount(rec["INDIV_REFUNDS"])),
            pac, party, -_total(_amount(rec["CMTE_REFUNDS"])),
        ),
    }


def house_totals(text, pulled_at):
    """Build `candidate_totals` rows for House campaigns only.

    Parameters
    ----------
    text : str
        Contents of webl26.txt.
    pulled_at : str
        ISO date of this pull.

    Returns
    -------
    list of dict
    """
    # FEC candidate IDs start with the office: H = House, S = Senate
    return [bulk_totals_row(rec, pulled_at) for rec in parse_summary(text) if rec["CAND_ID"].startswith("H")]


def download_summary(cycle=CYCLE):
    """Download the current-campaigns summary file and return its text.

    The zip is saved to data/raw/fec/ so the exact file behind a pull can be
    checked later. The FEC refreshes it daily, so each pull downloads again.

    Parameters
    ----------
    cycle : int, optional
        Election cycle, e.g. 2026.

    Returns
    -------
    str
        Contents of the summary text file inside the zip.
    """
    name = f"webl{str(cycle)[-2:]}"
    out_dir = RAW_DIR / "fec"
    out_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://www.fec.gov/files/bulk-downloads/{cycle}/{name}.zip"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    (out_dir / f"{name}.zip").write_bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        # Names in the file are Latin-1, not UTF-8
        return archive.read(f"{name}.txt").decode("latin-1")
