"""Tables for the tech money report, built from one pull of outside spending.

Every function takes an open database connection and a `pulled_at` date and
returns a DataFrame. Each one only counts spending by committees that are in
the `committees` table with a type of O (super PAC), V or W (hybrid PACs).
The real `outside_spending` table also holds rows from a bogus individual
filer (about $13B) and from party committees. Neither is a super PAC, and
neither may enter any total, so the filter is applied everywhere, even in the
network functions where the labeled committees should already pass it.

Spending is grouped by `outside_spending.party`, which was already resolved
for every row, including filings with no candidate ID.
"""

import pandas as pd

# Rows from real super PACs and hybrid PACs for one pull. Building every query
# on this keeps the committee filter in one place instead of repeating it.
SUPER_PAC_SPENDING = """
    SELECT s.*
    FROM outside_spending AS s
    JOIN committees AS c ON c.committee_id = s.committee_id
    WHERE s.pulled_at = :pulled_at
      AND c.committee_type IN ('O', 'V', 'W')
"""

# The same rows, limited to labeled committees and tagged with their network
NETWORK_SPENDING = f"""
    SELECT p.network, p.industry, s.*
    FROM ({SUPER_PAC_SPENDING}) AS s
    JOIN pac_industries AS p ON p.committee_id = s.committee_id
"""


def _query(conn, sql, pulled_at, **params):
    """Run a query with the pull date and any extra named parameters."""
    return pd.read_sql_query(sql, conn, params={"pulled_at": pulled_at, **params})


def network_totals(conn, pulled_at):
    """Total spending and candidate count for each labeled network.

    Spending with no race still counts here, because the total does not need
    a race.

    Parameters
    ----------
    conn : sqlite3.Connection
    pulled_at : str
        ISO date of the snapshot.

    Returns
    -------
    pandas.DataFrame
        Columns `network`, `industry`, `total`, `n_candidates`. The candidate
        count is the number of distinct `candidate_key` values.
    """
    sql = f"""
        SELECT network, industry,
               SUM(total) AS total,
               COUNT(DISTINCT candidate_key) AS n_candidates
        FROM ({NETWORK_SPENDING})
        GROUP BY network, industry
        ORDER BY total DESC
    """
    return _query(conn, sql, pulled_at)


def party_buckets(conn, pulled_at):
    """Network spending split by party and by support or opposition.

    DEM and DFL count as Democrats and REP as Republicans. Any other party
    code, including a missing one, goes in "Other or unknown". Spending with
    no race still counts here.

    Parameters
    ----------
    conn : sqlite3.Connection
    pulled_at : str

    Returns
    -------
    pandas.DataFrame
        Columns `network`, `bucket`, `total`.
    """
    sql = f"""
        SELECT network,
               CASE
                   WHEN party IN ('DEM', 'DFL') AND support_oppose = 'S' THEN 'Supporting Democrats'
                   WHEN party IN ('DEM', 'DFL') AND support_oppose = 'O' THEN 'Opposing Democrats'
                   WHEN party = 'REP' AND support_oppose = 'S' THEN 'Supporting Republicans'
                   WHEN party = 'REP' AND support_oppose = 'O' THEN 'Opposing Republicans'
                   ELSE 'Other or unknown'
               END AS bucket,
               SUM(total) AS total
        FROM ({NETWORK_SPENDING})
        GROUP BY network, bucket
        ORDER BY network, bucket
    """
    return _query(conn, sql, pulled_at)


def support_oppose_totals(conn, pulled_at):
    """Network spending supporting and opposing candidates, of any party.

    Unlike `party_buckets`, rows with no party are split by side too, so
    the two totals cover all of a network's spending.

    Parameters
    ----------
    conn : sqlite3.Connection
    pulled_at : str

    Returns
    -------
    pandas.DataFrame
        Columns `network`, `support_oppose` ("S" or "O"), `total`.
    """
    sql = f"""
        SELECT network, support_oppose, SUM(total) AS total
        FROM ({NETWORK_SPENDING})
        GROUP BY network, support_oppose
        ORDER BY network, support_oppose
    """
    return _query(conn, sql, pulled_at)


def competitiveness(conn, pulled_at):
    """General election network spending by how competitive the seat is.

    Only general election money counts, since a primary says nothing about
    the November race. Toss Up, Lean and Likely ratings are Competitive and
    Solid is Safe. Spending with no race drops out because it has no rating.

    Parameters
    ----------
    conn : sqlite3.Connection
    pulled_at : str

    Returns
    -------
    pandas.DataFrame
        Columns `network`, `seat_type`, `total`.
    """
    sql = f"""
        SELECT n.network,
               CASE WHEN r.cook_rating LIKE 'Solid%' THEN 'Safe' ELSE 'Competitive' END AS seat_type,
               SUM(n.total) AS total
        FROM ({NETWORK_SPENDING}) AS n
        JOIN races AS r ON r.race_id = n.race_id
        WHERE n.election_type = 'G'
          AND r.cook_rating IS NOT NULL
        GROUP BY n.network, seat_type
        ORDER BY n.network, seat_type
    """
    return _query(conn, sql, pulled_at)


def primary_vs_general(conn, pulled_at):
    """Network spending by stage of the election.

    Runoff, special and convention spending, and anything coded other, is
    grouped as Other. Spending with no race still counts here.

    Parameters
    ----------
    conn : sqlite3.Connection
    pulled_at : str

    Returns
    -------
    pandas.DataFrame
        Columns `network`, `election`, `total`.
    """
    sql = f"""
        SELECT network,
               CASE election_type
                   WHEN 'P' THEN 'Primary'
                   WHEN 'G' THEN 'General'
                   ELSE 'Other'
               END AS election,
               SUM(total) AS total
        FROM ({NETWORK_SPENDING})
        GROUP BY network, election
        ORDER BY network, election
    """
    return _query(conn, sql, pulled_at)


def top_races(conn, pulled_at, n=10):
    """Races with the most network spending, next to all super PAC spending there.

    Spending with no race drops out, since there is no race to rank.

    Parameters
    ----------
    conn : sqlite3.Connection
    pulled_at : str
    n : int, default 10
        Number of races to return.

    Returns
    -------
    pandas.DataFrame
        Columns `race_id`, `cook_rating`, `network_total`,
        `all_super_pac_total`. `all_super_pac_total` includes unlabeled
        super PACs and is limited to O, V and W committees.
    """
    sql = f"""
        SELECT n.race_id,
               r.cook_rating,
               SUM(n.total) AS network_total,
               (SELECT SUM(a.total) FROM ({SUPER_PAC_SPENDING}) AS a
                WHERE a.race_id = n.race_id) AS all_super_pac_total
        FROM ({NETWORK_SPENDING}) AS n
        LEFT JOIN races AS r ON r.race_id = n.race_id
        WHERE n.race_id IS NOT NULL
        GROUP BY n.race_id, r.cook_rating
        ORDER BY network_total DESC, n.race_id
        LIMIT :n
    """
    return _query(conn, sql, pulled_at, n=n)


def network_share(conn, pulled_at):
    """Each network's share of all super PAC and hybrid PAC spending.

    The denominator is every row from O, V and W committees, labeled or not.
    Party committees and non-committee filers are left out of both sides.

    Parameters
    ----------
    conn : sqlite3.Connection
    pulled_at : str

    Returns
    -------
    pandas.DataFrame
        Columns `network`, `total`, `share_of_super_pac_spending`.
    """
    totals = network_totals(conn, pulled_at).groupby("network", as_index=False)["total"].sum()
    all_spending = _query(conn, f"SELECT SUM(total) AS total FROM ({SUPER_PAC_SPENDING})", pulled_at)
    totals["share_of_super_pac_spending"] = totals["total"] / all_spending["total"].iloc[0]
    return totals
