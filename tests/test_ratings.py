"""Tests for src/ratings.py.

The HTML snippets copy the layout of the real pinned Wikipedia pages:
two-row headers, footnote markers, merged-cell continuation rows, and a
redistricting summary table that must not be mistaken for PVI data.
"""

import pandas as pd
import pytest

from src.ratings import (
    build_races,
    label_to_race_id,
    normalize_rating,
    parse_cook_ratings,
    parse_pvi_tables,
)

# Shaped like the ratings page: grouped header, then the real header with a
# footnoted "Cook" column, then competitive seats only
RATINGS_HTML = """
<table class="wikitable">
  <tr><th>Constituency</th><th>Incumbent</th><th>Ratings</th></tr>
  <tr><th>District</th><th>CPVI [1]</th><th>Incumbent</th><th>Cook Oct. 16, 2026 [3]</th><th>IE</th></tr>
  <tr><td>Alabama 2</td><td>R+7</td><td>Shomari Figures</td><td>Likely R (flip)</td><td>Lean R</td></tr>
  <tr><td>Alaska&nbsp;at-large</td><td>R+6</td><td>Nick Begich</td><td>Tossup</td><td>Tossup</td></tr>
</table>
"""

# Shaped like the elections page: a redistricting summary table ("New 2026 PVI")
# that must be skipped, then a state table with a continuation row from a
# merged cell (a second incumbent and no district label)
ELECTIONS_HTML = """
<table class="wikitable">
  <tr><th>District</th><th>Incumbent</th></tr>
  <tr><th>Location</th><th>Member</th><th>Original 2025 PVI</th><th>New 2026 PVI</th></tr>
  <tr><td>Alabama 2</td><td>Shomari Figures</td><td>D+5</td><td>R+7</td></tr>
</table>
<table class="wikitable">
  <tr><th>District</th><th>Incumbent</th><th>Candidates [184]</th></tr>
  <tr><th>Location</th><th>2026 PVI [88]</th><th>Member</th><th>Party</th></tr>
  <tr><td>Alabama 1</td><td>R+17</td><td>None (new seat)</td><td></td></tr>
  <tr><td>Alabama 2</td><td>R+7</td><td>Shomari Figures</td><td>Democratic</td></tr>
  <tr><td>Barry Moore Redistricted from the 1st</td><td>Republican</td><td>2020</td></tr>
  <tr><td>Alaska at-large</td><td>R+6</td><td>Nick Begich</td><td>Republican</td></tr>
</table>
<table class="wikitable">
  <tr><th>District</th><th>Incumbent</th><th>Candidates [211]</th></tr>
  <tr><th>Location</th><th>2025 PVI [l]</th><th>Member</th><th>Party</th></tr>
  <tr><td>Missouri 1</td><td>D+29</td><td>Wesley Bell</td><td>Democratic</td></tr>
</table>
"""


@pytest.mark.parametrize("raw, expected", [
    ("Likely R (flip)", "Likely R"), ("Safe D", "Solid D"), ("Tossup", "Toss Up"),
])
def test_normalize_rating(raw, expected):
    assert normalize_rating(raw) == expected


@pytest.mark.parametrize("label, expected", [
    ("Arizona 2", "AZ-02"), ("Alaska at-large", "AK-00"), ("New York 17", "NY-17"),
])
def test_label_to_race_id(label, expected):
    assert label_to_race_id(label) == expected


def test_label_to_race_id_unknown_state_names_label():
    with pytest.raises(ValueError, match="Atlantis 1"):
        label_to_race_id("Atlantis 1")


def test_parse_cook_ratings():
    ratings = parse_cook_ratings(RATINGS_HTML)
    assert ratings.to_dict("records") == [
        {"race_id": "AL-02", "cook_rating": "Likely R"},
        {"race_id": "AK-00", "cook_rating": "Toss Up"},
    ]


def test_parse_pvi_tables_skips_redistricting_table_and_continuation_rows():
    pvi = parse_pvi_tables(ELECTIONS_HTML)
    assert pvi.to_dict("records") == [
        {"race_id": "AL-01", "cook_pvi": "R+17"},
        {"race_id": "AL-02", "cook_pvi": "R+7"},
        {"race_id": "AK-00", "cook_pvi": "R+6"},
        {"race_id": "MO-01", "cook_pvi": "D+29"},
    ]


def summary_and_state_tables(summary_pvi):
    """A crossover-seat summary table followed by the state table it repeats."""
    return f"""
    <table class="wikitable">
      <tr><th>District</th><th>Incumbent</th></tr>
      <tr><th>Location</th><th>2026 PVI</th><th>Member</th></tr>
      <tr><td>Maine 2</td><td>{summary_pvi}</td><td>Jared Golden</td></tr>
    </table>
    <table class="wikitable">
      <tr><th>District</th><th>Incumbent</th><th>Candidates</th></tr>
      <tr><th>Location</th><th>2026 PVI</th><th>Member</th></tr>
      <tr><td>Maine 2</td><td>R+4</td><td>Jared Golden</td></tr>
    </table>
    """


def test_parse_pvi_tables_keeps_one_row_when_a_summary_table_repeats_a_district():
    pvi = parse_pvi_tables(summary_and_state_tables("R+4"))
    assert pvi.to_dict("records") == [{"race_id": "ME-02", "cook_pvi": "R+4"}]


def test_parse_pvi_tables_rejects_conflicting_pvi_for_one_district():
    with pytest.raises(ValueError, match="ME-02"):
        parse_pvi_tables(summary_and_state_tables("R+9"))


def test_build_races_uses_listed_rating_and_infers_the_rest():
    pvi = pd.DataFrame({"race_id": ["AL-01", "AL-02", "MO-01"], "cook_pvi": ["R+17", "R+7", "D+29"]})
    ratings = pd.DataFrame({"race_id": ["AL-02"], "cook_rating": ["Likely R"]})
    races = {r["race_id"]: r for r in build_races(pvi, ratings)}

    assert races["AL-02"]["cook_rating"] == "Likely R"
    assert races["AL-02"]["rating_source"] == "cook"
    assert races["AL-01"]["cook_rating"] == "Solid R"
    assert races["AL-01"]["rating_source"] == "inferred"
    assert races["MO-01"]["cook_rating"] == "Solid D"
    assert races["MO-01"] == {
        "race_id": "MO-01", "state": "MO", "district": "01",
        "cook_rating": "Solid D", "cook_pvi": "D+29", "rating_source": "inferred",
    }


def test_build_races_rejects_rated_seat_missing_from_pvi():
    pvi = pd.DataFrame({"race_id": ["AL-01"], "cook_pvi": ["R+17"]})
    ratings = pd.DataFrame({"race_id": ["ZZ-09"], "cook_rating": ["Toss Up"]})
    with pytest.raises(ValueError, match="ZZ-09"):
        build_races(pvi, ratings)
