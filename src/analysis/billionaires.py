"""Billionaire giving to super PACs, and which PACs they fund.

Every function takes an open database connection and returns a DataFrame.
Donors come from `donor_contributions` and PAC receipts from `pac_totals`,
both loaded by scripts/load_donors.py. Who counts as a billionaire, and which
organizations belong to them, comes from the hand-sourced CSVs read by
src/manual.py. Nothing here decides who a donor is. It only adds up what the
CSVs say.

Two rules keep the sums honest:
- Memo rows (`memo_code` X) repeat money that another row already reports,
  so they are left out. Refunds are negative amounts and are netted.
- A PAC is only called billionaire-backed if the rows we loaded add up to
  what the PAC reports raising. If they don't, it is reported as
  unreconciled instead.
"""

import pandas as pd

from src.fec.independent_expenditures import (
    drop_superseded,
    parse_independent_expenditures,
    read_saved_independent_expenditures,
    saved_file_path,
)
from src.fec.transform import to_money
from src.predict.simple import _last_name_matches

# Share of a PAC's receipts from one billionaire that makes it billionaire-backed
BACKED_THRESHOLD = 0.5
# Shares from here up to the threshold are flagged so their entities get checked
NEAR_FLOOR = 0.35
# How far itemized rows may differ from reported receipts, as a fraction
RECONCILE_TOLERANCE = 0.05

GIVING_COLUMNS = ["person", "committee_id", "direct", "via_entities", "total"]

# Net contributions per donor name and committee. COALESCE because the FEC
# leaves memo_code empty on ordinary rows, and NULL <> 'X' is not true in SQL.
NET_BY_NAME = """
    SELECT UPPER(contributor_name) AS name, committee_id, SUM(amount) AS amount
    FROM donor_contributions
    WHERE cycle = :cycle AND COALESCE(memo_code, '') <> 'X'
    GROUP BY UPPER(contributor_name), committee_id
"""

# House spending by super PACs and hybrids, summed by committee, party, and side.
# The type filter matches tech_money.py: the outside_spending table also holds
# party committees and one bogus individual filer that must never enter a total.
HOUSE_SPENDING = """
    SELECT s.committee_id, s.party, s.support_oppose, SUM(s.total) AS total
    FROM outside_spending AS s
    JOIN committees AS c ON c.committee_id = s.committee_id
    WHERE s.pulled_at = :pulled_at AND c.committee_type IN ('O', 'V', 'W')
    GROUP BY s.committee_id, s.party, s.support_oppose
"""

# Primary and runoff spending by super PACs and hybrids. candidate_key already
# separates candidates (the FEC ID, or race plus last name when the filing has
# none), so the descriptive columns can be taken with MAX.
PRIMARY_SPENDING = """
    SELECT s.committee_id, MAX(s.race_id) AS race_id, s.candidate_key,
           MAX(s.candidate_id) AS candidate_id, MAX(s.candidate_name) AS candidate_name,
           MAX(s.party) AS party, s.support_oppose, SUM(s.total) AS total
    FROM outside_spending AS s
    JOIN committees AS c ON c.committee_id = s.committee_id
    WHERE s.pulled_at = :pulled_at AND c.committee_type IN ('O', 'V', 'W')
      AND s.election_type IN ('P', 'R')
    GROUP BY s.committee_id, s.candidate_key, s.support_oppose
    HAVING SUM(s.total) >= :min_spend
"""

# The latest pull of each committee's cycle totals
LATEST_TOTALS = """
    SELECT t.committee_id, t.receipts
    FROM pac_totals AS t
    JOIN (
        SELECT committee_id, MAX(pulled_at) AS pulled_at
        FROM pac_totals WHERE cycle = :cycle GROUP BY committee_id
    ) AS latest
      ON latest.committee_id = t.committee_id AND latest.pulled_at = t.pulled_at
    WHERE t.cycle = :cycle
"""


def _name_to_person(billionaires):
    """Map each upper-cased FEC spelling to the one person it belongs to.

    Raises
    ------
    ValueError
        If a spelling is listed under two different people, which would count
        the same gifts for both.
    """
    owner = {}
    for row in billionaires:
        for variant in row["contributor_name_variants"]:
            key = variant.upper()
            if owner.get(key, row["person"]) != row["person"]:
                raise ValueError(f"{variant} is listed for both {owner[key]} and {row['person']}")
            owner[key] = row["person"]
    return owner


def _entity_owners(entities, people):
    """Map each upper-cased entity name to (person, share) pairs for listed people."""
    owners = {}
    for row in entities:
        if row["person"] in people:
            owners.setdefault(row["entity_name"].upper(), []).append((row["person"], row["share"]))
    return owners


def household_giving(conn, billionaires, entities, cycle=2026):
    """Add up each billionaire household's giving to each PAC.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database with `donor_contributions` loaded.
    billionaires : list of dict
        Output of `src.manual.load_billionaires`.
    entities : list of dict
        Output of `src.manual.load_donor_entities`. Each row's `share` scales
        how much of that entity's giving belongs to the person.
    cycle : int, optional
        Election cycle to count.

    Returns
    -------
    pandas.DataFrame
        One row per person and committee with columns `person`,
        `committee_id`, `direct` (gifts under the person's or household's own
        names), `via_entities` (their share of sourced entity gifts), and
        `total`. Memo rows are excluded and refunds are netted.
    """
    name_owner = _name_to_person(billionaires)
    entity_owners = _entity_owners(entities, {row["person"] for row in billionaires})

    net = pd.read_sql_query(NET_BY_NAME, conn, params={"cycle": cycle})
    records = []
    for name, committee_id, amount in net.itertuples(index=False):
        if name in name_owner:
            records.append((name_owner[name], committee_id, amount, 0.0))
        for person, share in entity_owners.get(name, []):
            records.append((person, committee_id, 0.0, amount * share))

    if not records:
        return pd.DataFrame(columns=GIVING_COLUMNS)
    giving = pd.DataFrame(records, columns=["person", "committee_id", "direct", "via_entities"])
    giving = giving.groupby(["person", "committee_id"], as_index=False).sum()
    giving["total"] = giving["direct"] + giving["via_entities"]
    return giving[GIVING_COLUMNS]


def reconcile(conn, committee_ids, cycle=2026, tolerance=RECONCILE_TOLERANCE):
    """Compare the contributions we loaded with what each PAC reports raising.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database with `donor_contributions` and `pac_totals` loaded.
    committee_ids : list of str
        PACs to check.
    cycle : int, optional
        Election cycle to count.
    tolerance : float, optional
        Largest allowed gap, as a fraction of reported receipts.

    Returns
    -------
    pandas.DataFrame
        Columns `committee_id`, `itemized` (net of memo rows and refunds),
        `receipts` (the PAC's own cycle total), `diff_pct` (itemized minus
        receipts, over receipts), and `reconciled`. A PAC with no totals has
        a NaN `diff_pct` and is not reconciled.
    """
    net = pd.read_sql_query(NET_BY_NAME, conn, params={"cycle": cycle})
    itemized = net.groupby("committee_id")["amount"].sum()
    receipts = pd.read_sql_query(LATEST_TOTALS, conn, params={"cycle": cycle}).set_index("committee_id")["receipts"]

    table = pd.DataFrame({"committee_id": list(committee_ids)})
    table["itemized"] = table["committee_id"].map(itemized).fillna(0.0)
    table["receipts"] = table["committee_id"].map(receipts)
    # Zero receipts would divide by zero, so treat them like missing totals
    valid_receipts = table["receipts"].where(table["receipts"] > 0)
    table["diff_pct"] = (table["itemized"] - valid_receipts) / valid_receipts
    table["reconciled"] = table["diff_pct"].abs() <= tolerance
    return table


def concentration(giving, conn, cycle=2026):
    """Give each donor's share of each PAC's total receipts.

    Parameters
    ----------
    giving : pandas.DataFrame
        Output of `household_giving`.
    conn : sqlite3.Connection
        Database with `pac_totals` loaded.
    cycle : int, optional
        Election cycle of the totals.

    Returns
    -------
    pandas.DataFrame
        Columns `committee_id`, `person`, `share`, where share is the
        person's `total` over the PAC's receipts. Receipts include transfers
        from other committees, which are not followed. A PAC with no totals
        keeps its row with a NaN share.
    """
    receipts = pd.read_sql_query(LATEST_TOTALS, conn, params={"cycle": cycle}).set_index("committee_id")["receipts"]
    result = giving[["committee_id", "person"]].copy()
    valid_receipts = result["committee_id"].map(receipts).where(lambda values: values > 0)
    result["share"] = giving["total"] / valid_receipts
    return result.reset_index(drop=True)


def billionaire_backed(concentration_df, reconcile_df, threshold=BACKED_THRESHOLD, near_floor=NEAR_FLOOR):
    """Label PACs where one billionaire supplies a large share of receipts.

    There is no joint threshold. Two donors at 30% each do not add up to a
    backed PAC.

    Parameters
    ----------
    concentration_df : pandas.DataFrame
        Output of `concentration`.
    reconcile_df : pandas.DataFrame
        Output of `reconcile`. A PAC missing from it counts as unreconciled.
    threshold : float, optional
        Share at or above which a PAC is billionaire-backed.
    near_floor : float, optional
        Shares from here up to the threshold are flagged `near`.

    Returns
    -------
    pandas.DataFrame
        Columns `committee_id`, `person`, `share`, `status`. Status is
        `backed` (share at or above the threshold and reconciled),
        `unreconciled` (same share, but the loaded rows do not match the
        PAC's totals, so it is never called backed), or `near`. Rows below
        the near floor are dropped.
    """
    merged = concentration_df.merge(reconcile_df[["committee_id", "reconciled"]], on="committee_id", how="left")
    merged["reconciled"] = merged["reconciled"].fillna(False).astype(bool)

    at_threshold = merged["share"] >= threshold
    is_near = (merged["share"] >= near_floor) & ~at_threshold
    merged["status"] = None
    merged.loc[is_near, "status"] = "near"
    merged.loc[at_threshold & ~merged["reconciled"], "status"] = "unreconciled"
    merged.loc[at_threshold & merged["reconciled"], "status"] = "backed"
    flagged = merged[merged["status"].notna()]
    return flagged[["committee_id", "person", "share", "status"]].reset_index(drop=True)


def all_office_expenditures(pulled_at, path=None, check_date=True):
    """Total independent expenditures by each committee, across every office.

    The House table only holds House races, but a PAC's money also goes to
    Senate races and others. Dividing by this total says how much of what a
    PAC spent went to the House.

    Parameters
    ----------
    pulled_at : str
        ISO date of the snapshot. The saved bulk file must belong to it.
    path : pathlib.Path, optional
        Bulk file to read. Defaults to the one the last pull saved.
    check_date : bool, optional
        Refuse a file saved on a different date than `pulled_at`. Turn off
        only for a hand-built test file.

    Returns
    -------
    dict
        Committee ID to total dollars. Amended filings count once.
    """
    if check_date:
        text = read_saved_independent_expenditures(pulled_at, path)
    else:
        text = (path or saved_file_path()).read_bytes().decode("latin-1")
    totals = {}
    for row in drop_superseded(parse_independent_expenditures(text)):
        # A row with no amount has nothing to add
        if row["exp_amo"] is not None:
            totals[row["spe_id"]] = totals.get(row["spe_id"], 0.0) + to_money(row["exp_amo"])
    return totals


def _attributed_spending(giving, conn, pulled_at, all_office_ie, cycle):
    """Each person's slice of each PAC's House and all-office spending.

    A person's slice is their `total` over the PAC's receipts, times the
    PAC's spending. One adjustment: if a PAC's all-office spending is more
    than its reported receipts (receipts stop at the last report, spending is
    snapshotted later), every spending figure is scaled down to the receipts.
    That keeps the donor from being credited with more than they gave, so
    'other or unspent' can't go negative. A PAC with no committee totals
    gets no attribution.

    Returns
    -------
    pandas.DataFrame
        One row per person and committee with `total`, `all_office` (their
        slice of all-office spending), `house_dollars`, and `dem_helping` and
        `rep_helping`, all already multiplied by the person's slice.
    """
    receipts = pd.read_sql_query(LATEST_TOTALS, conn, params={"cycle": cycle}).set_index("committee_id")["receipts"]
    house = pd.read_sql_query(HOUSE_SPENDING, conn, params={"pulled_at": pulled_at})
    if all_office_ie is None:
        all_office_ie = all_office_expenditures(pulled_at)

    table = giving[["person", "committee_id", "total"]].copy()
    table["receipts"] = table["committee_id"].map(receipts).where(lambda values: values > 0)
    table["share"] = (table["total"] / table["receipts"]).fillna(0.0)
    table["pac_spent"] = table["committee_id"].map(all_office_ie).fillna(0.0)
    # Fraction of the spending that the receipts can account for
    scale = (table["receipts"] / table["pac_spent"]).clip(upper=1.0).where(table["pac_spent"] > 0, 1.0)
    table["slice"] = (table["share"] * scale).fillna(0.0)
    table["all_office"] = table["slice"] * table["pac_spent"]

    house_total = house.groupby("committee_id")["total"].sum()
    table["house_dollars"] = table["committee_id"].map(house_total).fillna(0.0) * table["slice"]

    # Supporting a party's candidate or opposing the other party helps that party.
    # Other parties and unresolved parties map to NaN and are dropped.
    house["side"] = house["party"].map({"DEM": "dem", "DFL": "dem", "REP": "rep"})
    house = house.dropna(subset=["side"])
    helps_dem = (house["side"] == "dem") == (house["support_oppose"] == "S")
    house["helps"] = helps_dem.map({True: "dem_helping", False: "rep_helping"})
    helping = house.groupby(["committee_id", "helps"])["total"].sum().unstack(fill_value=0.0)
    for column in ("dem_helping", "rep_helping"):
        by_committee = helping[column] if column in helping else pd.Series(dtype=float)
        table[column] = table["committee_id"].map(by_committee).fillna(0.0) * table["slice"]
    return table


def house_share(giving, conn, pulled_at="2026-10-24", all_office_ie=None, cycle=2026):
    """Estimate how much of each billionaire's giving reached House races.

    Parameters
    ----------
    giving : pandas.DataFrame
        Output of `household_giving`.
    conn : sqlite3.Connection
        Database with `outside_spending`, `committees`, and `pac_totals`.
    pulled_at : str, optional
        Date of the outside spending snapshot.
    all_office_ie : dict, optional
        Committee ID to all-office spending. Defaults to the saved bulk file.
    cycle : int, optional
        Election cycle of the receipts.

    Returns
    -------
    pandas.DataFrame
        Columns `person`, `total_giving`, `house_dollars` (their slice of the
        PAC's House spending, support and oppose, primary and general),
        `house_pct` (house_dollars over total_giving), and `other_or_unspent`
        (total_giving minus their slice of the PAC's all-office spending:
        transfers, contributions, and cash not yet spent).
    """
    table = _attributed_spending(giving, conn, pulled_at, all_office_ie, cycle)
    people = table.groupby("person", as_index=False).agg(
        total_giving=("total", "sum"), house_dollars=("house_dollars", "sum"), spent=("all_office", "sum")
    )
    people["house_pct"] = (people["house_dollars"] / people["total_giving"]).where(people["total_giving"] > 0)
    people["other_or_unspent"] = people["total_giving"] - people["spent"]
    return people[["person", "total_giving", "house_dollars", "house_pct", "other_or_unspent"]]


def lean(giving, conn, pulled_at="2026-10-24", all_office_ie=None, cycle=2026):
    """Work out which party each billionaire's House spending helped.

    Supporting a Democrat or opposing a Republican counts as helping
    Democrats, and the reverse helps Republicans. Spending on candidates of
    other parties, or with no resolved party, counts for neither. The result
    is computed from the spending, never assigned by hand.

    Parameters
    ----------
    giving, conn, pulled_at, all_office_ie, cycle
        As in `house_share`.

    Returns
    -------
    pandas.DataFrame
        Columns `person`, `dem_helping`, `rep_helping` (dollars, weighted by
        the person's slice of each PAC), and `dem_share`, the Democratic
        fraction of the two. NaN when neither side got House spending.
    """
    table = _attributed_spending(giving, conn, pulled_at, all_office_ie, cycle)
    people = table.groupby("person", as_index=False)[["dem_helping", "rep_helping"]].sum()
    both = people["dem_helping"] + people["rep_helping"]
    people["dem_share"] = (people["dem_helping"] / both).where(both > 0)
    return people


def primary_support(conn, backed_pacs, pulled_at="2026-10-24", min_spend=10_000):
    """List the primary candidates that billionaire-backed PACs spent on.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database with `outside_spending` and `committees`.
    backed_pacs : pandas.DataFrame
        PACs to look at, with `committee_id` and `person`. Pass only rows
        whose status from `billionaire_backed` is `backed`.
    pulled_at : str, optional
        Date of the outside spending snapshot.
    min_spend : float, optional
        Smallest primary and runoff spending on one candidate, support or
        oppose, that counts. Small buys are not a PAC picking a side.

    Returns
    -------
    pandas.DataFrame
        One row per PAC and candidate with `committee_id`, `person`,
        `race_id`, `candidate_key`, `candidate_id`, `candidate_name`,
        `party`, `support_oppose`, and `total`.
    """
    spending = pd.read_sql_query(PRIMARY_SPENDING, conn, params={"pulled_at": pulled_at, "min_spend": min_spend})
    result = backed_pacs[["committee_id", "person"]].merge(spending, on="committee_id")
    columns = ["committee_id", "person", "race_id", "candidate_key", "candidate_id",
               "candidate_name", "party", "support_oppose", "total"]
    return result[columns].sort_values(["committee_id", "total"], ascending=[True, False]).reset_index(drop=True)


def _find_nominee(row, nominee_ids, nominees_by_race):
    """How a candidate matches the race's nominees: 'id', 'name', or None."""
    if row["candidate_id"] in nominee_ids:
        return "id"
    # A filing with no candidate ID, or a duplicate registration, still names the race and candidate
    for nominee in nominees_by_race.get(row["race_id"], []):
        if _last_name_matches(nominee["name"], row["candidate_name"]):
            return "name"
    return None


def primary_outcomes(support_df, nominee_ids, nominees):
    """Say whether each primary candidate went on to be a November nominee.

    A candidate is a nominee if their FEC ID is in `nominee_ids`, or, failing
    that, if their last name matches a nominee in the same race (`matched_by`
    records which, so name matches can be hand-checked). Anyone not matched
    is `lost` only when they have an FEC ID and the race's nominees are
    known. A candidate we can't place, or in a race with no known nominees,
    goes to `review` and is never counted as a loss. Withdrawals are not
    nominees, so they count as lost. In top-two states every candidate who
    advances is a nominee, so both count as wins.

    Parameters
    ----------
    support_df : pandas.DataFrame
        Output of `primary_support`.
    nominee_ids : set of str
        FEC candidate IDs of the November nominees.
    nominees : list of dict
        Nominees with `race_id` and `name` (from `src.nominees.parse_nominees`).

    Returns
    -------
    pandas.DataFrame
        `support_df` plus `matched_by`, `outcome` (won, lost, or review, for
        supported candidates), and `outcome_for_pac` (wanted if the opposed
        candidate did not become a nominee, unwanted if they did, or review).
    """
    nominees_by_race = {}
    for nominee in nominees:
        nominees_by_race.setdefault(nominee["race_id"], []).append(nominee)

    # Built as plain lists, not read back from the DataFrame: pandas turns a
    # None in a text column into NaN, which is truthy and would read as a match.
    matched_by, outcome, outcome_for_pac = [], [], []
    for _, row in support_df.iterrows():
        match = _find_nominee(row, nominee_ids, nominees_by_race)
        has_id = pd.notna(row["candidate_id"]) and row["candidate_id"] != ""
        decidable = has_id and row["race_id"] in nominees_by_race
        if match:
            verdict = ("won", "unwanted")
        elif decidable:
            verdict = ("lost", "wanted")
        else:
            verdict = ("review", "review")
        supported = row["support_oppose"] == "S"
        matched_by.append(match)
        outcome.append(verdict[0] if supported else None)
        outcome_for_pac.append(None if supported else verdict[1])

    result = support_df.copy()
    result["matched_by"] = matched_by
    result["outcome"] = outcome
    result["outcome_for_pac"] = outcome_for_pac
    return result


def _count(frame, column, labels):
    """Count rows per label, with zeros for labels that do not appear."""
    counts = frame[column].value_counts()
    return {label: int(counts.get(label, 0)) for label in labels}


def _rate(counts):
    """Wins over decided candidates, or None when none were decided."""
    decided = counts["won"] + counts["lost"]
    return counts["won"] / decided if decided else None


def win_rates(outcomes_df):
    """Summarize how backed candidates did, pooled and by PAC.

    Each candidate is counted once per race. Pooled, a candidate backed by
    two PACs is one candidate. The rate is over won and lost only, and
    candidates in review are counted separately.

    Parameters
    ----------
    outcomes_df : pandas.DataFrame
        Output of `primary_outcomes`.

    Returns
    -------
    dict
        `pooled` and `by_pac` (committee ID to counts), each with `won`,
        `lost`, `review`, and `rate`. `opposed` has `wanted`, `unwanted`, and
        `review` for candidates the PACs spent against, reported separately
        and not part of any rate.
    """
    candidate = outcomes_df["candidate_id"].fillna(outcomes_df["candidate_key"])
    frame = outcomes_df.assign(candidate=candidate)
    supported = frame[frame["support_oppose"] == "S"]
    opposed = frame[frame["support_oppose"] == "O"]

    def summarize(rows):
        counts = _count(rows.drop_duplicates(["race_id", "candidate"]), "outcome", ["won", "lost", "review"])
        return {**counts, "rate": _rate(counts)}

    return {
        "pooled": summarize(supported),
        "by_pac": {pac: summarize(rows) for pac, rows in supported.groupby("committee_id")},
        "opposed": _count(
            opposed.drop_duplicates(["race_id", "candidate"]), "outcome_for_pac", ["wanted", "unwanted", "review"]
        ),
    }


def could_not_test(concentration_df, reconcile_df, threshold=BACKED_THRESHOLD):
    """List PACs whose unexplained gap is big enough to hide a backed PAC.

    A PAC that does not reconcile is never classified, so a billionaire with
    30% of what we can see is not ruled out if a quarter of the PAC's money is
    missing from the itemized rows. Here the upper bound adds the whole gap
    to the donor's share, as if all the missing money were theirs. It is the
    most the share could be, not an estimate.

    Parameters
    ----------
    concentration_df : pandas.DataFrame
        Output of `concentration`.
    reconcile_df : pandas.DataFrame
        Output of `reconcile`.
    threshold : float, optional
        Share that makes a PAC billionaire-backed.

    Returns
    -------
    pandas.DataFrame
        Columns `committee_id`, `person`, `share`, `shortfall` (the missing
        fraction of the PAC's receipts), and `upper_bound`, for donors below
        the threshold whose upper bound reaches it on a PAC that does not
        reconcile. PACs whose rows overshoot the total have no shortfall.
    """
    merged = concentration_df.merge(reconcile_df[["committee_id", "diff_pct", "reconciled"]], on="committee_id")
    # diff_pct is negative when rows fall short of receipts
    merged["shortfall"] = (-merged["diff_pct"]).clip(lower=0.0)
    merged["upper_bound"] = merged["share"] + merged["shortfall"]
    flagged = merged[~merged["reconciled"] & (merged["share"] < threshold) & (merged["upper_bound"] >= threshold)]
    return flagged[["committee_id", "person", "share", "shortfall", "upper_bound"]].reset_index(drop=True)
