"""Build the simple 2026 House general election predictions.

Two rules, no model: the nominee with more external money, and the party Cook
rates ahead. The pinned Wikipedia nominee page is downloaded once (or reused),
matched to FEC candidates, and joined to the 2026-10-24 money snapshot. The
result is written to:

    reports/predictions/2026-general-simple.csv

The CSV is frozen once it is tagged (pre-election-simple). To correct it, write
a new dated file instead of editing this one.

Run from the repo root:
    python scripts/build_simple_predictions.py [--pulled-at YYYY-MM-DD]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Let this script import from src/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import DB_PATH, PROJECT_ROOT  # noqa: E402
from src.nominees import load_nominees  # noqa: E402
from src.manual import load_nominee_matches  # noqa: E402
from src.predict.simple import _load_candidates, match_nominees, simple_predictions  # noqa: E402

# Default money snapshot. The 2026-10-23 bulk file lagged some candidates'
# Pre-General reports (reports through Oct 14), so 2026-10-24 is the default.
DEFAULT_PULLED_AT = "2026-10-24"
OUTPUT_CSV = PROJECT_ROOT / "reports" / "predictions" / "2026-general-simple.csv"


def print_counts(predictions, nominees):
    """Print the counts a reader needs to sanity check the build.

    Parameters
    ----------
    predictions : pandas.DataFrame
        Output of `simple_predictions`.
    nominees : list of dict
        Nominees with a `candidate_id` key (None when unmatched).
    """
    scored = predictions[predictions["race_type"] == "D_vs_R"]
    both_called = scored.dropna(subset=["money_leader_party", "cook_favorite_party"])
    disagree = both_called[both_called["money_and_cook_agree"] == False]  # noqa: E712

    print("Races by type:\n", predictions["race_type"].value_counts().to_string(), sep="")
    print("\nRaces by status:\n", predictions["status"].value_counts().to_string(), sep="")
    unmatched = [n for n in nominees if n["candidate_id"] is None]
    major = [n for n in unmatched if n["party"] in ("Democratic", "Republican", "DFL")]
    print(f"\nUnmatched nominees: {len(unmatched)} ({len(major)} Democratic or Republican)")
    print(f"Money leader abstentions (D_vs_R): {scored['money_leader_party'].isna().sum()}")
    print(f"Cook abstentions (D_vs_R): {scored['cook_favorite_party'].isna().sum()}")
    print(f"Races where both made a call: {len(both_called)}")
    print(f"Races where money and Cook disagree: {len(disagree)}")


def main(argv=None):
    """Download or reuse the nominee page, build the predictions, and write the CSV."""
    parser = argparse.ArgumentParser(description="Build the simple 2026 House predictions")
    parser.add_argument("--pulled-at", default=DEFAULT_PULLED_AT, metavar="YYYY-MM-DD",
                        help="money snapshot date in the database")
    args = parser.parse_args(argv)

    nominees = load_nominees()
    with sqlite3.connect(DB_PATH) as conn:
        predictions = simple_predictions(conn, nominees, args.pulled_at)
        # Matching is deterministic, so redoing it here gives the same matches
        # the predictions used. It is only needed to list unmatched nominees.
        matched = match_nominees(nominees, _load_candidates(conn), load_nominee_matches())

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    predictions = predictions.sort_values("race_id")
    # Fixed line endings so the file is byte-identical on every machine
    predictions.to_csv(OUTPUT_CSV, index=False, lineterminator="\n")
    print(f"Wrote {len(predictions)} races to {OUTPUT_CSV}\n")
    print_counts(predictions, matched)


if __name__ == "__main__":
    main()
