"""Build the model-based 2026 House general election predictions.

A logistic regression (see `src/predict/model.py`) is fit on the 2022 and 2024
House generals and used to give each 2026 Democrat versus Republican race a
probability that the Democrat wins. Two files are written:

    reports/predictions/2026-general-model.csv
    reports/predictions/model-evaluation.json

The JSON holds everything behind the README's model section: training counts
and exclusions, the held-out evaluation, the full-fit coefficients, and the
2026 sanity checks. Both files are frozen once tagged (pre-election-model).

Run from the repo root:
    python scripts/build_model_predictions.py
"""

import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Let this script import from src/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import DB_PATH, HISTORY_CYCLES, NOMINEES_PAGE, PROJECT_ROOT  # noqa: E402
from src.history_results import _same_person  # noqa: E402
from src.nominees import parse_incumbents, parse_nominees  # noqa: E402
from src.predict.model import (  # noqa: E402
    FEATURES, _dem_pvi, _incumbency, coefficients, evaluate, fit, money_share_effect,
    race_table, training_frame,
)
from src.predict.simple import _load_money, simple_predictions  # noqa: E402
from src.ratings import download_page  # noqa: E402

# Same money snapshot as the simple predictions
PULLED_AT = "2026-10-24"
OUTPUT_DIR = PROJECT_ROOT / "reports" / "predictions"
OUTPUT_CSV = OUTPUT_DIR / "2026-general-model.csv"
OUTPUT_JSON = OUTPUT_DIR / "model-evaluation.json"

# Workaround for one known false match of the incumbent name rule. Trever
# Nehls (TX-22 Republican nominee) is the twin brother of the retiring member
# Troy Nehls. The rule compares last name and first initial (so "Tom" can
# meet "Thomas"), which cannot tell the two apart. Checked by hand against the
# pinned page: every other inexact match is a middle initial or an accent.
NOT_INCUMBENT = {("TX-22", "Trever Nehls")}

CSV_COLUMNS = [
    "race_id", "dem_name", "rep_name", "dem_money_share", "incumbency", "dem_pvi",
    "dem_win_probability", "money_leader_party", "cook_favorite_party", "money_record_missing",
]


# Training summary

def training_counts(table):
    """Races, exclusions, and trainable rows for each cycle.

    Parameters
    ----------
    table : pandas.DataFrame
        Output of `race_table`.

    Returns
    -------
    dict
        Cycle (as a string) to its counts.
    """
    counts = {}
    for cycle, rows in table.groupby("cycle"):
        exclusion = rows["exclusion"].fillna("")
        kept = rows[exclusion == ""]
        counts[str(cycle)] = {
            "d_vs_r_races": int(len(rows)),
            "excluded_missing_money": int(exclusion.str.startswith("missing_money").sum()),
            "excluded_third_party_outraised": int((exclusion == "third_party_outraised").sum()),
            "in_frame": int(len(kept)),
            "undefined_money_share": int(kept["dem_money_share"].isna().sum()),
            "trainable": int(kept.dropna(subset=FEATURES).shape[0]),
            "both_incumbents_set_to_0": int(kept["both_incumbents"].sum()),
        }
    return counts


def excluded_races(table):
    """The excluded training races with nominee names, money, and the reason."""
    excluded = table[table["exclusion"].notna()]
    columns = ["cycle", "race_id", "dem_name", "rep_name", "dem_money", "rep_money", "exclusion"]
    return excluded[columns].to_dict("records")


def both_incumbent_races(table):
    """Member versus member races kept in training with incumbency set to 0."""
    rows = table[table["both_incumbents"] & table["exclusion"].isna()]
    return rows[["cycle", "race_id", "dem_name", "rep_name"]].to_dict("records")


# 2026 inputs

def load_pvi(conn):
    """Democratic-oriented PVI for each 2026 race, converted as in training."""
    frame = pd.read_sql_query("SELECT race_id, cook_pvi FROM races", conn)
    return {row.race_id: _dem_pvi(row.cook_pvi) for row in frame.itertuples()}


def is_incumbent(race_id, name, members):
    """True when a nominee is one of the district's listed members (training's name rule)."""
    if (race_id, name) in NOT_INCUMBENT:
        return False
    return any(_same_person(name, member) for member in members)


def races_to_predict(simple):
    """D vs R races with confirmed nominees and no third party outraising a major nominee."""
    keep = (
        (simple["race_type"] == "D_vs_R")
        & (simple["status"] == "confirmed")
        & ~simple["third_party_outraised"].astype(bool)
    )
    return simple[keep].copy()


def add_model_inputs(races, incumbents, pvi, money):
    """Add incumbency, dem_pvi, and money_record_missing to the 2026 races.

    Parameters
    ----------
    races : pandas.DataFrame
        Rows of `simple_predictions` to predict.
    incumbents : dict
        Output of `parse_incumbents` for the pinned 2026 page.
    pvi : dict
        Output of `load_pvi`.
    money : dict
        Candidate ID to external money at PULLED_AT.

    Returns
    -------
    pandas.DataFrame
    """
    races = races.copy()
    dem_incumbent = [is_incumbent(r.race_id, r.dem_name, incumbents[r.race_id]) for r in races.itertuples()]
    rep_incumbent = [is_incumbent(r.race_id, r.rep_name, incumbents[r.race_id]) for r in races.itertuples()]
    races["incumbency"] = [
        _incumbency({"is_incumbent": d}, {"is_incumbent": r}) for d, r in zip(dem_incumbent, rep_incumbent)
    ]
    races["both_incumbents"] = [d and r for d, r in zip(dem_incumbent, rep_incumbent)]
    races["dem_pvi"] = races["race_id"].map(pvi)
    # Training dropped races where a major nominee had no money record, so a
    # prediction for one of these is outside what the model saw
    races["money_record_missing"] = [
        r.dem_candidate_id not in money or r.rep_candidate_id not in money for r in races.itertuples()
    ]
    races["dem_money_share"] = races["dem_money_share"].astype(float)
    return races


def predict(model, races):
    """Add dem_win_probability (NaN when the money share is undefined)."""
    races = races.copy()
    usable = races.dropna(subset=FEATURES)
    races["dem_win_probability"] = np.nan
    races.loc[usable.index, "dem_win_probability"] = model.predict_proba(usable[FEATURES])[:, 1]
    return races


# Comparisons and sanity checks

def model_call(probability):
    """DEM above 0.5, REP below, None at exactly 0.5 or when missing."""
    if pd.isna(probability) or probability == 0.5:
        return None
    return "DEM" if probability > 0.5 else "REP"


def disagreements(races, rule_column):
    """Races where the model and a rule both make a call and name different parties."""
    calls = races["dem_win_probability"].map(model_call)
    both = calls.notna() & races[rule_column].notna()
    differ = races[both & (calls != races[rule_column])]
    return [
        {"race_id": r.race_id, "dem_name": r.dem_name, "rep_name": r.rep_name,
         "dem_win_probability": r.dem_win_probability, "rule_call": getattr(r, rule_column),
         "cook_rating": r.cook_rating}
        for r in differ.itertuples()
    ]


def incumbency_vs_fec_flag(races):
    """Races where the page-based incumbency names a different party than the simple CSV.

    The simple CSV's incumbent_party used the FEC incumbent flag, while the
    model uses the Member column of the nominees page, as training did.
    """
    page_party = races["incumbency"].map({1: "DEM", -1: "REP", 0: None})
    fec_party = races["incumbent_party"].where(races["incumbent_party"].notna(), None)
    differ = races[page_party.fillna("") != fec_party.fillna("")]
    return [
        {"race_id": r.race_id, "dem_name": r.dem_name, "rep_name": r.rep_name,
         "page_incumbency": int(r.incumbency), "fec_incumbent_party": r.incumbent_party,
         "both_listed_as_members": bool(r.both_incumbents)}
        for r in differ.itertuples()
    ]


def safe_seat_range(races, rating):
    """Count and probability range for one Solid rating."""
    probabilities = races.loc[races["cook_rating"] == rating, "dem_win_probability"]
    return {"count": int(probabilities.size), "min": float(probabilities.min()), "max": float(probabilities.max())}


def sanity_checks(races, coefs):
    """The checks run before the predictions are committed.

    Raises
    ------
    RuntimeError
        If a probability is exactly 0 or 1, one is missing, or a coefficient
        sign points away from the Democrat. These would mean the model or its
        inputs are broken, so the script stops instead of writing files.
    """
    probabilities = races["dem_win_probability"]
    checks = {
        "rows": int(len(races)),
        "missing_probability": int(probabilities.isna().sum()),
        "exactly_0_or_1": int(((probabilities == 0) | (probabilities == 1)).sum()),
        "min_probability": float(probabilities.min()),
        "max_probability": float(probabilities.max()),
        "solid_d": safe_seat_range(races, "Solid D"),
        "solid_r": safe_seat_range(races, "Solid R"),
        "coefficient_signs_positive": all(coefs[f] > 0 for f in FEATURES),
        "money_record_missing": int(races["money_record_missing"].sum()),
        "incumbency_counts": {"dem_incumbent": int((races["incumbency"] == 1).sum()),
                              "rep_incumbent": int((races["incumbency"] == -1).sum()),
                              "neither_or_both": int((races["incumbency"] == 0).sum())},
        "both_incumbents": int(races["both_incumbents"].sum()),
    }
    if checks["missing_probability"] or checks["exactly_0_or_1"] or not checks["coefficient_signs_positive"]:
        raise RuntimeError(f"Sanity check failed: {checks}")
    return checks


# Output

def clean_for_json(value):
    """Turn numpy numbers into plain ones and NaN into None, recursively."""
    if isinstance(value, dict):
        return {str(k): clean_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_for_json(v) for v in value]
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return None if math.isnan(value) else float(value)
    return value


def write_outputs(races, report):
    """Write the CSV and JSON with fixed line endings, so reruns are byte-identical."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    races.sort_values("race_id")[CSV_COLUMNS].to_csv(OUTPUT_CSV, index=False, lineterminator="\n")
    text = json.dumps(clean_for_json(report), indent=2, ensure_ascii=False, allow_nan=False)
    OUTPUT_JSON.write_text(text + "\n", encoding="utf-8", newline="\n")


def print_summary(report):
    """Print the numbers a reader checks before committing."""
    checks = report["predictions_2026"]["sanity_checks"]
    print(f"Wrote {checks['rows']} races to {OUTPUT_CSV}")
    print(f"Wrote evaluation to {OUTPUT_JSON}\n")
    print("Sanity checks:", json.dumps(checks, indent=2))
    print("Full-fit coefficients:", json.dumps(report["full_fit"]["coefficients"], indent=2))
    for key in ("model_vs_money_rule", "model_vs_cook"):
        rows = report["predictions_2026"][key]
        print(f"\n{key}: {len(rows)} races")
        for row in rows:
            print(f"  {row['race_id']}: p(D) {row['dem_win_probability']:.3f}, rule {row['rule_call']}, "
                  f"Cook {row['cook_rating']}")
    paired = report["evaluation"]["pooled"]["competitive"]["bootstrap_95"]["paired_difference"]
    print("\nPaired differences, competitive shared set:", json.dumps(paired, indent=2))


def main():
    """Fit on 2022 and 2024, predict 2026, and write both files."""
    html = download_page(NOMINEES_PAGE).read_text(encoding="utf-8")
    nominees, incumbents = parse_nominees(html), parse_incumbents(html)
    cycles = list(HISTORY_CYCLES)
    with sqlite3.connect(DB_PATH) as conn:
        table = race_table(conn, cycles)
        frame = training_frame(conn, cycles)
        simple = simple_predictions(conn, nominees, PULLED_AT)
        pvi, money = load_pvi(conn), _load_money(conn, PULLED_AT)

    model = fit(frame)
    coefs = coefficients(model)
    races = predict(model, add_model_inputs(races_to_predict(simple), incumbents, pvi, money))

    report = {
        "cycles": cycles,
        "counts": training_counts(table),
        "exclusions": excluded_races(table),
        "both_incumbents": both_incumbent_races(table),
        "evaluation": evaluate(frame),
        "full_fit": {
            "n_train": int(frame.dropna(subset=FEATURES).shape[0]),
            "coefficients": coefs,
            "money_share_effect": money_share_effect(model, frame),
        },
        "predictions_2026": {
            "money_pulled_at": PULLED_AT,
            "nominees_page_revision": NOMINEES_PAGE[1],
            "sanity_checks": sanity_checks(races, coefs),
            "money_record_missing": races.loc[races["money_record_missing"], ["race_id", "dem_name", "rep_name"]]
                                         .to_dict("records"),
            "incumbency_differs_from_fec_flag": incumbency_vs_fec_flag(races),
            "model_vs_money_rule": disagreements(races, "money_leader_party"),
            "model_vs_cook": disagreements(races, "cook_favorite_party"),
        },
    }
    write_outputs(races, report)
    print_summary(report)


if __name__ == "__main__":
    main()
