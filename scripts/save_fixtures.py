"""Save one small page from each FEC endpoint as a test fixture.

The transform tests run against these real responses, so the field names
they check come from the API itself rather than from documentation.
Run from the repo root: python scripts/save_fixtures.py
(or `python scripts/save_fixtures.py history` for just the history samples)
"""

import csv
import io
import json
import sys
from pathlib import Path

# Let this script import from src/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import PROJECT_ROOT, load_api_key  # noqa: E402
from src.fec.client import FecClient  # noqa: E402
from src.fec.history import download_ccl  # noqa: E402
from src.fec.independent_expenditures import (  # noqa: E402
    download_independent_expenditures,
    parse_independent_expenditures,
)
from src.pipeline import ENDPOINTS  # noqa: E402

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


# 2024 principal campaign committees saved by save_history_samples, with the
# test each serves. Picked by hand from the Oct 24 2026 API and ccl24 file.
HISTORY_SAMPLE_COMMITTEES = [
    # Ordinary 12G filers whose 12G covers Oct 1 to Oct 16. They set the
    # cutoff. C00830661 is listed twice for one candidate in ccl24.
    "C00830661", "C00838060", "C00842765",
    # 12G amended in Dec 2024 with $1,000 less individual money: amendment test
    "C00507368",
    # 12G covering Oct 1 to Oct 20, past the cutoff, so its Q3 is used instead
    "C00859140",
    # Only 2024 report is a 12G covering Aug 9 to Nov 5: excluded, so no row
    "C00886770",
    # Two principal committees for one candidate (H2NV04045), neither filed a 12G
    "C00582320", "C00654095",
]

# Election-year report types the history loader asks for, plus the 30G (post
# general) so the sample also shows a report it should never use
HISTORY_ELECTION_YEAR_TYPES = [
    "12G", "Q3", "Q2", "Q1", "12P", "12R", "12S", "12C", "30S", "30R", "TER", "30G",
]


def save_history_samples(client, api_key):
    """Save real 2024 reports and ccl24 lines for HISTORY_SAMPLE_COMMITTEES.

    Every version of each report is kept (no amendment filter), so the tests
    can check that only the latest version counts.

    Parameters
    ----------
    client : FecClient
    api_key : str
        Stripped from the saved responses.
    """
    base = {"cycle": 2024, "committee_id": HISTORY_SAMPLE_COMMITTEES, "sort": "beginning_image_number"}
    # The API ignores report_year, so both files hold 2023 and 2024 reports,
    # just as a real pull does. The loader sorts them out by report_year.
    samples = {
        "reports_12g_sample.json": {**base, "report_type": HISTORY_ELECTION_YEAR_TYPES},
        # YE reports are never used for money. They are saved to show the
        # "_ytd" fields are cycle-to-date, not calendar year-to-date.
        "reports_ye_sample.json": {**base, "report_type": "YE"},
    }
    for name, params in samples.items():
        results = list(client.iter_results("/reports/house-senate/", params))
        out = FIXTURE_DIR / name
        out.write_text(json.dumps(strip_api_key({"results": results}, api_key), indent=2))
        print(f"{name}: {len(results)} reports")

    wanted = set(HISTORY_SAMPLE_COMMITTEES)
    lines = [line for line in download_ccl(2024).splitlines() if line.split("|")[3] in wanted]
    out = FIXTURE_DIR / "ccl_sample.txt"
    # newline="" keeps LF line endings on Windows, like the IE sample
    with open(out, "w", encoding="latin-1", newline="") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"ccl_sample.txt: {len(lines)} lines")


def main():
    api_key = load_api_key()
    client = FecClient(api_key)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    # "history" saves only the 2022/2024 history samples, leaving the other
    # fixtures as they are (the IE sample can't be rebuilt from today's file)
    if sys.argv[1:] == ["history"]:
        save_history_samples(client, api_key)
        return

    for name, (path, params) in ENDPOINTS.items():
        body = client.get(path, {**params, "per_page": 5})
        out = FIXTURE_DIR / f"{name}.json"
        out.write_text(json.dumps(strip_api_key(body, api_key), indent=2))
        print(f"{name}: {len(body.get('results', []))} results -> {out.name}")

    save_ie_sample()
    save_history_samples(client, api_key)


if __name__ == "__main__":
    main()
