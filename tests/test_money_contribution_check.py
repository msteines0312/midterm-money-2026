"""Tests for the paired bootstrap in scripts/money_contribution_check.py.

The paired computation is tested on a small synthetic frame with the columns
`held_out_predictions` returns. The held-out rebuild is checked against
`evaluate` on the same synthetic races used in tests/test_model.py.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Let the test import the script directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from money_contribution_check import held_out_predictions, paired_money_contribution  # noqa: E402
from src.predict.model import evaluate  # noqa: E402
from tests.test_model import synthetic_frame  # noqa: E402


def predictions(p_model, p_without_money, dem_won):
    return pd.DataFrame({"p_model": p_model, "p_without_money": p_without_money, "dem_won": dem_won})


def test_identical_models_give_zero_differences():
    # Pairing means every draw compares a race with itself, so the interval collapses to 0
    frame = predictions([0.9, 0.2, 0.6, 0.3], [0.9, 0.2, 0.6, 0.3], [1, 0, 0, 1])
    result = paired_money_contribution(frame)

    for key in ("brier_without_minus_with", "accuracy_with_minus_without"):
        assert result[key] == {"estimate": 0.0, "low": 0.0, "high": 0.0}


def test_estimates_match_hand_computed_scores():
    frame = predictions([0.9, 0.2, 0.6, 0.3], [0.7, 0.4, 0.4, 0.6], [1, 0, 0, 1])
    result = paired_money_contribution(frame)

    # Squared errors with money: 0.01, 0.04, 0.36, 0.49. Without: 0.09, 0.16, 0.16, 0.16.
    assert result["brier_with_money"] == pytest.approx(0.225)
    assert result["brier_without_money"] == pytest.approx(0.1425)
    assert result["brier_without_minus_with"]["estimate"] == pytest.approx(0.1425 - 0.225)
    # With money calls 2 of 4 right, without money calls all 4 right
    assert result["accuracy_with_minus_without"]["estimate"] == pytest.approx(0.5 - 1.0)
    for key in ("brier_without_minus_with", "accuracy_with_minus_without"):
        assert result[key]["low"] <= result[key]["estimate"] <= result[key]["high"]


def test_fixed_seed_repeats_and_unscored_rows_dropped():
    frame = predictions([0.9, 0.2, None, 0.3], [0.7, 0.4, 0.5, 0.6], [1, 0, 0, 1])

    first, second = paired_money_contribution(frame), paired_money_contribution(frame)

    assert first == second
    assert first["n_races"] == 3


def test_held_out_rebuild_matches_evaluate():
    frame = synthetic_frame()
    pooled = evaluate(frame)["pooled"]["overall"]
    result = paired_money_contribution(held_out_predictions(frame))

    assert result["brier_with_money"] == pytest.approx(pooled["model"]["brier"])
    assert result["brier_without_money"] == pytest.approx(pooled["model_without_money"]["brier"])
    assert result["accuracy_with_money"] == pytest.approx(pooled["model"]["accuracy"])
