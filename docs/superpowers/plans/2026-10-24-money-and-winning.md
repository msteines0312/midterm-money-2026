# Money and Winning: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Commit and push 2026 House general election predictions before Nov 3: a simple money rule with a Cook comparison by about Oct 28, then a logistic regression trained on 2022 and 2024 with pre-election money.

**Architecture:** Part A parses November nominees from a pinned Wikipedia revision, matches them to FEC candidates, and builds a per-race simple predictions CSV from the 2026-10-23 snapshot. Part B adds historical tables (pre-general money, results, PVI, and ratings for 2022 and 2024), trains a race-level model in `src/predict/model.py`, and writes a model predictions CSV. Scoring after Nov 3 gets its own plan.

**Tech Stack:** Python 3.13, pandas, requests, BeautifulSoup, sqlite3, pytest, scikit-learn (new, Part B).

**Spec:** `docs/superpowers/specs/2026-10-24-money-and-winning-design.md`

## Global Constraints
- No em dashes anywhere. NumPy docstrings. Comment density matches `src/ratings.py` and `src/fec/bulk.py`.
- Commit messages in plain human voice, no prefixes, never a Co-Authored-By line.
- Tests run on real saved rows or real saved HTML, never invented field names.
- Money is `external_contributions` (individuals minus refunds, plus PAC and party, minus committee refunds). Self-funding never counts. Negative values are floored at 0.
- 2026 money comes from `candidate_totals` at `pulled_at = '2026-10-23'`. Never stamp newer data with that date.
- Prediction CSVs are never edited after their tag. Corrections go in a new, dated file.
- Push and tag as soon as predictions are verified (`pre-election-simple`, `pre-election-model`) on branch `money-and-winning`. Don't touch open PRs #1 and #2.
- Historical data never modifies the 2026 tables.
- Neutral wording. Abstentions (Toss Up, exact 50%) are not misses.

## Review Focus
1. **A nominee with no FEC match** (raised under $5,000, so never filed): they stay in the race with $0, which makes the opponent's share 100%. Pinned in Task 2.
2. **A race with one nominee:** listed as `unopposed` and not scored. Pinned in Task 2.
3. **Same-party top-two races** (CA, WA): money rule from the top two by money, no Cook favorite, excluded from the model. Pinned in Tasks 2 and 7.
4. **Both nominees at $0 or exactly equal:** no money leader (abstain), not a crash or a divide-by-zero. Pinned in Task 2.
5. **Amended historical reports:** only the most recent version of each report counts, so amendments don't double money. Pinned in Task 4.

---

## Part A: Simple predictions (target Oct 28)

### Task 1: Parse November nominees

**Files:**
- Modify: `src/config.py` (add `NOMINEES_PAGE = ("2026_United_States_House_of_Representatives_elections", <latest revision id>)`)
- Create: `src/nominees.py`, `tests/test_nominees.py`
- Create: `tests/fixtures/nominees_sample.html` (real table rows cut from the pinned revision)

**Interfaces:**
- Consumes: `src.ratings.cell_text`, `src.ratings.label_to_race_id`, `src.ratings.download_page`.
- Produces: `parse_nominees(html: str) -> list[dict]`, with keys `race_id, name, party, status`. `party` is the word inside the parentheses ("Democratic", "Republican", "Independent", ...). `status` is `"confirmed"` or `"unconfirmed"`.

- [ ] **Step 1: Pin the revision.** Fetch the page's current revision ID through the MediaWiki API (`action=query&prop=revisions&titles=...&rvprop=ids`) and set `NOMINEES_PAGE`. Record the ID and the fetch date in the config comment.
- [ ] **Step 2: Save the fixture.** Cut these real rows from the pinned HTML into `nominees_sample.html`, keeping their table headers: Alabama 1 and 2, California 1, one California same-party race, one at-large seat, one race with a single nominee, and any race whose candidate cell shows a pending runoff, "TBD", or a withdrawal (search the page; if none exists, say so in the fixture comment).
- [ ] **Step 3: Write failing tests:** `test_two_nominees_with_party` (Alabama 2 gives Shomari Figures/Democratic and Rhett Marques/Republican), `test_at_large_race_id` (`XX-00`), `test_same_party_race_kept`, `test_single_nominee_race`, `test_unconfirmed_status` (or skip with a reason if the page has none), `test_footnotes_stripped`.
- [ ] **Step 4: Run and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/test_nominees.py -v`
- [ ] **Step 5: Implement `parse_nominees`.** Use the same per-state tables `parse_pvi_tables` reads, and find the column whose header starts with "Candidates". Each `<li>` is "▌ Name (Party)". Strip the bar character and any "(incumbent)" style notes. Mark a race `unconfirmed` when its cell mentions a pending runoff, TBD, or withdrawal. Write a comment listing the exact markers you found.
- [ ] **Step 6: Run the tests and confirm they pass.** Then run `python -c` on the full pinned page and print the counts: races, nominees, and races per nominee count.
- [ ] **Step 7: Commit** `src/config.py src/nominees.py tests/test_nominees.py tests/fixtures/nominees_sample.html` with message "Parse November House nominees from a pinned Wikipedia revision".

### Task 2: Match nominees to FEC candidates and build simple predictions

**Files:**
- Create: `src/predict/__init__.py`, `src/predict/simple.py`, `tests/test_simple_predictions.py`
- Create: `data/manual/nominee_matches.csv` (columns `race_id,name,candidate_id,note`, for hand-checked matches only)
- Modify: `src/manual.py` (add `load_nominee_matches`)

**Interfaces:**
- Consumes: `parse_nominees` output, plus the `candidates`, `candidate_totals`, `races`, and `outside_spending` tables.
- Produces:
  - `match_nominees(nominees: list[dict], candidates: list[dict], overrides: list[dict]) -> list[dict]`: adds `candidate_id` (or None). Matching uses the override first, then a unique last-name match among `candidates` in the same `race_id`, then None.
  - `simple_predictions(conn, nominees: list[dict], pulled_at: str) -> pandas.DataFrame`: one row per race. Columns: `race_id, status, race_type, dem_name, dem_candidate_id, rep_name, rep_candidate_id, dem_money, rep_money, dem_money_share, money_leader_party, cook_rating, cook_favorite_party, incumbent_party, outside_support_dem, outside_oppose_dem, outside_support_rep, outside_oppose_rep, money_and_cook_agree, third_party_outraised, notes`. `third_party_outraised` is true when a nominee other than the D and R nominees has more external money than either of them.
  - `race_type` is one of `D_vs_R`, `same_party`, `unopposed`, `other`. For a `same_party` race, the `dem_*` and `rep_*` columns hold the top two nominees by money, and the note goes in a `notes` column.
  - `money_leader_party` is `DEM`, `REP`, or None (abstain). `cook_favorite_party` is None for Toss Up and for non-D_vs_R races. Outside spending uses only committees in `committees` with type O, V, or W, as `src/analysis/tech_money.py` does.

- [ ] **Step 1: Write failing tests** against a tmp database built with `create_schema`, using hand-written rows:
  - `test_unique_last_name_match` and `test_ambiguous_last_name_unmatched`
  - `test_override_wins`
  - `test_unmatched_nominee_counts_as_zero_money`: the opponent's share is 1.0
  - `test_negative_money_floored_at_zero`
  - `test_both_zero_is_abstain` and `test_exact_half_is_abstain`
  - `test_toss_up_has_no_cook_favorite`
  - `test_unopposed_race_type`
  - `test_same_party_race_has_no_cook_favorite`
  - `test_unconfirmed_status_passed_through`
  - `test_outside_spending_excludes_non_committee_filers`
  - `test_self_funding_not_counted`: a candidate with a big `candidate_self_funding` and small `external_contributions` gets the small share
  - `test_third_party_outraised_flagged`
- [ ] **Step 2: Run and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/test_simple_predictions.py -v`
- [ ] **Step 3: Implement** `match_nominees`, `simple_predictions`, and `load_nominee_matches` (validates that every row has a `note`). Party words map to codes: Democratic and Democratic-Farmer-Labor become DEM, and Republican becomes REP.
- [ ] **Step 4: Run all tests and confirm they pass.** Run: `.venv/Scripts/python -m pytest -v`
- [ ] **Step 5: Commit** with message "Match nominees to FEC candidates and build simple money and Cook predictions".

### Task 3: Write, verify, commit, tag, and push the simple predictions

**Files:**
- Create: `scripts/build_simple_predictions.py`
- Create: `reports/predictions/2026-general-simple.csv`, `reports/predictions/README.md`
- Modify: `data/manual/nominee_matches.csv`, `README.md` (one line under Status), `tasks/todo.md`

**Interfaces:**
- Consumes: Tasks 1 and 2.

- [ ] **Step 1: Write the script.** `python scripts/build_simple_predictions.py` downloads (or reuses) the pinned nominee page, runs `simple_predictions(conn, nominees, "2026-10-23")`, and writes the CSV sorted by `race_id`. It prints counts by `race_type`, by `status`, unmatched nominees, money-leader abstentions, Cook abstentions, and the number of races where money and Cook disagree.
- [ ] **Step 2: Clear unmatched nominees.** For every unmatched nominee, search fec.gov by name and state. Add real matches to `nominee_matches.csv` with a note such as "fec.gov candidate page, name spelled X". Nominees with no FEC record stay unmatched, and the note says "no FEC filing found".
- [ ] **Step 3: Spot-check 10 D_vs_R races,** five competitive and five safe. Compare `dem_money` and `rep_money` against each candidate's fec.gov page, through Oct 14. Record the comparison table in `reports/predictions/README.md`. Every row must match within $1 of the bulk figure, or the gap must be explained.
- [ ] **Step 4: Write `reports/predictions/README.md`.** Cover what the file is, the frozen-after-tag rule, column definitions, abstention rules, the money snapshot date, the nominee source revision, the spot-check table, and counts. Keep it neutral, with no em dashes.
- [ ] **Step 5: Run the full suite.** Run: `.venv/Scripts/python -m pytest` Expected: all pass.
- [ ] **Step 6: Commit, tag, and push.**
  ```bash
  git add scripts/build_simple_predictions.py reports/predictions data/manual/nominee_matches.csv README.md tasks/todo.md
  git commit -m "Commit simple 2026 House general election predictions before election day"
  git tag -a pre-election-simple -m "Simple money and Cook predictions, committed before Nov 3, 2026"
  git push -u origin money-and-winning
  git push origin pre-election-simple
  ```
  Then confirm with `git ls-remote --tags origin pre-election-simple` that the tag is on GitHub.

## Part B: Model (before Nov 3 if ready, otherwise labeled after)

### Task 4: Historical pre-general money for 2022 and 2024

**Files:**
- Modify: `src/schema.sql` (new table `history_money`: `cycle INTEGER, candidate_id TEXT, committee_id TEXT, external_contributions REAL, candidate_self_funding REAL, coverage_end_date TEXT`, primary key `(cycle, candidate_id)`)
- Create: `src/fec/history.py`, `tests/test_history_money.py`, `tests/fixtures/reports_12g_sample.json`, `tests/fixtures/reports_ye_sample.json`, `tests/fixtures/ccl_sample.txt`

**Interfaces:**
- Produces:
  - `principal_committees(ccl_text: str) -> dict[str, list[str]]`: maps candidate ID to principal campaign committee IDs. Uses the FEC candidate-committee linkage bulk file `ccl{yy}.zip`, where `CMTE_DSGN == "P"`.
  - `report_external(rec: dict) -> float`: `total_individual_contributions_ytd - refunded_individual_contributions_ytd + other_political_committee_contributions_ytd + political_party_committee_contributions_ytd - refunded_other_political_committee_contributions_ytd - refunded_political_party_committee_contributions_ytd`. Values arrive as text or float.
  - `pre_general_money(client, cycle: int, ccl_text: str) -> list[dict]`: rows for `history_money`.

Cycle-to-date money as of the pre-general report equals the year-end report for the odd year (`report_type=YE`, `report_year=cycle-1`) plus the 12G report's year-to-date fields. Self-funding is `candidate_contribution_ytd + loans_made_by_candidate_ytd`, summed the same way.

- [ ] **Step 1: Save real fixtures** with a small script added to `scripts/save_fixtures.py`: two pages of `/reports/house-senate/?cycle=2024&report_type=12G`, the matching YE rows, and real `ccl24` lines for those committees. Strip the API key, as the existing script does.
- [ ] **Step 2: Write failing tests:** `test_report_external_matches_fields` (one real record computed by hand), `test_ye_plus_12g_ytd`, `test_most_recent_amendment_only` (two versions of the same report give the later one's numbers), `test_multiple_principal_committees_summed`, `test_candidate_without_12g_omitted` (no pre-general report means no row; candidates who weren't in the general don't file one), `test_odd_coverage_12g_flagged` (a 12G whose coverage ends after election day is excluded and logged; the real API returned one covering 10-24 to 11-05).
- [ ] **Step 3: Run and confirm they fail.**
- [ ] **Step 4: Implement.** Query with the API's most-recent-version filter, and verify in the fixture which parameter does that (`most_recent=true` or `is_amended=false`). Download `ccl{yy}.zip` the way `download_summary` does.
- [ ] **Step 5: Run the tests, then the full suite.**
- [ ] **Step 6: Commit** with message "Load 2022 and 2024 House money as of each campaign's pre-general report".

### Task 5: Historical results, PVI, and ratings

**Files:**
- Modify: `src/schema.sql`. Add `history_results` (`cycle, race_id, candidate_id, name, party, votes, won`, primary key `(cycle, race_id, name)`) and `history_races` (`cycle, race_id, cook_pvi, cook_rating, rating_source`, primary key `(cycle, race_id)`).
- Modify: `src/config.py` (pinned pages for 2022 and 2024: the elections page and the ratings page, each pinned to the last revision before that election day)
- Create: `src/history_results.py`, `tests/test_history_results.py`, plus fixtures of real rows

**Interfaces:**
- Consumes: `src.ratings.parse_cook_ratings`, `parse_pvi_tables`, `build_races` (reuse them; if a past page's headers differ, add a small header option instead of copying the parser).
- Produces: `load_history_results(cycle) -> list[dict]` and `load_history_races(cycle) -> list[dict]`, plus a `--history` flag on `src.pipeline` that fills the three history tables for 2022 and 2024.

- [ ] **Step 1: Find the results source.** First choice is the FEC's *Federal Elections {year}* results spreadsheet (fec.gov "Election results and voting information"), which carries FEC candidate IDs. If 2024 isn't published or doesn't parse, use the MIT Election Data and Science Lab U.S. House returns (Harvard Dataverse) and match candidates to FEC IDs by state, district, and last name, as in Task 2. Record the source and URL in the config and the README.
- [ ] **Step 2: Write failing tests on real fixture rows:** `test_general_rows_only` (primaries and runoffs dropped, Georgia and Louisiana general runoffs handled so the final winner has `won = 1`), `test_one_winner_per_race`, `test_at_large_race_id`, `test_past_pvi_parsed` (2024 and 2022 pages), `test_past_ratings_inferred_solid`.
- [ ] **Step 3: Run and confirm they fail.**
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run `python -m src.pipeline --history`** and print per cycle the races, the D versus R races, results matched to `history_money`, and unmatched counts. Expected: at least 90% of D versus R general candidates matched to pre-general money. Otherwise stop and report.
- [ ] **Step 6: Commit** with message "Load 2022 and 2024 House results, PVI, and ratings for model training".

### Task 6: Train and evaluate the model

**Files:**
- Create: `src/predict/model.py`, `tests/test_model.py`
- Modify: `requirements.txt` (add `scikit-learn`)

**Interfaces:**
- Produces:
  - `training_frame(conn, cycles: list[int]) -> pandas.DataFrame`: one row per D versus R race. Columns: `cycle, race_id, dem_money_share, incumbency (1 = D incumbent, -1 = R incumbent, 0 = open), dem_pvi (D+5 becomes 5, R+5 becomes -5, EVEN becomes 0), cook_favorite_party, dem_won`. It drops races where a third-party or independent candidate outraised either major nominee.
  - `evaluate(frame) -> dict`: leave-one-cycle-out. Train on 2022 and test on 2024, then the reverse. Reports accuracy, Brier score, and calibration (5 equal-width bins) for the model, plus accuracy and coverage for the money rule and the Cook favorite, and accuracy for all three on the shared set of races where each made a call.
  - `fit(frame) -> sklearn.linear_model.LogisticRegression`: fit on all training cycles, with no regularization tuning beyond the default.
  - `coefficients(model) -> dict`

- [ ] **Step 1: Write failing tests on a synthetic frame:** `test_training_frame_orients_pvi_to_dem`, `test_third_party_outraiser_dropped`, `test_leave_one_cycle_out_never_trains_on_test_cycle`, `test_abstentions_reported_as_coverage`, `test_brier_in_range`, `test_shared_set_same_races_for_all_three`.
- [ ] **Step 2: Run and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.**
- [ ] **Step 5: Run `evaluate`** on the real 2022 and 2024 data and save the output for Task 7.
- [ ] **Step 6: Commit** with message "Train a race-level win model on 2022 and 2024 and evaluate it by held-out cycle".

### Task 7: Model predictions for 2026, verify, commit, tag, push

**Files:**
- Create: `scripts/build_model_predictions.py`
- Create: `reports/predictions/2026-general-model.csv`, `reports/predictions/model-evaluation.json`
- Modify: `reports/predictions/README.md` (add a model section; earlier content and the simple CSV are not edited)

**Interfaces:**
- Consumes: Task 2 `simple_predictions` (for 2026 D versus R races and inputs) and Task 6 `fit`, `evaluate`, `coefficients`.

- [ ] **Step 1: Write the script.** It fits on 2022 and 2024, then predicts `dem_win_probability` for every 2026 `D_vs_R` race whose `status` is `confirmed`, excluding races where `third_party_outraised` is true. CSV columns: `race_id, dem_name, rep_name, dem_money_share, incumbency, dem_pvi, dem_win_probability, money_leader_party, cook_favorite_party`. It writes the evaluation output and coefficients to `model-evaluation.json`.
- [ ] **Step 2: Sanity-check the output.** Safe seats should be near 0 or 1, the coefficient signs should be plausible (PVI and incumbency positive toward the Democrat when D-oriented), and probabilities should never be exactly 0 or 1. If a sign is implausible, stop and report instead of tuning.
- [ ] **Step 3: Add the README model section:** training data, the pre-general money definition, held-out results compared with the money rule and Cook on the same races, coefficients in plain words, and the limit that this is prediction, not cause. If the date is on or after Nov 3, 2026, add a clear line at the top saying "Built after the election; not a pre-election prediction" and skip Step 5's tag.
- [ ] **Step 4: Run the full suite.**
- [ ] **Step 5: Commit, tag (only if before Nov 3), and push.**
  ```bash
  git add scripts/build_model_predictions.py reports/predictions requirements.txt
  git commit -m "Commit model-based 2026 House general election predictions"
  git tag -a pre-election-model -m "Model predictions, committed before Nov 3, 2026"
  git push origin money-and-winning
  git push origin pre-election-model
  ```
  Then confirm with `git ls-remote --tags origin pre-election-model`.
