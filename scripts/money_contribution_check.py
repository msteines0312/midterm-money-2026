"""Check whether money share adds information beyond incumbency and PVI.

The frozen evaluation (reports/predictions/model-evaluation.json) shows the
held-out Brier score dropping when money share is added to a model that
already has incumbency and PVI, but with no interval. This script puts a
paired bootstrap interval on that gain.

It rebuilds the same leave-one-cycle-out predictions as `evaluate` in
`src/predict/model.py` (train on 2022 and score 2024, then the reverse), for
the model with money and the model without it. Only 2022 and 2024 races are
used, and no 2026 data is read. Each bootstrap draw resamples races once and
scores both models on those same races, so the interval reflects how the two
differ race by race.

The output is a new dated file. The tagged files are never touched:

    reports/predictions/supplementary-2026-10-26.json

Run from the repo root:
    python scripts/money_contribution_check.py
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Let this script import from src/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import DB_PATH, HISTORY_CYCLES, PROJECT_ROOT  # noqa: E402
from src.predict.model import (  # noqa: E402
    BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, COMPETITIVE_RATINGS, FEATURES_WITHOUT_MONEY,
    _paired_difference, _party_call, _predict, _resample_indices, fit, training_frame,
)

OUTPUT_JSON = PROJECT_ROOT / "reports" / "predictions" / "supplementary-2026-10-26.json"


def held_out_predictions(frame):
    """Leave-one-cycle-out probabilities from the models with and without money.

    Same folds and fits as `evaluate`: each cycle is scored by models trained
    only on the other cycles.

    Parameters
    ----------
    frame : pandas.DataFrame
        Output of `training_frame` covering at least two cycles.

    Returns
    -------
    pandas.DataFrame
        The frame's rows plus `p_model` and `p_without_money`.
    """
    held_out = []
    for test_cycle in sorted(frame["cycle"].unique(), reverse=True):
        train = frame[frame["cycle"] != test_cycle]
        test = frame[frame["cycle"] == test_cycle].copy()
        test["p_model"] = _predict(fit(train), test)
        test["p_without_money"] = _predict(fit(train, features=FEATURES_WITHOUT_MONEY), test)
        held_out.append(test)
    return pd.concat(held_out)


def _correct(probabilities, actual):
    """1.0 where the call at 0.5 names the winner, else 0.0."""
    return (_party_call(probabilities) == actual).to_numpy(dtype=float)


def paired_money_contribution(predictions, seed=BOOTSTRAP_SEED):
    """Brier and accuracy gains from adding money, with paired bootstrap 95% intervals.

    Races are kept only when both models scored them. One set of resampled
    race indices is drawn and used for both differences, so every draw scores
    both models on the same races.

    Parameters
    ----------
    predictions : pandas.DataFrame
        Rows with `p_model`, `p_without_money`, and `dem_won`.
    seed : int
        Seed for the resampling, fixed so results can be reproduced.

    Returns
    -------
    dict
        `n_races`, each model's Brier score and accuracy, and two paired
        differences with `estimate`, `low`, and `high`:
        `brier_without_minus_with` (positive means money lowered the error)
        and `accuracy_with_minus_without` (positive means money added correct calls).
    """
    scored = predictions.dropna(subset=["p_model", "p_without_money"])
    outcome = scored["dem_won"].to_numpy(dtype=float)
    actual = scored["dem_won"].map({1: "DEM", 0: "REP"})
    # Per-race squared error, so the mean of each array is that model's Brier score
    error_with = (scored["p_model"].to_numpy() - outcome) ** 2
    error_without = (scored["p_without_money"].to_numpy() - outcome) ** 2
    correct_with = _correct(scored["p_model"], actual)
    correct_without = _correct(scored["p_without_money"], actual)

    resamples = _resample_indices(len(scored), np.random.default_rng(seed))
    return {
        "n_races": int(len(scored)),
        "brier_with_money": float(error_with.mean()) if len(scored) else None,
        "brier_without_money": float(error_without.mean()) if len(scored) else None,
        "accuracy_with_money": float(correct_with.mean()) if len(scored) else None,
        "accuracy_without_money": float(correct_without.mean()) if len(scored) else None,
        # `_paired_difference` returns mean(a - b) and its percentile interval
        "brier_without_minus_with": _paired_difference(error_without, error_with, resamples),
        "accuracy_with_minus_without": _paired_difference(correct_with, correct_without, resamples),
    }


def build_report(frame):
    """The supplementary results for competitive races and for all races."""
    predictions = held_out_predictions(frame)
    competitive = predictions["cook_rating"].isin(COMPETITIVE_RATINGS)
    return {
        "date": "2026-10-26",
        "note": ("Added after the pre-election-model tag. Uses only 2022 and 2024 held-out "
                 "predictions; the tagged prediction files are unchanged."),
        "cycles": [int(c) for c in sorted(frame["cycle"].unique())],
        "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED,
                      "interval": "2.5th to 97.5th percentile", "unit": "race"},
        "competitive": paired_money_contribution(predictions[competitive]),
        "all_races": paired_money_contribution(predictions),
    }


def main():
    """Rebuild the held-out predictions, run the paired bootstrap, and write the JSON."""
    with sqlite3.connect(DB_PATH) as conn:
        frame = training_frame(conn, list(HISTORY_CYCLES))
    report = build_report(frame)
    text = json.dumps(report, indent=2, allow_nan=False)
    # Fixed line endings so reruns are byte-identical on every machine
    OUTPUT_JSON.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT_JSON}")
    print(text)


if __name__ == "__main__":
    main()
