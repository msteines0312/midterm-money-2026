"""Save one small page from each FEC endpoint as a test fixture.

The transform tests run against these real responses, so the field names
they check come from the API itself rather than from documentation.
Run from the repo root: python scripts/save_fixtures.py
"""

import csv
import io
import json
import sys
from pathlib import Path

# Let this script import from src/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import CYCLE, PROJECT_ROOT, load_api_key  # noqa: E402
from src.fec.client import FecClient  # noqa: E402
from src.fec.independent_expenditures import (  # noqa: E402
    download_independent_expenditures,
    parse_independent_expenditures,
)
from src.pipeline import ENDPOINTS, OUTSIDE_SPENDING_PATH  # noqa: E402

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"


def strip_api_key(value, api_key):
    """Remove the API key from anywhere in a saved response."""
    return json.loads(json.dumps(value).replace(api_key, "REDACTED"))


# (committee, transaction) pairs saved by save_ie_sample, with the test each serves
IE_SAMPLE_TRANSACTIONS = [
    # CLF, blank cand_id, WA-05 (two rows, same race and last name): blank ID
    # tests, and the aggregation test (same committee, candidate, sup_opp, ele_type)
    ("C00504530", "SE24.6747"),
    ("C00504530", "SE24.6708"),
    # One transaction filed three times (N, A1, A2) with a different amount
    # each time, in a primary (ele_type P): amendment and election type tests
    ("C00900993", "WFT2026441236-1"),
    # Ordinary House rows with a cand_id
    ("C00348540", "500370949"),
    ("C00348540", "500370948"),
    # At-large seat (can_office_dis 00): race_id test
    ("C00888065", "WFT2026961052-1"),
    # Senate and presidential rows: House-only test
    ("C00348540", "500370946"),
    ("C00884023", "500165941"),
]


def save_ie_sample():
    """Save a few real rows of the bulk independent expenditure file.

    The whole file is over 10 MB, so only the transactions listed in
    IE_SAMPLE_TRANSACTIONS are kept (every version of each one). Row choices
    were made against the Oct 23 2026 download; the file keeps changing, so
    rerunning this later may need new IDs.
    """
    rows = parse_independent_expenditures(download_independent_expenditures())
    wanted = set(IE_SAMPLE_TRANSACTIONS)
    sample = [row for row in rows if (row["spe_id"], row["tran_id"]) in wanted]
    found = {(row["spe_id"], row["tran_id"]) for row in sample}
    if found != wanted:
        raise SystemExit(f"Transactions missing from the download: {sorted(wanted - found)}")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(sample[0]), lineterminator="\n")
    writer.writeheader()
    # parse_independent_expenditures turned blanks into None; write them back as blanks
    writer.writerows({k: v or "" for k, v in row.items()} for row in sample)
    out = FIXTURE_DIR / "ie_sample.csv"
    # newline="" stops Windows from turning the LF line endings into CRLF
    with open(out, "w", encoding="latin-1", newline="") as handle:
        handle.write(buffer.getvalue())
    print(f"ie_sample: {len(sample)} rows -> {out.name}")


def main():
    api_key = load_api_key()
    client = FecClient(api_key)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, (path, params) in ENDPOINTS.items():
        body = client.get(path, {**params, "per_page": 5})
        out = FIXTURE_DIR / f"{name}.json"
        out.write_text(json.dumps(strip_api_key(body, api_key), indent=2))
        print(f"{name}: {len(body.get('results', []))} results -> {out.name}")

    # Outside spending is queried by candidate ID. The top fundraisers are
    # used here because they're the likeliest to have outside money.
    top = client.get(
        "/candidates/totals/",
        {"office": "H", "election_year": CYCLE, "cycle": CYCLE, "sort": "-receipts", "per_page": 20},
    )
    ids = [r["candidate_id"] for r in top["results"]]
    body = client.get(OUTSIDE_SPENDING_PATH, {"cycle": CYCLE, "candidate_id": ids, "per_page": 5})
    out = FIXTURE_DIR / "outside_spending.json"
    out.write_text(json.dumps(strip_api_key(body, api_key), indent=2))
    print(f"outside_spending: {len(body['results'])} results -> {out.name}")

    save_ie_sample()


if __name__ == "__main__":
    main()
