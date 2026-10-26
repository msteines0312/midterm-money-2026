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
"""

# Super PAC committee types: O (independent expenditure only), V and W
# (hybrid PACs with non-contribution accounts)
SUPER_PAC_TYPES = ["O", "V", "W"]

SCHEDULE_A_PATH = "/schedules/schedule_a/"


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
