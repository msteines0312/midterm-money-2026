"""Build the charts and the numbers file for the money and winning report.

Reads only the frozen prediction files in `reports/predictions/` (no
database, no network) and writes everything `reports/money-and-winning.md`
relies on:

    reports/figures/competitive_accuracy.png
    reports/figures/win_probability_vs_money.png
    reports/figures/competitive_calibration.png
    reports/figures/money_winning_numbers.json

The frozen inputs are the two tagged prediction CSVs, the tagged model
evaluation, and the dated supplementary bootstrap. This script only reads
them, so running it can never change a prediction.

The prose is written by hand. The JSON keeps each raw value next to the exact
text the report uses for it (under `cited`), and
tests/test_money_winning_report.py checks that every cited string appears in
the report and that the JSON matches a fresh build from the frozen files.

Run from the repo root:
    python scripts/build_money_winning_report.py
"""

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib

# Write PNGs without opening a window, so the script also runs on a server
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

# Let this script import from src/ and scripts/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reuse section 1's palette and axis styling so the write-up reads as one set
# of charts. Importing the module has no side effects beyond choosing the Agg
# backend, which this script does anyway.
from build_tech_money_report import (  # noqa: E402
    BLUE, GRAY, GRID, RED, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY, add_note, style_axes,
)
from src.config import PROJECT_ROOT  # noqa: E402

PREDICTIONS_DIR = PROJECT_ROOT / "reports" / "predictions"
FIGURES_DIR = PROJECT_ROOT / "reports" / "figures"
REPORT_PATH = PROJECT_ROOT / "reports" / "money-and-winning.md"

FROZEN_FILES = {
    "simple": "2026-general-simple.csv",
    "model": "2026-general-model.csv",
    "evaluation": "model-evaluation.json",
    "supplementary": "supplementary-2026-10-26.json",
}

# Snapshot dates, shown in every chart subtitle
MONEY_PULLED_AT = "2026-10-24"
HELD_OUT_LABEL = "Held-out 2022 and 2024 House generals"

# Tag commits, recorded in the predictions README and the root README
TAGS = {"pre-election-simple": "c18c0db", "pre-election-model": "eb42038"}

# A neutral ink for charts where party is not the encoding
NEUTRAL = "#3d3c39"

PARTY_NAMES = {"DEM": "Democratic", "REP": "Republican"}
INCUMBENCY_GROUPS = [
    # (incumbency value, legend label, color, marker). Party colors are used
    # here because the incumbent's party is what the color encodes. Gray means
    # no incumbent, and the marker shape repeats the encoding for readers who
    # can't separate the colors.
    (1, "Democratic incumbent", BLUE, "o"),
    (-1, "Republican incumbent", RED, "s"),
    (0, "Open seat", GRAY, "^"),
]


# ---------------------------------------------------------------------------
# Formatting. Every string here is what the report prints, so the check can
# look for it verbatim.
# ---------------------------------------------------------------------------

def pct(share, digits=1):
    """Format a 0-1 share as a percent, such as "83.8%"."""
    return f"{share * 100:.{digits}f}%"


def pct_interval(low, high):
    """Format a 0-1 interval as "[77.9%, 89.6%]"."""
    return f"[{pct(low)}, {pct(high)}]"


def points(share):
    """Format a 0-1 difference in points with a sign, such as "+14.4"."""
    value = share * 100
    # Show exact zero without a sign, as the predictions README does
    return "0.0" if round(value, 1) == 0 else f"{value:+.1f}"


def points_interval(low, high):
    """Format a 0-1 difference interval as "[+6.2, +23.7]"."""
    return f"[{points(low)}, {points(high)}]"


def prob(value):
    """Format a probability to two decimals, such as "0.66"."""
    return f"{value:.2f}"


def nominees(row):
    """The nominee pair as the report prints it."""
    return f"{row['dem_name']} (D) vs. {row['rep_name']} (R)"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_frozen(predictions_dir=PREDICTIONS_DIR):
    """Read the four frozen prediction files.

    Parameters
    ----------
    predictions_dir : pathlib.Path
        Folder holding the files named in `FROZEN_FILES`.

    Returns
    -------
    dict
        Keys "simple" and "model" (DataFrames), "evaluation" and
        "supplementary" (parsed JSON).
    """
    paths = {key: Path(predictions_dir) / name for key, name in FROZEN_FILES.items()}
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Frozen prediction files not found: {missing}")
    return {
        "simple": pd.read_csv(paths["simple"]),
        "model": pd.read_csv(paths["model"]),
        "evaluation": json.loads(paths["evaluation"].read_text(encoding="utf-8")),
        "supplementary": json.loads(paths["supplementary"].read_text(encoding="utf-8")),
    }


def model_with_ratings(frozen):
    """The 2026 model rows with Cook's rating joined from the simple file.

    Parameters
    ----------
    frozen : dict
        Output of `load_frozen`.

    Returns
    -------
    pandas.DataFrame
        One row per modeled race, with `cook_rating` added.
    """
    ratings = frozen["simple"][["race_id", "cook_rating"]]
    merged = frozen["model"].merge(ratings, on="race_id", how="left", validate="one_to_one")
    if merged["cook_rating"].isna().any():
        raise ValueError("A modeled race has no row in the simple file.")
    return merged


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

def simple_rule_summary(simple):
    """Counts for the money rule versus Cook, and the full disagreement list.

    Parameters
    ----------
    simple : pandas.DataFrame
        The frozen simple predictions.

    Returns
    -------
    dict
    """
    d_vs_r = simple[simple["race_type"] == "D_vs_R"]
    # money_and_cook_agree is True/False when both rules made a call, empty otherwise
    both_called = d_vs_r[d_vs_r["money_and_cook_agree"].notna()]
    agree = both_called["money_and_cook_agree"].astype(str) == "True"
    disagreements = both_called[~agree].sort_values("race_id")
    return {
        "n_races": len(simple),
        "race_types": {key: int(n) for key, n in simple["race_type"].value_counts().items()},
        "n_d_vs_r": len(d_vs_r),
        "cook_toss_ups": int((d_vs_r["cook_rating"] == "Toss Up").sum()),
        "money_abstentions": int(d_vs_r["money_leader_party"].isna().sum()),
        "both_called": len(both_called),
        "agree": int(agree.sum()),
        "disagree": len(disagreements),
        "disagree_money_leader": {
            key: int(n) for key, n in disagreements["money_leader_party"].value_counts().items()},
        "disagreements": [
            {"race_id": row["race_id"], "nominees": nominees(row),
             "money_leader": PARTY_NAMES[row["money_leader_party"]],
             "dem_money_share": float(row["dem_money_share"]),
             "cook_rating": row["cook_rating"]}
            for _, row in disagreements.iterrows()
        ],
    }


def evaluation_summary(evaluation, supplementary):
    """Held-out accuracy, intervals, coverage, and the money contribution check.

    Parameters
    ----------
    evaluation : dict
        The frozen model evaluation.
    supplementary : dict
        The dated paired bootstrap of what money adds.

    Returns
    -------
    dict
    """
    pooled = evaluation["evaluation"]["pooled"]
    overall, competitive = pooled["overall"], pooled["competitive"]
    boot = competitive["bootstrap_95"]
    folds = {fold["test_cycle"]: fold for fold in evaluation["evaluation"]["folds"]}

    def scores(block, name):
        entry = block[name]
        result = {"n_called": entry["n_called"], "n_races": entry["n_races"],
                  "coverage": entry["coverage"], "accuracy": entry["accuracy"]}
        if "brier" in entry:
            result["brier"] = entry["brier"]
        return result

    predictors = ("model", "model_without_money", "money_rule", "cook")
    return {
        "overall": {name: scores(overall, name) for name in predictors},
        "competitive": {
            name: {**scores(competitive, name), **({"interval": boot[name]} if name in boot else {})}
            for name in predictors
        },
        "competitive_by_cycle": {
            str(cycle): {"n_races": fold["competitive"]["n_races"],
                         "model_accuracy": fold["competitive"]["model"]["accuracy"]}
            for cycle, fold in sorted(folds.items())
        },
        "shared": {
            "n_races": competitive["shared"]["n_races"],
            "model": {"accuracy": competitive["shared"]["model_accuracy"], "interval": boot["shared"]["model"]},
            "money_rule": {"accuracy": competitive["shared"]["money_rule_accuracy"],
                           "interval": boot["shared"]["money_rule"]},
            "cook": {"accuracy": competitive["shared"]["cook_accuracy"], "interval": boot["shared"]["cook"]},
        },
        "paired_difference": {
            key: boot["paired_difference"][key] for key in ("model_minus_money_rule", "model_minus_cook")
        },
        "calibration_competitive": competitive["model"]["calibration"],
        "money_contribution": {
            "resamples": supplementary["bootstrap"]["resamples"],
            "seed": supplementary["bootstrap"]["seed"],
            "competitive": supplementary["competitive"],
            "all_races": supplementary["all_races"],
        },
    }


def coefficient_summary(evaluation):
    """The full-fit coefficients and the plain-words money effect.

    Parameters
    ----------
    evaluation : dict

    Returns
    -------
    dict
    """
    fit = evaluation["full_fit"]
    coefficients = fit["coefficients"]
    effect = fit["money_share_effect"]
    return {
        "n_train": fit["n_train"],
        "raw": {key: value for key, value in coefficients.items() if key != "standardized"},
        "standardized": coefficients["standardized"],
        # exp(coefficient) is the odds multiplier for one unit of the input
        "odds_per_pvi_point": math.exp(coefficients["dem_pvi"]),
        "odds_incumbency": math.exp(coefficients["incumbency"]),
        "odds_per_10_points_money": effect["odds_ratio_per_10_points"],
        "pvi_vs_money_sd_ratio": coefficients["standardized"]["dem_pvi"]
                                 / coefficients["standardized"]["dem_money_share"],
        "shift_open_even": effect["probability_shift_45_to_55"]["open seat, EVEN PVI"],
        "shift_training_medians": effect["probability_shift_45_to_55"]["training medians"],
    }


def predictions_2026_summary(frozen):
    """Counts and race lists for the 2026 model predictions.

    Parameters
    ----------
    frozen : dict
        Output of `load_frozen`.

    Returns
    -------
    dict
    """
    rows = model_with_ratings(frozen)
    rows["dem_called"] = rows["dem_win_probability"] > 0.5
    rows["distance_from_even"] = (rows["dem_win_probability"] - 0.5).abs()

    # Model versus Cook: both named a party and they differ
    has_cook = rows["cook_favorite_party"].notna()
    model_party = rows["dem_called"].map({True: "DEM", False: "REP"})
    vs_cook = rows[has_cook & (model_party != rows["cook_favorite_party"])].sort_values("race_id")
    frozen_vs_cook = frozen["evaluation"]["predictions_2026"]["model_vs_cook"]
    if sorted(vs_cook["race_id"]) != sorted(row["race_id"] for row in frozen_vs_cook):
        raise ValueError("Model versus Cook list does not match model-evaluation.json.")

    toss_ups = rows[rows["cook_rating"] == "Toss Up"]
    with_incumbent = toss_ups[toss_ups["incumbency"] != 0]
    # The model favors the incumbent's party when its call matches the incumbency sign
    incumbent_favored = (with_incumbent["dem_called"] == (with_incumbent["incumbency"] == 1)).sum()

    closest = rows.sort_values("distance_from_even").head(4)
    near_even = rows[(rows["dem_win_probability"] > 0.4) & (rows["dem_win_probability"] < 0.6)]
    confident_toss_ups = toss_ups[toss_ups["dem_win_probability"] < 0.15].sort_values("dem_win_probability")
    return {
        "n_races": len(rows),
        "excluded_third_party": int(
            ((frozen["simple"]["race_type"] == "D_vs_R")
             & (frozen["simple"]["third_party_outraised"].astype(str) == "True")).sum()),
        "dem_called": int(rows["dem_called"].sum()),
        "rep_called": int((~rows["dem_called"]).sum()),
        "incumbency": {"dem": int((rows["incumbency"] == 1).sum()),
                       "rep": int((rows["incumbency"] == -1).sum()),
                       "open": int((rows["incumbency"] == 0).sum())},
        "between_40_and_60": len(near_even),
        "closest": [
            {"race_id": row["race_id"], "nominees": nominees(row),
             "dem_win_probability": float(row["dem_win_probability"]),
             "dem_money_share": float(row["dem_money_share"]),
             "incumbency": int(row["incumbency"]), "dem_pvi": int(row["dem_pvi"]),
             "cook_rating": row["cook_rating"]}
            for _, row in closest.iterrows()
        ],
        "toss_ups": {
            "n": len(toss_ups),
            "dem_called": int(toss_ups["dem_called"].sum()),
            "rep_called": int((~toss_ups["dem_called"]).sum()),
            "with_incumbent": len(with_incumbent),
            "dem_incumbent": int((with_incumbent["incumbency"] == 1).sum()),
            "rep_incumbent": int((with_incumbent["incumbency"] == -1).sum()),
            "incumbent_party_favored": int(incumbent_favored),
            "open": int((toss_ups["incumbency"] == 0).sum()),
            "open_dem_called": sorted(toss_ups[(toss_ups["incumbency"] == 0) & toss_ups["dem_called"]]["race_id"]),
            "open_rep_called": int(((toss_ups["incumbency"] == 0) & ~toss_ups["dem_called"]).sum()),
            "below_015": [{"race_id": row["race_id"], "dem_win_probability": float(row["dem_win_probability"])}
                          for _, row in confident_toss_ups.iterrows()],
        },
        "model_vs_cook": [
            {"race_id": row["race_id"], "nominees": nominees(row),
             "dem_win_probability": float(row["dem_win_probability"]),
             "incumbency": int(row["incumbency"]), "cook_rating": row["cook_rating"]}
            for _, row in vs_cook.iterrows()
        ],
        "model_vs_money_rule": len(frozen["evaluation"]["predictions_2026"]["model_vs_money_rule"]),
        "money_record_missing": int(frozen["model"]["money_record_missing"].astype(str).eq("True").sum()),
    }


def cited_strings(numbers):
    """The exact text the report uses for each number, keyed by a short name.

    Keeping these next to the raw values means the check does not have to
    guess how a number was rounded in the prose.

    Parameters
    ----------
    numbers : dict
        The raw numbers from `collect_numbers`.

    Returns
    -------
    dict of str
    """
    simple, ev, coef, pred = numbers["simple"], numbers["evaluation"], numbers["coefficients"], numbers["predictions_2026"]
    comp, overall, shared = ev["competitive"], ev["overall"], ev["shared"]
    diff, contrib = ev["paired_difference"], ev["money_contribution"]
    cited = {
        "money_date": f"FEC data as of {numbers['money_pulled_at']}",
        "tag_simple": f"`pre-election-simple` at commit `{numbers['tags']['pre-election-simple']}`",
        "tag_model": f"`pre-election-model` at commit `{numbers['tags']['pre-election-model']}`",
        "simple_races": f"{simple['n_races']} races",
        "simple_d_vs_r": f"{simple['n_d_vs_r']} Democrat versus Republican",
        "simple_toss_ups": f"{simple['cook_toss_ups']} Toss Ups",
        "simple_both_called": f"{simple['both_called']} races",
        "simple_agree": f"same party in {simple['agree']}",
        "simple_disagree": f"different parties in {simple['disagree']}",
        "simple_disagree_dem": f"{simple['disagree_money_leader'].get('DEM', 0)} of the {simple['disagree']}",
        "simple_disagree_rep": f"{simple['disagree_money_leader'].get('REP', 0)} (NV-01)",
        "overall_races": f"{overall['model']['n_called']} held-out races",
        "overall_model": pct(overall["model"]["accuracy"]),
        "overall_model_brier": f"{overall['model']['brier']:.3f}",
        "overall_money_rule": pct(overall["money_rule"]["accuracy"]),
        "overall_cook": pct(overall["cook"]["accuracy"]),
        "overall_cook_called": f"{overall['cook']['n_called']} of {overall['cook']['n_races']}",
        "overall_cook_coverage": pct(overall["cook"]["coverage"]),
        "competitive_races": f"{comp['model']['n_races']} competitive races",
        "competitive_model": f"{pct(comp['model']['accuracy'])} {pct_interval(**comp['model']['interval'])}",
        "competitive_model_brier": f"{comp['model']['brier']:.3f}",
        "competitive_without_money": pct(comp["model_without_money"]["accuracy"]),
        "competitive_without_money_brier": f"{comp['model_without_money']['brier']:.3f}",
        "competitive_money_rule": f"{pct(comp['money_rule']['accuracy'])} {pct_interval(**comp['money_rule']['interval'])}",
        "competitive_cook": f"{pct(comp['cook']['accuracy'])} {pct_interval(**comp['cook']['interval'])}",
        "competitive_cook_called": f"{comp['cook']['n_called']} of {comp['cook']['n_races']}",
        "competitive_cook_coverage": pct(comp["cook"]["coverage"]),
        "competitive_cook_abstained": f"{comp['cook']['n_races'] - comp['cook']['n_called']} Toss Ups",
        "shared_races": f"{shared['n_races']} competitive races where all three",
        "shared_model": pct(shared["model"]["accuracy"]),
        "shared_money_rule": pct(shared["money_rule"]["accuracy"]),
        "shared_cook": pct(shared["cook"]["accuracy"]),
        "diff_money_rule": f"{points(diff['model_minus_money_rule']['estimate'])} points",
        "diff_money_rule_interval": points_interval(diff["model_minus_money_rule"]["low"],
                                                    diff["model_minus_money_rule"]["high"]),
        "diff_cook": f"{points(diff['model_minus_cook']['estimate'])} points",
        "diff_cook_interval": points_interval(diff["model_minus_cook"]["low"], diff["model_minus_cook"]["high"]),
        "contrib_resamples": f"{contrib['resamples']:,} draws",
        "contrib_seed": f"seed {contrib['seed']}",
        "contrib_comp_brier": (f"{contrib['competitive']['brier_without_minus_with']['estimate']:.3f} "
                               f"[{contrib['competitive']['brier_without_minus_with']['low']:.3f}, "
                               f"{contrib['competitive']['brier_without_minus_with']['high']:.3f}]"),
        "contrib_comp_accuracy": (f"{points(contrib['competitive']['accuracy_with_minus_without']['estimate'])} points "
                                  + points_interval(contrib["competitive"]["accuracy_with_minus_without"]["low"],
                                                    contrib["competitive"]["accuracy_with_minus_without"]["high"])),
        "contrib_all_brier": (f"{contrib['all_races']['brier_without_minus_with']['estimate']:.4f} "
                              f"[{contrib['all_races']['brier_without_minus_with']['low']:.4f}, "
                              f"{contrib['all_races']['brier_without_minus_with']['high']:.4f}]"),
        "contrib_all_accuracy": (f"{points(contrib['all_races']['accuracy_with_minus_without']['estimate'])} points "
                                 + points_interval(contrib["all_races"]["accuracy_with_minus_without"]["low"],
                                                   contrib["all_races"]["accuracy_with_minus_without"]["high"])),
        "coef_n_train": f"{coef['n_train']} training races",
        "coef_pvi_sd_ratio": f"about {coef['pvi_vs_money_sd_ratio']:.1f} times",
        "coef_pvi_odds": f"about {coef['odds_per_pvi_point']:.2f}",
        "coef_incumbency_odds": f"about {coef['odds_incumbency']:.1f}",
        "coef_money_odds": f"about {coef['odds_per_10_points_money']:.2f}",
        "shift_open_even": (f"from {pct(coef['shift_open_even']['p_at_45_pct'])} "
                            f"to {pct(coef['shift_open_even']['p_at_55_pct'])}"),
        "shift_medians": (f"from {pct(coef['shift_training_medians']['p_at_45_pct'])} "
                          f"to {pct(coef['shift_training_medians']['p_at_55_pct'])}"),
        "pred_races": f"{pred['n_races']} races",
        "pred_excluded": f"{pred['excluded_third_party']} races where a third-party",
        "pred_dem_called": f"Democrat in {pred['dem_called']}",
        "pred_rep_called": f"Republican in {pred['rep_called']}",
        "pred_incumbency": (f"{pred['incumbency']['dem']} Democratic incumbents, "
                            f"{pred['incumbency']['rep']} Republican incumbents, and {pred['incumbency']['open']} open seats"),
        "pred_near_even": f"{pred['between_40_and_60']} races",
        "pred_toss_ups": f"{pred['toss_ups']['n']} Toss Ups",
        "pred_toss_up_calls": (f"Republican in {pred['toss_ups']['rep_called']} "
                               f"and the Democrat in {pred['toss_ups']['dem_called']}"),
        "pred_toss_up_incumbents": (f"{pred['toss_ups']['with_incumbent']} Toss Ups with an incumbent "
                                    f"({pred['toss_ups']['rep_incumbent']} Republican, "
                                    f"{pred['toss_ups']['dem_incumbent']} Democratic)"),
        "pred_toss_up_open": f"{pred['toss_ups']['open']} open-seat Toss Ups",
        "pred_toss_up_open_calls": (f"Democrat in {len(pred['toss_ups']['open_dem_called'])} "
                                    f"({' and '.join(pred['toss_ups']['open_dem_called'])}) "
                                    f"and the Republican in {pred['toss_ups']['open_rep_called']}"),
        "pred_confident_toss_ups": f"the {len(pred['toss_ups']['below_015'])} below 0.15",
        "pred_vs_cook": f"different parties in {len(pred['model_vs_cook'])}",
        "pred_vs_money_rule": f"{pred['model_vs_money_rule']} races",
        "pred_missing_money": f"{pred['money_record_missing']} races",
    }
    for bin_row in ev["calibration_competitive"]:
        cited[f"calibration_{bin_row['bin']}"] = (
            f"| {bin_row['bin'].replace('-', ' to ')} | {bin_row['count']} | "
            f"{bin_row['mean_predicted']:.2f} | {bin_row['observed_rate']:.2f} |")
    for row in simple["disagreements"]:
        cited[f"disagree_{row['race_id']}"] = (
            f"| {row['race_id']} | {row['nominees']} | {row['money_leader']} | {pct(row['dem_money_share'])} "
            f"| {row['cook_rating']} |")
    for row in pred["closest"]:
        cited[f"closest_{row['race_id']}"] = f"{row['race_id']} ({prob(row['dem_win_probability'])}"
    for row in pred["model_vs_cook"]:
        cited[f"vs_cook_{row['race_id']}"] = (
            f"| {row['race_id']} | {row['nominees']} | {prob(row['dem_win_probability'])} | {row['cook_rating']} |")
    for row in pred["toss_ups"]["below_015"]:
        cited[f"confident_toss_up_{row['race_id']}"] = f"{row['race_id']} ({prob(row['dem_win_probability'])})"
    return cited


def collect_numbers(frozen):
    """Gather every number the report cites, raw and as printed.

    Parameters
    ----------
    frozen : dict
        Output of `load_frozen`.

    Returns
    -------
    dict
    """
    numbers = {
        "sources": {key: f"reports/predictions/{name}" for key, name in FROZEN_FILES.items()},
        "money_pulled_at": frozen["evaluation"]["predictions_2026"]["money_pulled_at"],
        "tags": TAGS,
        "simple": simple_rule_summary(frozen["simple"]),
        "evaluation": evaluation_summary(frozen["evaluation"], frozen["supplementary"]),
        "coefficients": coefficient_summary(frozen["evaluation"]),
        "predictions_2026": predictions_2026_summary(frozen),
    }
    if numbers["money_pulled_at"] != MONEY_PULLED_AT:
        raise ValueError(f"Expected money pulled {MONEY_PULLED_AT}, got {numbers['money_pulled_at']}.")
    numbers["cited"] = cited_strings(numbers)
    return numbers


def round_floats(value, digits=6):
    """Round every float in a nested structure, for a readable JSON file."""
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, dict):
        return {key: round_floats(item, digits) for key, item in value.items()}
    if isinstance(value, list):
        return [round_floats(item, digits) for item in value]
    return value


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def new_figure(title, subtitle, size=(10, 5.2), top=0.8):
    """A figure with a left-aligned title and a data-date subtitle.

    Section 1's `new_figure` hard-codes "FEC data as of", which is wrong for
    the evaluation charts, so this version takes the subtitle as text.

    Parameters
    ----------
    title : str
    subtitle : str
    size : tuple of float
        Figure size in inches.
    top : float
        Top of the plot area, as a share of the figure height.

    Returns
    -------
    tuple of (matplotlib.figure.Figure, matplotlib.axes.Axes)
    """
    fig, ax = plt.subplots(figsize=size, facecolor=SURFACE)
    fig.subplots_adjust(left=0.08, right=0.97, top=top, bottom=0.14)
    fig.text(0.02, 0.965, title, fontsize=15, fontweight="bold", color=TEXT_PRIMARY, va="top")
    fig.text(0.02, 0.965 - 0.4 / size[1], subtitle, fontsize=11.5, color=TEXT_SECONDARY, va="top")
    return fig, ax


def save(fig, figures_dir, name):
    """Write a figure as a PNG and close it."""
    path = Path(figures_dir) / name
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    print(f"Wrote {path}")


def plot_competitive_accuracy(numbers, figures_dir):
    """Held-out competitive accuracy with 95% intervals and coverage, per predictor.

    Two groups of rows: every competitive race, then the races where all
    three predictors made a call. Cook's coverage is printed next to its
    interval so a reader sees that it abstains on Toss Ups.
    """
    ev = numbers["evaluation"]
    comp, shared = ev["competitive"], ev["shared"]
    n_comp = comp["model"]["n_races"]
    rows = [
        # (group, label, accuracy, interval, coverage note)
        (f"All {n_comp} competitive races", "Model", comp["model"],
         f"called {comp['model']['n_called']} of {n_comp} (100%)"),
        (None, "Money rule", comp["money_rule"], f"called {comp['money_rule']['n_called']} of {n_comp} (100%)"),
        (None, "Cook favorite", comp["cook"],
         f"called {comp['cook']['n_called']} of {n_comp} ({pct(comp['cook']['coverage'], 0)}),\n"
         f"abstains on {n_comp - comp['cook']['n_called']} Toss Ups"),
        (f"The {shared['n_races']} races where all three made a call", "Model", shared["model"], None),
        (None, "Money rule", shared["money_rule"], None),
        (None, "Cook favorite", shared["cook"], None),
    ]

    note_x = 108  # data units, right of the 100% gridline
    fig, ax = new_figure("Held-out accuracy in competitive House races",
                         f"{HELD_OUT_LABEL}. Dots are accuracy, lines are bootstrap 95% intervals.",
                         size=(10, 5.6), top=0.83)
    fig.subplots_adjust(left=0.17, right=0.97, bottom=0.12)
    # Leave a blank slot above each group for its heading
    positions, y = [], 0
    for group, *_ in rows:
        if group is not None:
            y += 1
        positions.append(y)
        y += 1
    positions = [y - p for p in positions]  # first row at the top

    for pos, (group, label, entry, note) in zip(positions, rows):
        low, high = entry["interval"]["low"] * 100, entry["interval"]["high"] * 100
        acc = entry["accuracy"] * 100
        ax.plot([low, high], [pos, pos], color=GRAY, linewidth=2, solid_capstyle="round")
        ax.scatter([acc], [pos], s=70, color=NEUTRAL, zorder=3, edgecolor=SURFACE, linewidth=2)
        ax.text(high + 0.8, pos, f"{acc:.1f}%", va="center", fontsize=11.5,
                color=TEXT_PRIMARY, fontweight="bold")
        if note:
            # A fixed column to the right of every interval, so no note can
            # run into an accuracy label
            ax.text(note_x, pos, note, va="center", fontsize=10.5, color=TEXT_SECONDARY, linespacing=1.3)
        if group:
            ax.text(55, pos + 0.95, group, va="center", fontsize=11.5, color=TEXT_PRIMARY, fontweight="bold")

    ax.set_yticks(positions, [row[1] for row in rows], fontsize=11.5, color=TEXT_PRIMARY)
    ax.text(note_x, max(positions) + 0.95, "Coverage", va="center", fontsize=11.5,
            color=TEXT_PRIMARY, fontweight="bold")
    ax.set_xlim(55, 130)
    ax.set_xticks(range(60, 101, 10))
    ax.set_ylim(min(positions) - 0.7, max(positions) + 1.5)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    style_axes(ax)
    ax.spines["bottom"].set_bounds(55, 100)
    add_note(fig, "Competitive = Cook Toss Up, Lean or Likely in that cycle. "
                  "Model trained on one cycle and scored on the other.")
    save(fig, figures_dir, "competitive_accuracy.png")


def plot_win_probability_vs_money(frozen, figures_dir):
    """2026 model win probability against Democratic money share, by incumbency.

    Cook Toss Ups get a ring, so a reader can see how far some of them sit
    from 50%.
    """
    rows = model_with_ratings(frozen)
    fig, ax = new_figure("2026 model: Democratic win probability and money share",
                         f"FEC data as of {MONEY_PULLED_AT}. {len(rows)} Democrat versus Republican "
                         "House races, predictions tagged before election day.",
                         size=(10, 6.6), top=0.8)
    fig.subplots_adjust(left=0.1, bottom=0.13)
    for value, label, color, marker in INCUMBENCY_GROUPS:
        group = rows[rows["incumbency"] == value]
        ax.scatter(group["dem_money_share"] * 100, group["dem_win_probability"] * 100, s=34,
                   color=color, marker=marker, alpha=0.85, edgecolor=SURFACE, linewidth=0.8, zorder=3)
    toss_ups = rows[rows["cook_rating"] == "Toss Up"]
    ax.scatter(toss_ups["dem_money_share"] * 100, toss_ups["dem_win_probability"] * 100, s=150,
               facecolor="none", edgecolor=TEXT_PRIMARY, linewidth=1.2, zorder=4)

    # Label the most confident Toss Up, the one the write-up discusses first
    tx15 = toss_ups.loc[toss_ups["dem_win_probability"].idxmin()]
    ax.annotate(f"{tx15['race_id']} (Toss Up)", (tx15["dem_money_share"] * 100, tx15["dem_win_probability"] * 100),
                xytext=(30, 30), textcoords="data", ha="center", fontsize=10.5, color=TEXT_PRIMARY,
                arrowprops={"arrowstyle": "-", "color": TEXT_SECONDARY, "linewidth": 1})

    for ref in ("x", "y"):
        line = ax.axvline if ref == "x" else ax.axhline
        line(50, color=TEXT_SECONDARY, linewidth=1, linestyle=(0, (4, 3)), zorder=1)
    style_axes(ax)
    ax.spines["left"].set_visible(True)
    ax.spines["left"].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.tick_params(axis="y", colors=TEXT_SECONDARY, labelsize=11, length=0)
    ax.set_xlim(-2, 102)
    ax.set_ylim(-3, 103)
    pct_format = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%")
    ax.xaxis.set_major_formatter(pct_format)
    ax.yaxis.set_major_formatter(pct_format)
    ax.set_xlabel("Democrat's share of the two nominees' money", fontsize=11.5, color=TEXT_PRIMARY)
    ax.set_ylabel("Model's probability the Democrat wins", fontsize=11.5, color=TEXT_PRIMARY)

    handles = [Line2D([], [], linestyle="none", marker=marker, color=color, markersize=8, label=label)
               for _, label, color, marker in INCUMBENCY_GROUPS]
    handles.append(Line2D([], [], linestyle="none", marker="o", markerfacecolor="none",
                          markeredgecolor=TEXT_PRIMARY, markersize=11, label="Cook Toss Up"))
    fig.legend(handles=handles, loc="upper left", ncol=4, bbox_to_anchor=(0.015, 0.965 - 0.72 / 6.6),
               frameon=False, fontsize=11, handletextpad=0.4, columnspacing=1.4, labelcolor=TEXT_PRIMARY)
    add_note(fig, "Money = donor, PAC and party money, never the candidate's own. "
                  "Dashed lines mark 50%.")
    save(fig, figures_dir, "win_probability_vs_money.png")


def plot_competitive_calibration(numbers, figures_dir):
    """Held-out calibration on competitive races: predicted versus observed."""
    bins = numbers["evaluation"]["calibration_competitive"]
    fig, ax = new_figure("Held-out calibration in competitive House races",
                         f"{HELD_OUT_LABEL}. Each dot is one probability bin.",
                         size=(8, 6.6), top=0.84)
    fig.subplots_adjust(left=0.13, right=0.95, bottom=0.14)
    ax.plot([0, 100], [0, 100], color=TEXT_SECONDARY, linewidth=1, linestyle=(0, (4, 3)), zorder=1)
    ax.text(77, 70, "Perfect calibration", fontsize=10.5, color=TEXT_SECONDARY, rotation=45,
            rotation_mode="anchor", ha="center")
    for row in bins:
        x, y = row["mean_predicted"] * 100, row["observed_rate"] * 100
        ax.scatter([x], [y], s=80, color=NEUTRAL, edgecolor=SURFACE, linewidth=2, zorder=3)
        ax.annotate(f"{row['count']} races", (x, y), xytext=(-12, 9), textcoords="offset points",
                    fontsize=10.5, color=TEXT_PRIMARY, ha="right")
    style_axes(ax)
    ax.spines["left"].set_visible(True)
    ax.spines["left"].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.tick_params(axis="y", colors=TEXT_SECONDARY, labelsize=11, length=0)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    pct_format = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%")
    ax.xaxis.set_major_formatter(pct_format)
    ax.yaxis.set_major_formatter(pct_format)
    ax.set_xlabel("Average predicted Democratic win probability", fontsize=11.5, color=TEXT_PRIMARY)
    ax.set_ylabel("Share of races Democrats won", fontsize=11.5, color=TEXT_PRIMARY)
    add_note(fig, "Bins are 0-20%, 20-40%, 40-60%, 60-80% and 80-100% predicted. "
                  "Small bins are noisy.")
    save(fig, figures_dir, "competitive_calibration.png")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args():
    """Read the input and output folders."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--predictions-dir", type=Path, default=PREDICTIONS_DIR,
                        help="Folder with the frozen prediction files (read only)")
    parser.add_argument("--figures-dir", type=Path, default=FIGURES_DIR,
                        help="Folder to write the charts and numbers file")
    return parser.parse_args()


def build(predictions_dir=PREDICTIONS_DIR):
    """Load the frozen files and return the rounded numbers, without writing anything.

    Parameters
    ----------
    predictions_dir : pathlib.Path

    Returns
    -------
    tuple of (dict, dict)
        The frozen inputs and the JSON-ready numbers.
    """
    frozen = load_frozen(predictions_dir)
    return frozen, round_floats(collect_numbers(frozen))


def main():
    """Build every chart and the numbers file."""
    args = parse_args()
    frozen, numbers = build(args.predictions_dir)
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    plot_competitive_accuracy(numbers, args.figures_dir)
    plot_win_probability_vs_money(frozen, args.figures_dir)
    plot_competitive_calibration(numbers, args.figures_dir)

    path = args.figures_dir / "money_winning_numbers.json"
    path.write_text(json.dumps(numbers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
