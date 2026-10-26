"""Tests for src/predict/model.py.

`training_frame` is tested on a small database built with the real schema, so
every column name is the one the pipeline writes. `evaluate` is tested on a
synthetic frame with the same columns `training_frame` returns.
"""

import numpy as np
import pandas as pd
import pytest

import src.predict.model as model_module
from src.db import connect, create_schema, upsert_rows
from src.predict.model import coefficients, evaluate, fit, training_frame


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    create_schema(connection)
    yield connection
    connection.close()


def result(cycle, race_id, candidate_id, party, won, is_incumbent=0):
    return {
        "cycle": cycle, "race_id": race_id, "candidate_id": candidate_id,
        "name": f"Candidate {candidate_id}", "party": party, "votes": None,
        "vote_share": None, "won": won, "incumbent_challenge": None,
        "is_incumbent": is_incumbent,
    }


def money(cycle, candidate_id, external):
    return {
        "cycle": cycle, "candidate_id": candidate_id, "committee_id": "C0",
        "external_contributions": external, "candidate_self_funding": 0.0,
        "coverage_end_date": f"{cycle}-10-19",
    }


def race(cycle, race_id, pvi, rating="Solid R", source="inferred"):
    return {"cycle": cycle, "race_id": race_id, "cook_pvi": pvi,
            "cook_rating": rating, "rating_source": source}


def add_two_way(conn, race_id, pvi, dem_money, rep_money, dem_won, cycle=2022, rating="Solid R"):
    """Insert one D vs R race with both nominees on file."""
    dem_id, rep_id = f"D-{race_id}", f"R-{race_id}"
    upsert_rows(conn, "history_results", [
        result(cycle, race_id, dem_id, "DEM", int(dem_won)),
        result(cycle, race_id, rep_id, "REP", int(not dem_won), is_incumbent=1),
    ])
    upsert_rows(conn, "history_money", [money(cycle, dem_id, dem_money), money(cycle, rep_id, rep_money)])
    upsert_rows(conn, "history_races", [race(cycle, race_id, pvi, rating)])


# training_frame

def test_training_frame_orients_pvi_to_dem(conn):
    add_two_way(conn, "AA-01", "D+5", 100.0, 50.0, dem_won=True)
    add_two_way(conn, "AA-02", "R+7", 100.0, 50.0, dem_won=False)
    add_two_way(conn, "AA-03", "EVEN", 100.0, 50.0, dem_won=True)

    frame = training_frame(conn, [2022]).set_index("race_id")

    assert frame.loc["AA-01", "dem_pvi"] == 5
    assert frame.loc["AA-02", "dem_pvi"] == -7
    assert frame.loc["AA-03", "dem_pvi"] == 0
    # The Republican is flagged as the incumbent in every race above
    assert (frame["incumbency"] == -1).all()
    assert frame.loc["AA-01", "dem_money_share"] == pytest.approx(100 / 150)


def test_third_party_outraiser_dropped(conn):
    add_two_way(conn, "AA-01", "R+2", 100.0, 50.0, dem_won=True)
    add_two_way(conn, "AA-02", "R+2", 100.0, 50.0, dem_won=True)
    # An independent with more money than the Republican in AA-02 only
    upsert_rows(conn, "history_results", [result(2022, "AA-02", "I-1", "IND", 0)])
    upsert_rows(conn, "history_money", [money(2022, "I-1", 60.0)])

    frame = training_frame(conn, [2022])

    assert list(frame["race_id"]) == ["AA-01"]


def test_missing_money_row_dropped_and_negative_floored(conn):
    add_two_way(conn, "AA-01", "R+2", -500.0, 50.0, dem_won=False)
    add_two_way(conn, "AA-02", "R+2", 100.0, 50.0, dem_won=True)
    # The Democrat in AA-02 has no money row: a data gap, not $0
    conn.execute("DELETE FROM history_money WHERE candidate_id = 'D-AA-02'")

    frame = training_frame(conn, [2022])

    assert list(frame["race_id"]) == ["AA-01"]
    assert frame.iloc[0]["dem_money_share"] == 0.0


def test_both_incumbents_count_as_open(conn):
    add_two_way(conn, "AA-01", "D+1", 100.0, 50.0, dem_won=True)
    conn.execute("UPDATE history_results SET is_incumbent = 1 WHERE candidate_id = 'D-AA-01'")

    frame = training_frame(conn, [2022])

    assert frame.iloc[0]["incumbency"] == 0


# evaluate

def synthetic_frame(rows_per_cycle=40, seed=0):
    """Races whose winner mostly follows PVI, with some Toss Ups and one exact 50% split."""
    rng = np.random.default_rng(seed)
    rows = []
    for cycle in (2022, 2024):
        for i in range(rows_per_cycle):
            pvi = int(rng.integers(-20, 21))
            share = float(np.clip(0.5 + pvi / 50 + rng.normal(0, 0.1), 0.01, 0.99))
            dem_won = int(pvi + rng.normal(0, 4) > 0)
            rating = "Toss Up" if abs(pvi) <= 2 else ("Solid D" if pvi > 0 else "Solid R")
            rows.append({
                "cycle": cycle, "race_id": f"AA-{i:02d}", "dem_money_share": share,
                "incumbency": int(np.sign(pvi)), "dem_pvi": pvi,
                "cook_rating": rating, "rating_source": "cook" if i % 2 else "inferred",
                "cook_favorite_party": None if rating == "Toss Up" else ("DEM" if pvi > 0 else "REP"),
                "dem_won": dem_won,
            })
    frame = pd.DataFrame(rows)
    frame.loc[0, "dem_money_share"] = 0.5
    return frame


def test_leave_one_cycle_out_never_trains_on_test_cycle(monkeypatch):
    frame = synthetic_frame()
    real_fit = model_module.fit
    trained_on = []

    def recording_fit(train, **kwargs):
        trained_on.append(set(train["cycle"]))
        return real_fit(train, **kwargs)

    monkeypatch.setattr(model_module, "fit", recording_fit)
    result_ = evaluate(frame)

    folds = result_["folds"]
    assert [fold["test_cycle"] for fold in folds] == [2024, 2022]
    assert {2022} in trained_on and {2024} in trained_on
    for fold in folds:
        assert fold["test_cycle"] not in fold["train_cycles"]
    # Every fit saw exactly one cycle, never both
    assert all(len(cycles) == 1 for cycles in trained_on)


def test_abstentions_reported_as_coverage():
    frame = synthetic_frame()
    overall = evaluate(frame)["pooled"]["overall"]

    toss_ups = (frame["cook_rating"] == "Toss Up").sum()
    assert overall["cook"]["n_called"] == len(frame) - toss_ups
    assert overall["cook"]["coverage"] == pytest.approx((len(frame) - toss_ups) / len(frame))
    # The one exact 50% split is an abstention for the money rule, not a miss
    assert overall["money_rule"]["n_called"] == len(frame) - 1
    assert 0.0 <= overall["money_rule"]["accuracy"] <= 1.0


def test_brier_in_range():
    overall = evaluate(synthetic_frame())["pooled"]["overall"]

    assert 0.0 <= overall["model"]["brier"] <= 1.0
    calibration = overall["model"]["calibration"]
    assert len(calibration) == 5
    assert sum(b["count"] for b in calibration) == overall["model"]["n_scored"]


def test_shared_set_same_races_for_all_three():
    frame = synthetic_frame()
    overall = evaluate(frame)["pooled"]["overall"]

    shared = overall["shared"]
    expected = (
        (frame["cook_rating"] != "Toss Up") & (frame["dem_money_share"] != 0.5)
    ).sum()
    assert shared["n_races"] == expected
    assert set(shared) >= {"model_accuracy", "money_rule_accuracy", "cook_accuracy"}


def test_competitive_subset_excludes_solid_seats():
    frame = synthetic_frame()
    competitive = evaluate(frame)["pooled"]["competitive"]

    assert competitive["n_races"] == (frame["cook_rating"] == "Toss Up").sum()
    assert competitive["cook"]["n_called"] == 0


# Coefficients and noise

def test_original_scale_coefficients_reproduce_predictions():
    frame = synthetic_frame()
    model = fit(frame)
    coefs = coefficients(model)
    row = frame.iloc[[3]]

    log_odds = coefs["intercept"] + sum(coefs[f] * row[f].iloc[0] for f in model_module.FEATURES)
    by_hand = 1 / (1 + np.exp(-log_odds))

    assert by_hand == pytest.approx(model.predict_proba(row[model_module.FEATURES])[0, 1])
    assert set(coefs["standardized"]) == {"intercept", *model_module.FEATURES}


def test_bootstrap_interval_brackets_competitive_accuracy():
    frame = synthetic_frame()
    first = evaluate(frame)["pooled"]["competitive"]
    second = evaluate(frame)["pooled"]["competitive"]

    intervals = first["bootstrap_95"]
    # A fixed seed makes the intervals repeatable
    assert intervals == second["bootstrap_95"]
    for name in ("model", "money_rule"):
        interval = intervals[name]
        assert interval["low"] <= first[name]["accuracy"] <= interval["high"]
    assert set(intervals["shared"]) == {"n_races", "model", "money_rule", "cook"}
