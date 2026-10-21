"""Save one small page from each FEC endpoint as a test fixture.

The transform tests run against these real responses, so the field names
they check come from the API itself rather than from documentation.
Run from the repo root: python scripts/save_fixtures.py
"""

import json
import sys
from pathlib import Path

# Let this script import from src/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import CYCLE, PROJECT_ROOT, load_api_key  # noqa: E402
from src.fec.client import FecClient  # noqa: E402
from src.pipeline import ENDPOINTS, OUTSIDE_SPENDING_PATH  # noqa: E402

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"


def strip_api_key(value, api_key):
    """Remove the API key from anywhere in a saved response."""
    return json.loads(json.dumps(value).replace(api_key, "REDACTED"))


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
    top = client.get("/candidates/totals/", {**ENDPOINTS["totals"][1], "sort": "-receipts", "per_page": 20})
    ids = [r["candidate_id"] for r in top["results"]]
    body = client.get(OUTSIDE_SPENDING_PATH, {"cycle": CYCLE, "candidate_id": ids, "per_page": 5})
    out = FIXTURE_DIR / "outside_spending.json"
    out.write_text(json.dumps(strip_api_key(body, api_key), indent=2))
    print(f"outside_spending: {len(body['results'])} results -> {out.name}")


if __name__ == "__main__":
    main()
