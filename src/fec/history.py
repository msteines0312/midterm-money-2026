"""House campaign money for 2022 and 2024, as of each campaign's pre-general report.

The model is trained on past House generals and then predicts 2026. The 2026
money feature is each campaign's cycle-to-date money as of its latest report
through mid-October, so the training feature has to mean the same thing.
End-of-cycle totals would not: winners keep raising after election day, so
those totals leak the result into the money.

Source is the OpenFEC reports API (/reports/house-senate/). Despite the name,
its "_ytd" fields for House committees are Form 3 Column B, "election
cycle-to-date": they restart the day after each general election, not on
January 1. So a campaign's money is simply the "_ytd" figures on its latest
report ending on or before the pre-general cutoff. (Checked by adding up the
"_period" fields across a cycle, and against the raw filed 12G.) Adding the
odd year's year-end report on top would count that year twice.

Campaigns are tied to candidates with the FEC's candidate-committee linkage
bulk file (ccl{yy}.zip). Its columns are documented at
https://www.fec.gov/campaign-finance-data/candidate-committee-linkage-file-description/
"""

import io
import urllib.request
import zipfile
from collections import Counter

from src.config import RAW_DIR
from src.fec.bulk import USER_AGENT
from src.fec.transform import to_money

# The linkage file has no header row. Column order is from the FEC's header file.
CCL_COLUMNS = ["CAND_ID", "CAND_ELECTION_YR", "FEC_ELECTION_YR", "CMTE_ID", "CMTE_TP", "CMTE_DSGN", "LINKAGE_ID"]

# Report types a House campaign files in an election year that can end on or
# before the pre-general cutoff: quarterlies, pre-election reports (primary,
# runoff, special, convention, general), post-special and post-runoff
# reports, and terminations. The 30G (post-general) always ends after the
# cutoff, so it is never requested. House campaigns don't file monthly.
ELECTION_YEAR_TYPES = ["12G", "Q3", "Q2", "Q1", "12P", "12R", "12S", "12C", "30S", "30R", "TER"]

# external_contributions = the first three fields minus the last three, the
# same definition as the 2026 bulk file (individuals, PACs, and party, net of
# refunds). All are cycle-to-date (see the module docstring).
EXTERNAL_ADDED = [
    "total_individual_contributions_ytd",
    "other_political_committee_contributions_ytd",
    "political_party_committee_contributions_ytd",
]
EXTERNAL_SUBTRACTED = [
    "refunded_individual_contributions_ytd",
    "refunded_other_political_committee_contributions_ytd",
    "refunded_political_party_committee_contributions_ytd",
]
# Candidate loans count as self-funding even if repaid, as in src/fec/bulk.py
SELF_FUNDING_FIELDS = ["candidate_contribution_ytd", "loans_made_by_candidate_ytd"]

# Identifying fields kept from each API record, alongside the money fields
REPORT_FIELDS = [
    "committee_id", "report_type", "report_year", "receipt_date", "file_number",
    "coverage_start_date", "coverage_end_date",
] + EXTERNAL_ADDED + EXTERNAL_SUBTRACTED + SELF_FUNDING_FIELDS


def download_ccl(cycle):
    """Download the candidate-committee linkage file and return its text.

    The zip is saved to data/raw/fec/ so the exact file behind a load can be
    checked later.

    Parameters
    ----------
    cycle : int
        Election cycle, e.g. 2024.

    Returns
    -------
    str
        Contents of the pipe-delimited text file inside the zip.
    """
    name = f"ccl{str(cycle)[-2:]}"
    out_dir = RAW_DIR / "fec"
    out_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://www.fec.gov/files/bulk-downloads/{cycle}/{name}.zip"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    # fec.gov answers with a redirect to its file storage, which urllib follows
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    (out_dir / f"{name}.zip").write_bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        # Unlike webl26.zip, the text file inside is just "ccl.txt" for every cycle
        return archive.read("ccl.txt").decode("latin-1")


def principal_committees(ccl_text):
    """Map each candidate to their principal campaign committees.

    Parameters
    ----------
    ccl_text : str
        Contents of the ccl.txt file inside ccl{yy}.zip.

    Returns
    -------
    dict of str to list of str
        Candidate ID to sorted committee IDs. Only principal committees
        (CMTE_DSGN "P") are kept.
    """
    committees = {}
    for line in ccl_text.splitlines():
        if not line:
            continue
        rec = dict(zip(CCL_COLUMNS, line.split("|")))
        if rec["CMTE_DSGN"] != "P":
            continue
        # The same link often appears twice, once per candidate election
        # year, so a set keeps a committee's money from being counted twice
        committees.setdefault(rec["CAND_ID"], set()).add(rec["CMTE_ID"])
    return {candidate: sorted(ids) for candidate, ids in committees.items()}


def _sum_fields(rec, fields):
    """Add up money fields from one report, treating missing values as 0."""
    return sum(to_money(rec.get(field)) or 0.0 for field in fields)


def report_external(rec):
    """Cycle-to-date money raised from other people on one report.

    Parameters
    ----------
    rec : dict
        One /reports/house-senate/ record. Money values arrive as text or float.

    Returns
    -------
    float
    """
    return _sum_fields(rec, EXTERNAL_ADDED) - _sum_fields(rec, EXTERNAL_SUBTRACTED)


def report_self_funding(rec):
    """Cycle-to-date candidate contributions plus candidate loans on one report.

    Parameters
    ----------
    rec : dict
        One /reports/house-senate/ record.

    Returns
    -------
    float
    """
    return _sum_fields(rec, SELF_FUNDING_FIELDS)


def campaign_money(reports):
    """Add up external money and self-funding over a set of reports.

    Parameters
    ----------
    reports : list of dict
        One chosen report per committee. Each holds that committee's
        cycle-to-date totals, so they can be added without overlap.

    Returns
    -------
    dict
        `external_contributions` and `candidate_self_funding`.
    """
    return {
        "external_contributions": sum(report_external(rec) for rec in reports),
        "candidate_self_funding": sum(report_self_funding(rec) for rec in reports),
    }


def _filing_order(rec):
    """Sort key for which of two filings came later."""
    return (rec["receipt_date"], rec["file_number"])


def latest_versions(reports):
    """Keep only the most recent filing of each report.

    The query already asks the API for current versions only. This is a
    second check, so an original and its amendment can never both count.

    Parameters
    ----------
    reports : list of dict

    Returns
    -------
    list of dict
        One report per committee, report type, and report year: the one
        received last (ties go to the higher file number).
    """
    latest = {}
    for rec in reports:
        key = (rec["committee_id"], rec["report_type"], rec["report_year"])
        if key not in latest or _filing_order(rec) > _filing_order(latest[key]):
            latest[key] = rec
    return list(latest.values())


def _end_date(rec):
    """A report's coverage end date as YYYY-MM-DD (the API adds a time)."""
    return rec["coverage_end_date"][:10]


def pre_general_cutoff(reports):
    """Find the standard pre-general (12G) coverage end date for a cycle.

    Parameters
    ----------
    reports : list of dict
        Election-year reports, one version each.

    Returns
    -------
    str
        The most common 12G coverage end date, YYYY-MM-DD.

    Raises
    ------
    ValueError
        If there are no 12G reports.
    """
    ends = Counter(_end_date(rec) for rec in reports if rec["report_type"] == "12G")
    if not ends:
        raise ValueError("No 12G reports, so the pre-general cutoff can't be found")
    return ends.most_common(1)[0][0]


def _is_later(rec, current):
    """True if `rec` ends later than `current`, or ends the same day and was filed later."""
    return (_end_date(rec), _filing_order(rec)) > (_end_date(current), _filing_order(current))


def latest_before_cutoff(reports, cutoff):
    """Pick each committee's latest report that ends on or before the cutoff.

    Usually that is the 12G. A campaign that didn't file one keeps its latest
    earlier report (often the Q3), the same way the 2026 data keeps a quiet
    campaign's last report instead of treating it as $0.

    Parameters
    ----------
    reports : list of dict
        Election-year reports, one version each.
    cutoff : str
        YYYY-MM-DD, from `pre_general_cutoff`.

    Returns
    -------
    chosen : dict of str to dict
        Committee ID to its chosen report.
    excluded : list of dict
        Reports that end after the cutoff. These include money raised after
        the standard pre-general date, and 12Gs with odd coverage (one real
        2024 12G covers Aug 9 to Nov 5).
    """
    chosen, excluded = {}, []
    for rec in reports:
        if _end_date(rec) > cutoff:
            excluded.append(rec)
            continue
        current = chosen.get(rec["committee_id"])
        if current is None or _is_later(rec, current):
            chosen[rec["committee_id"]] = rec
    return chosen, excluded


def fetch_reports(client, cycle, committee_ids=None):
    """Download a cycle's House reports that can count toward pre-general money.

    Only election-year reports are needed, because each one already holds
    cycle-to-date totals.

    Parameters
    ----------
    client : FecClient
    cycle : int
        Election year, e.g. 2024.
    committee_ids : list of str, optional
        Only these committees' reports (the supplemental path). By default
        every House committee's reports are downloaded.

    Returns
    -------
    list of dict
    """
    params = {
        "cycle": cycle,
        "committee_type": "H",
        "report_type": ELECTION_YEAR_TYPES,
        # Current versions only. Checked against the 2024 12Gs: most_recent=true
        # gives the same filings but drops 8 paper filings that have no
        # most_recent value, so is_amended=false is the safer filter.
        "is_amended": "false",
        # The API ignores report_year, so this is how odd-year reports are
        # skipped on the server. Election-year reports can't be filed earlier.
        "min_receipt_date": f"{cycle}-01-01",
        # Page-number pagination is only stable with a unique sort key. Without
        # one, pages overlap and some filings are never returned.
        "sort": "beginning_image_number",
    }
    if committee_ids is not None:
        params["committee_id"] = committee_ids
    # Each record has about 100 fields and a cycle has over 13,000 reports, so
    # only the fields the loader uses are kept as pages stream in
    return [
        {field: rec.get(field) for field in REPORT_FIELDS}
        for rec in client.iter_results("/reports/house-senate/", params)
    ]


def _print_exclusions(cycle, cutoff, excluded):
    """Report how many reports ended after the cutoff, listing any 12Gs."""
    by_type = dict(Counter(rec["report_type"] for rec in excluded))
    print(f"{cycle}: cutoff {cutoff}, {len(excluded)} reports excluded for ending after it {by_type}")
    for rec in excluded:
        if rec["report_type"] == "12G":
            start = rec["coverage_start_date"][:10]
            print(f"  12G {rec['committee_id']} covers {start} to {_end_date(rec)}")


def _candidate_row(cycle, candidate_id, committee_ids, chosen):
    """Build one `history_money` row, or None if no committee has a qualifying report."""
    used = [cid for cid in committee_ids if cid in chosen]
    if not used:
        return None
    reports = [chosen[cid] for cid in used]
    return {
        "cycle": cycle,
        "candidate_id": candidate_id,
        "committee_id": ",".join(used),
        **campaign_money(reports),
        "coverage_end_date": max(_end_date(chosen[cid]) for cid in used),
    }


def pre_general_money(client, cycle, ccl_text):
    """Build `history_money` rows: each House campaign's money as of its pre-general report.

    Money is the cycle-to-date figures on each principal committee's report
    chosen by `latest_before_cutoff`, summed over the candidate's committees.

    Parameters
    ----------
    client : FecClient
    cycle : int
        Election year, e.g. 2024.
    ccl_text : str
        Contents of that cycle's candidate-committee linkage file.

    Returns
    -------
    list of dict
        One row per House candidate with at least one qualifying report.
    """
    reports = latest_versions(fetch_reports(client, cycle))
    # Amendments to odd-year reports filed in the election year still come
    # back from the query, so keep only reports for the election year itself
    election_year = [rec for rec in reports if rec["report_year"] == cycle]

    cutoff = pre_general_cutoff(election_year)
    chosen, excluded = latest_before_cutoff(election_year, cutoff)
    _print_exclusions(cycle, cutoff, excluded)

    rows = []
    for candidate_id, committee_ids in principal_committees(ccl_text).items():
        # FEC candidate IDs start with the office: H = House
        if not candidate_id.startswith("H"):
            continue
        row = _candidate_row(cycle, candidate_id, committee_ids, chosen)
        if row is not None:
            rows.append(row)
    return rows


# Supplemental path: candidates the linkage file leaves out

def api_principal_committees(client, candidate_id, cycle):
    """A candidate's principal committees for one cycle, from the OpenFEC API.

    Parameters
    ----------
    client : FecClient
    candidate_id : str
    cycle : int

    Returns
    -------
    list of str
        Sorted committee IDs (CMTE_DSGN "P").
    """
    params = {"cycle": cycle, "designation": "P"}
    return sorted({rec["committee_id"] for rec in client.iter_results(f"/candidate/{candidate_id}/committees/", params)})


def api_pre_general_cutoff(client, cycle):
    """The cycle's standard 12G coverage end date, from one page of 12G reports.

    Same rule as `pre_general_cutoff` (the most common 12G end date), so the
    supplemental rows use the cutoff the full load used.

    Parameters
    ----------
    client : FecClient
    cycle : int

    Returns
    -------
    str
        YYYY-MM-DD.
    """
    params = {
        "cycle": cycle, "committee_type": "H", "report_type": "12G",
        "is_amended": "false", "min_receipt_date": f"{cycle}-01-01",
        "sort": "beginning_image_number",
    }
    reports = list(client.iter_results("/reports/house-senate/", params, max_pages=1))
    return pre_general_cutoff([rec for rec in reports if rec["report_year"] == cycle])


def supplemental_money(client, cycle, candidate_committees, cutoff):
    """`history_money` rows for candidates the ccl{yy} linkage file leaves out.

    The bulk linkage file drops some candidates whose FEC record has rolled
    forward to a later cycle (Glenn Ivey, MD-04, lists 2012, 2016, and 2026),
    so `pre_general_money` never sees their committees. This runs the same
    report rules for just the candidates and committees passed in. It doesn't
    change the rows `pre_general_money` builds for anyone else.

    Parameters
    ----------
    client : FecClient
    cycle : int
    candidate_committees : dict of str to list of str
        Candidate ID to principal committee IDs (from `api_principal_committees`).
    cutoff : str
        The cycle's pre-general cutoff, YYYY-MM-DD (from `api_pre_general_cutoff`).

    Returns
    -------
    list of dict
        One row per candidate with at least one qualifying report.
    """
    committee_ids = sorted({cid for ids in candidate_committees.values() for cid in ids})
    if not committee_ids:
        return []
    reports = latest_versions(fetch_reports(client, cycle, committee_ids))
    election_year = [rec for rec in reports if rec["report_year"] == cycle]
    chosen, _ = latest_before_cutoff(election_year, cutoff)
    rows = []
    for candidate_id, ids in candidate_committees.items():
        row = _candidate_row(cycle, candidate_id, sorted(ids), chosen)
        if row is not None:
            rows.append(row)
    return rows
