"""Big contributions to super PACs in 2026, from FEC Schedule A.

Schedule A lists every contribution a committee received. These functions
pull the ones given to super PACs (committee types O, V and W) so later
steps can total what billionaires gave. PAC committee totals come from a
second endpoint and give the denominator for "what share of the money".

Two things about the data that matter when adding it up:

- Memo rows (memo_code "X") repeat a transaction that is already counted on
  another row, such as a joint fundraising split, so they are left out of totals.
- Refunds are negative amounts. They reduce what a donor gave.

`is_individual=true` does not filter out organizations in this endpoint, so
each row keeps its own `entity_type` (IND, ORG, PAC, COM, ...) instead.

One more thing about timing: the processed Schedule A lags the newest
filings. Reports filed on Oct 15 and Oct 22, 2026 were in the committee
totals but had no itemized rows yet (America PAC's two reports hold about
$166M). The raw e-filing endpoint has those rows, so the e-file functions at
the bottom fill the gap. They are raw, so amendments and rows that Schedule A
later processes have to be handled (see `drop_superseded_efile` and
`drop_already_processed`).
"""

import re
from collections import Counter

# Super PAC committee types: O (independent expenditure only), V and W
# (hybrid PACs with non-contribution accounts)
SUPER_PAC_TYPES = ["O", "V", "W"]

SCHEDULE_A_PATH = "/schedules/schedule_a/"
EFILE_PATH = "/schedules/schedule_a/efile/"


def _schedule_a_params(cycle, **filters):
    """Query parameters shared by every Schedule A pull."""
    return {
        "two_year_transaction_period": cycle,
        "recipient_committee_type": SUPER_PAC_TYPES,
        "sort": "-contribution_receipt_amount",
        "per_page": 100,
        **filters,
    }


def contribution_row(rec, pulled_at):
    """Turn one Schedule A record into a `donor_contributions` row.

    Parameters
    ----------
    rec : dict
        One /schedules/schedule_a/ record.
    pulled_at : str
        Date of the pull, YYYY-MM-DD.

    Returns
    -------
    dict
        The ~100 fields of the record are cut to the ones the analysis uses.
    """
    return {
        "sub_id": rec["sub_id"],
        "cycle": rec["two_year_transaction_period"],
        "committee_id": rec["committee_id"],
        "contributor_name": rec["contributor_name"],
        "entity_type": rec["entity_type"],
        "amount": rec["contribution_receipt_amount"],
        "receipt_date": rec["contribution_receipt_date"],
        "memo_code": rec["memo_code"],
        "pulled_at": pulled_at,
    }


def large_contributions(client, cycle, min_amount):
    """Every contribution of at least `min_amount` to a super PAC in a cycle.

    Parameters
    ----------
    client : FecClient
    cycle : int
        Two-year transaction period, e.g. 2026.
    min_amount : float
        Smallest contribution to include, in dollars.

    Returns
    -------
    list of dict
        Raw Schedule A records, largest first.
    """
    params = _schedule_a_params(cycle, min_amount=min_amount)
    return list(client.iter_keyset(SCHEDULE_A_PATH, params))


def contributions_by_name(client, cycle, name):
    """Every contribution of any size from one contributor name to a super PAC.

    Parameters
    ----------
    client : FecClient
    cycle : int
    name : str
        Contributor name as the FEC files it, usually "LAST, FIRST".

    Returns
    -------
    list of dict
        Raw Schedule A records. Refunds are included as negative amounts.
    """
    params = _schedule_a_params(cycle, contributor_name=name)
    return list(client.iter_keyset(SCHEDULE_A_PATH, params))


def contributions_to_committee(client, cycle, committee_id):
    """Every contribution of any size received by one committee.

    Parameters
    ----------
    client : FecClient
    cycle : int
    committee_id : str

    Returns
    -------
    list of dict
        Raw Schedule A records.
    """
    params = _schedule_a_params(cycle, committee_id=committee_id)
    return list(client.iter_keyset(SCHEDULE_A_PATH, params))


def pac_totals_rows(client, cycle, committee_ids, pulled_at):
    """Build `pac_totals` rows: each committee's receipts and independent spending.

    Parameters
    ----------
    client : FecClient
    cycle : int
    committee_ids : list of str
    pulled_at : str
        Date of the pull, YYYY-MM-DD.

    Returns
    -------
    list of dict
        One row per committee that has totals for the cycle. A committee
        with none is skipped.
    """
    rows = []
    for committee_id in committee_ids:
        body = client.get(f"/committee/{committee_id}/totals/", {"cycle": cycle})
        for rec in body.get("results", [])[:1]:
            rows.append({
                "committee_id": committee_id,
                "cycle": cycle,
                "receipts": rec["receipts"],
                "independent_expenditures": rec["independent_expenditures"],
                # The API adds a midnight time to this date
                "coverage_end_date": (rec["coverage_end_date"] or "")[:10] or None,
                "pulled_at": pulled_at,
            })
    return rows


def net_amount(rows):
    """Total given across contribution rows, after refunds, without memo rows.

    Parameters
    ----------
    rows : list of dict
        `donor_contributions` rows (or anything with `amount` and `memo_code`).

    Returns
    -------
    float
    """
    return sum(row["amount"] for row in rows if row["memo_code"] != "X")


def clean_efile_name(name):
    """Make a raw e-filing name match the spelling Schedule A uses.

    Raw names keep the filer's typing: a doubled space after the comma
    ("MUSK,  ELON"), a trailing comma ("ACME INC,"), and often mixed case
    ("Yass, Jeff") where Schedule A is uppercase. Without the case fix, a
    gift filed in both places would not be recognized as the same one.

    Parameters
    ----------
    name : str or None

    Returns
    -------
    str
    """
    return re.sub(r"\s+", " ", (name or "")).strip().rstrip(",").strip().upper()


def efile_contributions(client, committee_id, min_date):
    """Raw e-filed contributions to one committee since a date.

    Parameters
    ----------
    client : FecClient
    committee_id : str
    min_date : str
        YYYY-MM-DD. Earlier rows are left to the processed Schedule A.

    Returns
    -------
    list of dict
        Raw records, which may include amended versions of a transaction.
    """
    params = {"committee_id": committee_id, "min_date": min_date}
    return list(client.iter_results(EFILE_PATH, params))


def drop_superseded_efile(records):
    """Keep the latest version of each transaction.

    An amended filing repeats its transactions under a higher file number.
    Counting both would double the gift.

    Parameters
    ----------
    records : list of dict
        Raw e-filing records.

    Returns
    -------
    list of dict
    """
    latest = {}
    for rec in records:
        key = (rec["committee_id"], rec["transaction_id"])
        if key not in latest or rec["file_number"] > latest[key]["file_number"]:
            latest[key] = rec
    return list(latest.values())


def efile_contribution_row(rec, pulled_at):
    """Turn one raw e-filing record into a `donor_contributions` row.

    The row gets a made-up `sub_id` (`efile-<file number>-<transaction id>`)
    because raw records have none, and a name cleaned to the Schedule A style.

    Parameters
    ----------
    rec : dict
        One /schedules/schedule_a/efile/ record.
    pulled_at : str
        Date of the pull, YYYY-MM-DD.

    Returns
    -------
    dict
    """
    year = int(rec["contribution_receipt_date"][:4])
    return {
        "sub_id": f"efile-{rec['file_number']}-{rec['transaction_id']}",
        # A two-year cycle is named for its even year
        "cycle": year + year % 2,
        "committee_id": rec["committee_id"],
        "contributor_name": clean_efile_name(rec["contributor_name"]),
        "entity_type": rec["entity_type"],
        "amount": rec["contribution_receipt_amount"],
        "receipt_date": rec["contribution_receipt_date"],
        "memo_code": rec["memo_code"],
        "pulled_at": pulled_at,
    }


def drop_already_processed(rows, processed_counts):
    """Remove e-filed rows that the processed Schedule A already has.

    Once the API processes a filing, its gifts show up in Schedule A under a
    different ID. Counting the raw copy as well would double them. Names are
    not used to match, because the two sources spell them differently
    ("YASS, JEFF MR." against "YASS, MR. JEFF"). A raw row is dropped when a
    processed row has the same committee, date, amount, and memo code. Each
    processed row cancels only one raw row, so two real gifts of the same size
    on the same day are not merged into one.

    Parameters
    ----------
    rows : list of dict
        Output of `efile_contribution_row`.
    processed_counts : collections.Counter
        For rows already in `donor_contributions` from Schedule A, how many
        share each (committee_id, receipt_date, amount, memo_code).

    Returns
    -------
    list of dict
    """
    remaining = Counter(processed_counts)
    kept = []
    for row in rows:
        key = (row["committee_id"], row["receipt_date"], row["amount"], row["memo_code"])
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            kept.append(row)
    return kept
