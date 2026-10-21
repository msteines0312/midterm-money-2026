"""Turn OpenFEC records into rows for the database tables.

Each function takes one record as the API returns it and gives back a dict
whose keys match the table's columns. Field names were checked against real
responses saved in tests/fixtures/.
"""


def race_id(state, district):
    """Build the district key used to join FEC data to Cook ratings.

    Parameters
    ----------
    state : str
        Postal code, e.g. "CA".
    district : str or None
        District number as text. The FEC uses "00" for at-large seats, but
        "0" and missing values show up too.

    Returns
    -------
    str
        e.g. "CA-07", or "AK-00" for an at-large seat.
    """
    return f"{state}-{int(district or 0):02d}"


def to_money(value):
    """Convert an API money value to a float, keeping missing values as None.

    Some fields (cash_on_hand_end_period) come back as strings like "0.04".
    None stays None because "not reported" is different from $0.

    Parameters
    ----------
    value : str, int, float, or None

    Returns
    -------
    float or None
    """
    return None if value is None else float(value)


def candidate_row(rec):
    """Map a /candidates/ record to a `candidates` row.

    Parameters
    ----------
    rec : dict

    Returns
    -------
    dict
    """
    return {
        "candidate_id": rec["candidate_id"],
        "name": rec.get("name"),
        "party": rec.get("party"),
        "state": rec.get("state"),
        "district": rec.get("district"),
        "race_id": race_id(rec.get("state"), rec.get("district")),
        "incumbent_challenge": rec.get("incumbent_challenge"),
        "primary_result": None,  # not in FEC data, added in the endorsements phase
    }


def committee_row(rec):
    """Map a /committees/ record to a `committees` row.

    Parameters
    ----------
    rec : dict

    Returns
    -------
    dict
    """
    return {
        "committee_id": rec["committee_id"],
        "name": rec.get("name"),
        "committee_type": rec.get("committee_type"),
        "designation": rec.get("designation"),
    }


def totals_row(rec, pulled_at):
    """Map a /candidates/totals/ record to a `candidate_totals` row.

    Parameters
    ----------
    rec : dict
    pulled_at : str
        ISO date of this pull.

    Returns
    -------
    dict
    """
    return {
        "candidate_id": rec["candidate_id"],
        "pulled_at": pulled_at,
        "receipts": to_money(rec.get("receipts")),
        "disbursements": to_money(rec.get("disbursements")),
        "cash_on_hand": to_money(rec.get("cash_on_hand_end_period")),
        # Itemized means donors who gave more than $200 this cycle. The endpoint
        # has no total for smaller donors, so this is not all individual money.
        "individual_itemized_contributions": to_money(rec.get("individual_itemized_contributions")),
        "pac_contributions": to_money(rec.get("other_political_committee_contributions")),
    }


def outside_spending_row(rec, pulled_at):
    """Map a /schedules/schedule_e/by_candidate/ record to an `outside_spending` row.

    Parameters
    ----------
    rec : dict
    pulled_at : str
        ISO date of this pull.

    Returns
    -------
    dict
    """
    return {
        "committee_id": rec["committee_id"],
        "candidate_id": rec["candidate_id"],
        "support_oppose": rec.get("support_oppose_indicator"),
        "pulled_at": pulled_at,
        "total": to_money(rec.get("total")),
        "count": rec.get("count"),
    }
