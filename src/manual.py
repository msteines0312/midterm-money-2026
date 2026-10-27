"""Load hand-built CSVs from data/manual/.

These files hold judgment calls the FEC doesn't make for us, like which
super PACs count as "crypto" or "AI". Every row must cite a source so a
reader can check the call.
"""

import csv

from src.config import PAC_INDUSTRIES_CSV


def load_pac_industries(path=PAC_INDUSTRIES_CSV):
    """Read and validate the PAC industry labels.

    Parameters
    ----------
    path : pathlib.Path, optional
        CSV with columns committee_id, industry, source_url.

    Returns
    -------
    list of dict
        One dict per labeled committee, with whitespace stripped.

    Raises
    ------
    ValueError
        If a row has no source or a committee is labeled twice.
    """
    with open(path, newline="", encoding="utf-8") as f:
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(f)]

    seen = set()
    for row in rows:
        if not row["source_url"]:
            raise ValueError(f"{row['committee_id']} has no source_url")
        if row["committee_id"] in seen:
            raise ValueError(f"{row['committee_id']} is a duplicate")
        seen.add(row["committee_id"])
    return rows
