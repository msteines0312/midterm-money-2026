"""A race-level win model for House generals, trained on 2022 and 2024.

One row per Democrat versus Republican race. A logistic regression predicts
the probability that the Democrat wins from three inputs: the Democrat's share
of the two nominees' external money, who the incumbent is, and the district's
Cook PVI oriented toward Democrats. This is prediction, not cause: money flows
to candidates who were already likely to win, so a money coefficient says
money share carries information, not that spending moved votes.

Evaluation holds out one cycle at a time (train 2022 and test 2024, then the
reverse) and compares the model with the two simple rules from
`src/predict/simple.py`: the money leader and the Cook favorite.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from src.history_results import dem_vs_rep_races
from src.predict.simple import PARTY_CODES, _cook_favorite, _money_share

FEATURES = ["dem_money_share", "incumbency", "dem_pvi"]
FEATURES_WITHOUT_MONEY = ["incumbency", "dem_pvi"]

FRAME_COLUMNS = [
    "cycle", "race_id", "dem_money_share", "incumbency", "dem_pvi",
    "cook_rating", "rating_source", "cook_favorite_party", "dem_won",
]

# Ratings that make a race competitive for the competitive-only scoring.
# Solid seats (listed or inferred) are almost always called correctly by
# everyone, so overall accuracy mostly measures how many safe seats there are.
COMPETITIVE_RATINGS = {"Toss Up", "Lean D", "Lean R", "Likely D", "Likely R"}

CALIBRATION_BINS = 5


# Building the race table

def _major_party(party):
    """DEM, REP, or OTHER, with the same Democratic variants as the 2026 code.

    history_results already stores DEM and REP for the major parties, but a
    Wikipedia label such as "DFL" is mapped through `PARTY_CODES` in case one
    slips through.
    """
    if party in ("DEM", "REP"):
        return party
    return PARTY_CODES.get(party, "OTHER")


def _dem_pvi(cook_pvi):
    """Cook PVI as a number oriented toward Democrats: D+5 is 5, R+5 is -5, EVEN is 0."""
    if cook_pvi == "EVEN":
        return 0
    lean, points = cook_pvi.split("+")
    if lean not in ("D", "R"):
        raise ValueError(f"Unexpected Cook PVI: {cook_pvi!r}")
    return int(points) if lean == "D" else -int(points)


def _load_nominees(conn, cycles):
    """General election nominees joined to their pre-general money.

    `has_money` is False when the nominee has no history_money row (no FEC
    candidate ID, or no report on file). That is a data gap, not $0. Money is
    looked up per candidate ID and never summed across candidates, because a
    committee that is principal for two IDs appears once under each.
    """
    placeholders = ",".join("?" for _ in cycles)
    sql = f"""
        SELECT r.cycle, r.race_id, r.candidate_id, r.name, r.party, r.won, r.is_incumbent,
               m.external_contributions, m.candidate_id IS NOT NULL AS has_money
        FROM history_results r
        LEFT JOIN history_money m ON m.cycle = r.cycle AND m.candidate_id = r.candidate_id
        WHERE r.cycle IN ({placeholders})
    """
    frame = pd.read_sql_query(sql, conn, params=list(cycles))
    frame["major"] = frame["party"].map(_major_party)
    frame["has_money"] = frame["has_money"].astype(bool)
    # Negative totals (refunds larger than receipts) are floored at 0
    frame["money"] = frame["external_contributions"].fillna(0).clip(lower=0)
    return frame


def _load_races(conn, cycles):
    """Cook PVI and rating by (cycle, race_id)."""
    placeholders = ",".join("?" for _ in cycles)
    frame = pd.read_sql_query(
        f"SELECT * FROM history_races WHERE cycle IN ({placeholders})", conn, params=list(cycles)
    )
    return {(row.cycle, row.race_id): row for row in frame.itertuples()}


def _incumbency(dem, rep):
    """1 for a Democratic incumbent, -1 for a Republican one, 0 for an open seat.

    Two incumbents (member versus member after redistricting) also count as
    0, since neither side has the advantage alone.
    """
    if dem["is_incumbent"] and rep["is_incumbent"]:
        return 0
    if dem["is_incumbent"]:
        return 1
    return -1 if rep["is_incumbent"] else 0


def _exclusion(dem, rep, others):
    """Why a D vs R race is left out of the model, or None when it stays in.

    A third party counts as outraising when it beats at least one major
    nominee, the same test as `third_party_outraised` for 2026.
    """
    missing = [nominee["name"] for nominee in (dem, rep) if not nominee["has_money"]]
    if missing:
        return "missing_money: " + ", ".join(missing)
    if (others["money"] > min(dem["money"], rep["money"])).any():
        return "third_party_outraised"
    return None


def _race_row(race_nominees, race_info):
    """One row of the race table for one D vs R race."""
    dem = race_nominees[race_nominees["major"] == "DEM"].iloc[0]
    rep = race_nominees[race_nominees["major"] == "REP"].iloc[0]
    others = race_nominees[race_nominees["major"] == "OTHER"]
    return {
        "cycle": int(dem["cycle"]),
        "race_id": dem["race_id"],
        "dem_name": dem["name"],
        "rep_name": rep["name"],
        "dem_money": dem["money"],
        "rep_money": rep["money"],
        # None when both nominees raised $0, which leaves the share undefined
        "dem_money_share": _money_share(dem["money"], rep["money"]),
        "incumbency": _incumbency(dem, rep),
        "both_incumbents": bool(dem["is_incumbent"] and rep["is_incumbent"]),
        "dem_pvi": _dem_pvi(race_info.cook_pvi),
        "cook_rating": race_info.cook_rating,
        "rating_source": race_info.rating_source,
        "cook_favorite_party": _cook_favorite(race_info.cook_rating),
        "dem_won": int(dem["won"]),
        "exclusion": _exclusion(dem, rep, others),
    }


def race_table(conn, cycles):
    """Every D vs R race in the given cycles, with the reason any is excluded.

    A D vs R race has exactly one Democratic and one Republican nominee;
    third-party candidates may also be on the ballot.

    Parameters
    ----------
    conn : sqlite3.Connection
    cycles : list of int

    Returns
    -------
    pandas.DataFrame
        The `training_frame` columns plus dem_name, rep_name, dem_money,
        rep_money, both_incumbents, and `exclusion` (None for races the model
        uses, else "missing_money: <names>" or "third_party_outraised").
    """
    nominees = _load_nominees(conn, cycles)
    races = _load_races(conn, cycles)
    rows = []
    for cycle, cycle_nominees in nominees.groupby("cycle"):
        keep = dem_vs_rep_races(cycle_nominees.rename(columns={"party": "raw_party", "major": "party"})
                                .to_dict("records"))
        for race_id in sorted(keep):
            race_nominees = cycle_nominees[cycle_nominees["race_id"] == race_id]
            rows.append(_race_row(race_nominees, races[(cycle, race_id)]))
    table = pd.DataFrame(rows)
    table["dem_money_share"] = table["dem_money_share"].astype(float)
    return table


def training_frame(conn, cycles):
    """One row per D vs R race the model can learn from.

    Races where a major nominee has no money row, or where a third-party or
    independent candidate outraised either major nominee, are dropped. A race
    where both nominees raised $0 stays in with a missing `dem_money_share`:
    the model skips it and the money rule abstains, while Cook is still scored.

    Parameters
    ----------
    conn : sqlite3.Connection
    cycles : list of int

    Returns
    -------
    pandas.DataFrame
        Columns in FRAME_COLUMNS. `incumbency` is 1 for a Democratic
        incumbent, -1 for a Republican one, 0 otherwise. `dem_pvi` is the Cook
        PVI with Democratic leans positive.
    """
    table = race_table(conn, cycles)
    kept = table[table["exclusion"].isna()]
    return kept[FRAME_COLUMNS].reset_index(drop=True)


# Fitting

def fit(frame, features=FEATURES):
    """Fit a logistic regression with scikit-learn's default settings.

    The defaults include a mild L2 penalty (C=1.0). No tuning is done, so the
    held-out scores are not flattered by choices made after seeing them.

    Parameters
    ----------
    frame : pandas.DataFrame
        Rows from `training_frame`. Rows with no money share are skipped.
    features : list of str

    Returns
    -------
    sklearn.linear_model.LogisticRegression
        Fitted on a DataFrame, so `feature_names_in_` records the inputs.
    """
    usable = frame.dropna(subset=features)
    return LogisticRegression().fit(usable[features], usable["dem_won"])


def _predict(model, frame):
    """P(Democrat wins) for each row, NaN where an input is missing."""
    features = list(model.feature_names_in_)
    probabilities = pd.Series(np.nan, index=frame.index)
    usable = frame.dropna(subset=features)
    if len(usable):
        probabilities[usable.index] = model.predict_proba(usable[features])[:, 1]
    return probabilities


def coefficients(model):
    """Intercept and one coefficient per input, in log-odds of a Democratic win.

    Returns
    -------
    dict
    """
    named = dict(zip(model.feature_names_in_, (float(c) for c in model.coef_[0])))
    return {"intercept": float(model.intercept_[0]), **named}


def money_share_effect(model, frame):
    """The money share coefficient in plain numbers.

    Reports the odds ratio for a 10-point rise in money share, each input's
    coefficient times its standard deviation (a standardized effect, so the
    three inputs can be compared), and the change in win probability when
    money share rises from 45% to 55% with the other inputs held fixed.

    Parameters
    ----------
    model : sklearn.linear_model.LogisticRegression
        Fitted with FEATURES.
    frame : pandas.DataFrame
        The training rows, used for standard deviations and typical values.

    Returns
    -------
    dict
    """
    coefs = coefficients(model)
    usable = frame.dropna(subset=FEATURES)
    scenarios = {
        "open seat, EVEN PVI": (0, 0),
        "training medians": (float(usable["incumbency"].median()), float(usable["dem_pvi"].median())),
    }
    shifts = {}
    for label, (incumbency, pvi) in scenarios.items():
        inputs = pd.DataFrame({"dem_money_share": [0.45, 0.55], "incumbency": incumbency, "dem_pvi": pvi})
        low, high = model.predict_proba(inputs[FEATURES])[:, 1]
        shifts[label] = {"incumbency": incumbency, "dem_pvi": pvi,
                         "p_at_45_pct": float(low), "p_at_55_pct": float(high),
                         "change": float(high - low)}
    return {
        "odds_ratio_per_10_points": float(np.exp(0.1 * coefs["dem_money_share"])),
        "standardized_coefficients": {f: float(coefs[f] * usable[f].std()) for f in FEATURES},
        "probability_shift_45_to_55": shifts,
    }


# Scoring

def _party_call(values, threshold=0.5):
    """DEM above the threshold, REP below, None at it or when missing."""
    return values.map(lambda v: None if pd.isna(v) or v == threshold else ("DEM" if v > threshold else "REP"))


def _rule_metrics(calls, actual):
    """Coverage and accuracy for one predictor over a set of races.

    Abstentions (None) lower coverage but never count as misses.
    """
    called = calls.notna()
    n_called = int(called.sum())
    correct = int((calls[called] == actual[called]).sum())
    return {
        "n_races": int(len(calls)),
        "n_called": n_called,
        "coverage": n_called / len(calls) if len(calls) else None,
        "accuracy": correct / n_called if n_called else None,
    }


def _calibration(probabilities, outcomes):
    """Count, mean prediction, and observed Democratic win rate in 5 equal-width bins."""
    # A probability of exactly 1.0 belongs in the top bin, not a sixth one
    bins = np.minimum((probabilities * CALIBRATION_BINS).astype(int), CALIBRATION_BINS - 1)
    table = []
    for b in range(CALIBRATION_BINS):
        in_bin = bins == b
        count = int(in_bin.sum())
        table.append({
            "bin": f"{b / CALIBRATION_BINS:.1f}-{(b + 1) / CALIBRATION_BINS:.1f}",
            "count": count,
            "mean_predicted": float(probabilities[in_bin].mean()) if count else None,
            "observed_rate": float(outcomes[in_bin].mean()) if count else None,
        })
    return table


def _model_metrics(probabilities, outcomes, actual):
    """Accuracy, coverage, Brier score, and calibration for one set of probabilities."""
    scored = probabilities.notna()
    p, y = probabilities[scored], outcomes[scored]
    metrics = _rule_metrics(_party_call(probabilities), actual)
    metrics["n_scored"] = int(scored.sum())
    # Brier score per race: the Democrat's probability against 1 or 0
    metrics["brier"] = float(((p - y) ** 2).mean()) if len(p) else None
    metrics["calibration"] = _calibration(p.to_numpy(), y.to_numpy())
    return metrics


def _score(predictions):
    """All metrics for one set of held-out races.

    Parameters
    ----------
    predictions : pandas.DataFrame
        Frame rows plus `p_model` and `p_without_money`.

    Returns
    -------
    dict
    """
    actual = predictions["dem_won"].map({1: "DEM", 0: "REP"})
    calls = {
        "model": _party_call(predictions["p_model"]),
        "money_rule": _party_call(predictions["dem_money_share"]),
        "cook": predictions["cook_favorite_party"].where(predictions["cook_favorite_party"].notna(), None),
    }
    listed = predictions["rating_source"] == "cook"
    shared = calls["model"].notna() & calls["money_rule"].notna() & calls["cook"].notna()
    return {
        "n_races": int(len(predictions)),
        "model": _model_metrics(predictions["p_model"], predictions["dem_won"], actual),
        "model_without_money": _model_metrics(predictions["p_without_money"], predictions["dem_won"], actual),
        "money_rule": _rule_metrics(calls["money_rule"], actual),
        "cook": _rule_metrics(calls["cook"], actual),
        # Inferred Solid ratings are almost always right, so Cook is also scored
        # on the seats Cook actually listed
        "cook_listed_only": _rule_metrics(calls["cook"][listed], actual[listed]),
        "shared": {
            "n_races": int(shared.sum()),
            **{f"{name}_accuracy": _rule_metrics(call[shared], actual[shared])["accuracy"]
               for name, call in calls.items()},
        },
    }


def _score_with_subsets(predictions):
    """Scores for all held-out races and for the competitive ones only."""
    competitive = predictions["cook_rating"].isin(COMPETITIVE_RATINGS)
    return {"overall": _score(predictions), "competitive": _score(predictions[competitive])}


def evaluate(frame):
    """Leave-one-cycle-out evaluation of the model, the money rule, and Cook.

    Each cycle is held out in turn (2024 first, then 2022): the model is fit
    on the other cycles only and scored on the held-out one. The money rule
    and Cook favorite need no training and are scored on the same races.

    Parameters
    ----------
    frame : pandas.DataFrame
        Output of `training_frame` covering at least two cycles.

    Returns
    -------
    dict
        `folds`: one entry per held-out cycle with `train_cycles`,
        `test_cycle`, `n_train`, and `overall` and `competitive` scores.
        `pooled`: the same scores over both held-out cycles together.
    """
    folds, held_out = [], []
    for test_cycle in sorted(frame["cycle"].unique(), reverse=True):
        train = frame[frame["cycle"] != test_cycle]
        test = frame[frame["cycle"] == test_cycle].copy()
        model = fit(train)
        test["p_model"] = _predict(model, test)
        test["p_without_money"] = _predict(fit(train, features=FEATURES_WITHOUT_MONEY), test)
        folds.append({
            "train_cycles": sorted(int(c) for c in train["cycle"].unique()),
            "test_cycle": int(test_cycle),
            "n_train": int(train.dropna(subset=FEATURES).shape[0]),
            "coefficients": coefficients(model),
            **_score_with_subsets(test),
        })
        held_out.append(test)
    return {"folds": folds, "pooled": _score_with_subsets(pd.concat(held_out))}
