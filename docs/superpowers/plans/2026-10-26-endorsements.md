# Endorsements: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a sourced dataset of House primary endorsements and write the endorsements section (win rates of endorsed candidates by incumbent, open seat, and contested primary, with the selection-bias discussion) before Nov 3, 2026.

**Architecture:**
- A short, confirmed list of endorsers (`data/manual/endorsers.csv`) and a hand-sourced endorsements file (`data/manual/endorsements.csv`), each row with a source URL, loaded and validated by `src/manual.py`.
- `src/analysis/endorsements.py` classifies each primary (incumbent, open seat, challenger, contested or not), decides whether the endorsed candidate became a nominee, and computes win rates with intervals and baselines.
- A build script writes charts, a numbers JSON, and `reports/endorsements.md`, following `scripts/build_billionaire_report.py`.

**Tech Stack:** Python 3.13, pandas, requests, sqlite3, pytest, matplotlib. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-20-midterm-money-design.md`, research question 2 ("Win rate of endorsed candidates in 2026 primaries, split by incumbents, open seats, and contested primaries, with an explicit selection-bias discussion"). There is no separate design doc. The decisions below are my calls, written down so you can change them before work starts.

## Design Decisions (my calls)
1. **Who counts as an endorser.** One that publishes a public, dated list of 2026 House primary endorsements. The same rule applies to both parties. Task 1 confirms each candidate endorser has such a list before it is included. The plan expects Donald Trump and Club for Growth PAC on the Republican side (Ballotpedia tracks Trump's endorsements, and Club for Growth publishes an official list) and at least two Democratic-side groups found by the same rule. Names are confirmed by research, not assumed.
2. **House primaries only.** Tracker lists mix Senate, governor, and state races. Rows for other offices are dropped.
3. **Timing.** An endorsement counts only if it is dated on or before the candidate's primary date. A later endorsement of a nominee proves nothing. Rows with no date are kept in the file but excluded from the headline rate and reported separately.
4. **"Won" means became the November nominee.** Same rule as the billionaire section. Both candidates advancing from a top-two primary (CA, WA) count as wins, a runoff winner is the nominee, and a withdrawal counts as not the nominee, with a note.
5. **Contested** means at least two candidates of the endorsed candidate's party in the race each had at least $10,000 in external contributions in the FEC data. This is a proxy, because full primary candidate lists are not in the database. Task 3 hand-checks 15 races against Wikipedia and reports how often the proxy agreed.
6. **Selection bias is handled three ways, not one.** (a) Win rates by stratum. (b) A baseline: the win rate of all candidates in the same stratum. (c) A favorite check: in contested primaries, whether the endorsed candidate was also the top fundraiser. The section says plainly that this cannot separate an endorsement's effect from endorsers choosing likely winners.
7. **Intervals.** Wilson 95% intervals, because the counts per stratum will be small.
8. **Reuse.** Primary outcomes reuse `src.analysis.billionaires.primary_outcomes` and nominee IDs from `reports/predictions/2026-general-simple.csv` (read-only). Moving that function into a shared module is a possible later refactor and is not part of this plan.

## Global Constraints
- No em dashes anywhere. NumPy docstrings. Comment density matches `src/analysis/billionaires.py`.
- Plain commit messages, never a Co-Authored-By or attribution line.
- Tests run on real saved HTML or real rows, never invented field names.
- Never modify existing tables or the frozen files in `reports/predictions/`.
- Every endorsement row has a `source_url`. Nothing is added from memory.
- Neutral wording, with no judging verbs. Same standard for both parties.
- Work on a new branch `endorsements` from `main`. Don't push without the controller's go-ahead.

## Review Focus
1. **Endorsement dated after the primary** (a nominee endorsed once they had won) must not count. Pinned in Task 4.
2. **One endorser backing two candidates in the same primary.** Excluded from the win rate and listed separately, because one of them has to lose. Pinned in Task 4.
3. **Uncontested primaries.** An endorsed candidate with no opponent wins trivially. They get their own stratum and stay out of the headline. Pinned in Task 4.
4. **Other offices in a tracker list** (Senate, governor, state legislature). Dropped, with a count reported. Pinned in Task 2.
5. **Candidates in redrawn districts or with a changed FEC ID.** Matched by candidate ID first, then race and last name, and anything unmatched goes to a review list, never counted as a loss. Pinned in Task 2.

---

### Task 1: Confirm endorsers and add the loaders

**Files:**
- Create: `data/manual/endorsers.csv` with columns `endorser,side,list_url,list_kind,checked_on,note`. `side` is `R` or `D`. `list_kind` is `official` or `tracker`.
- Create: `data/manual/endorsements.csv` (header only for now) with columns `endorser,candidate_id,race_id,candidate_name,endorsement_date,source_url,note`.
- Modify: `src/manual.py`, `src/config.py` (two path constants), `tests/test_manual.py`.

**Interfaces:**
- Produces:
  - `load_endorsers(path=ENDORSERS_CSV) -> list[dict]`. Raises `ValueError` if `list_url` is empty, `side` is not R or D, or `list_kind` is unknown.
  - `load_endorsements(path=ENDORSEMENTS_CSV) -> list[dict]`. Raises if `source_url` or `race_id` is empty. `endorsement_date` is an ISO date string or empty. Raises if an `endorser` is not in `endorsers.csv`.

- [ ] **Step 1: Research the endorser list.** For each candidate endorser, fetch its list page with WebFetch and confirm it names 2026 House candidates. Candidates: Trump (via the Ballotpedia tracker and the posts it links), Club for Growth PAC (`clubforgrowth.org/elections/pac-endorsed-candidates/`), and Democratic-side groups found by searching for public House endorsement lists (for example EMILY's List, Justice Democrats, Working Families Party). Record only groups whose page was actually fetched. Never fill a row from memory.
- [ ] **Step 2: Stop and check in.** Show the proposed `endorsers.csv` (name, side, list size for House, list URL) and ask for approval. Do not build the dataset until it is approved.
- [ ] **Step 3: Write failing loader tests:** `test_endorser_requires_list_url`, `test_endorser_side_validated`, `test_endorsement_requires_source`, `test_endorsement_endorser_must_be_listed`, `test_real_endorsement_files_load` (in the style of `test_real_billionaire_files_load`).
- [ ] **Step 4: Implement the two loaders, confirm the tests pass, and commit** with message "Add the endorser list and loaders for the endorsements section".

### Task 2: Build the endorsements dataset

**Files:**
- Modify: `data/manual/endorsements.csv`
- Create: `src/endorsements_match.py`, `tests/test_endorsements_match.py`, `tests/fixtures/endorsements_list_sample.html` (a real saved list page for the parser tests)

**Interfaces:**
- Consumes: `candidates` table, `load_endorsers`.
- Produces:
  - `parse_endorsement_list(html: str) -> list[dict]`, one dict per listed candidate with keys `name`, `office`, `state`, `district`, `date`, `source_url`. Written against the saved sample, one parser per list format actually found.
  - `match_candidates(rows: list[dict], candidates: pd.DataFrame) -> tuple[list[dict], list[dict]]`, returning matched rows (with `candidate_id` and `race_id`) and a review list. Matching goes by FEC ID if the page gives one, otherwise by race and last name using `src.predict.simple._last_name_matches`.

- [ ] **Step 1: Save a real list page** as `tests/fixtures/endorsements_list_sample.html`.
- [ ] **Step 2: Write failing tests:** `test_non_house_rows_dropped` (Senate, governor, and state rows are dropped and counted), `test_match_by_candidate_id`, `test_match_by_race_and_last_name`, `test_unmatched_goes_to_review`, `test_district_change_matches_by_id`.
- [ ] **Step 3: Implement both functions, run the tests, and confirm they pass.**
- [ ] **Step 4: Collect the data.** Parse each approved list, match to FEC candidates, and write the matched rows to `endorsements.csv`. Hand-check up to 10 review-list items against the endorser's page and Wikipedia, resolve them, and note any left over.
- [ ] **Step 5: Run the full suite and commit** with message "Add sourced House primary endorsements". The commit body gives the row count per endorser, the number dropped as non-House, and the number left in review.

### Task 3: Primary dates and primary context

**Files:**
- Create: `data/manual/primary_dates.csv` (columns `state,primary_date,runoff_date,source_url`), `src/analysis/endorsements.py`, `tests/test_endorsements.py`

**Interfaces:**
- Produces:
  - `load_primary_dates(path) -> dict[str, str]`, a state to ISO primary date map. Raises if a state has no `source_url`.
  - `classify_primary(conn, candidate_ids, cycle=2026, min_external=10_000) -> pd.DataFrame` with columns `candidate_id, race_id, status, contested, top_fundraiser`. `status` is `incumbent`, `open_seat`, or `challenger` from `candidates.incumbent_challenge`. `contested` is True when at least two candidates of the party in that race each reach `min_external` in `external_contributions` on the latest `candidate_totals` pull.

- [ ] **Step 1: Write failing tests on a tmp database:** `test_status_from_incumbent_challenge`, `test_contested_needs_two_funded_candidates`, `test_one_funded_candidate_is_uncontested`, `test_top_fundraiser_flag`, `test_primary_date_requires_source`.
- [ ] **Step 2: Build `primary_dates.csv`** from the pinned Wikipedia elections page, with the page URL as each row's source.
- [ ] **Step 3: Implement both functions and confirm the tests pass.**
- [ ] **Step 4: Check the proxy.** Hand-check 15 contested and uncontested calls against Wikipedia state pages and record how many agree in a code comment and in the commit body.
- [ ] **Step 5: Commit** with message "Add primary dates and a contested-primary classification".

### Task 4: Outcomes, win rates, and baselines

**Files:**
- Modify: `src/analysis/endorsements.py`, `tests/test_endorsements.py`

**Interfaces:**
- Consumes: `load_endorsements`, `load_primary_dates`, `classify_primary`, `primary_outcomes` from `src.analysis.billionaires`.
- Produces:
  - `endorsement_outcomes(endorsements, primary_dates, classified, nominee_ids, nominees) -> pd.DataFrame` with columns `endorser, candidate_id, race_id, status, contested, timing, outcome, hedged`. `timing` is `before`, `after`, or `unknown`. `hedged` is True when the same endorser backed two candidates in one primary.
  - `endorsement_win_rates(outcomes) -> pd.DataFrame` by endorser and stratum with `won, lost, review, rate, low, high` (Wilson 95%). Only `before` timing, not hedged, and contested rows count toward the headline, and the other groups are reported alongside.
  - `baseline_rates(conn, classified_all, nominee_ids) -> pd.DataFrame`, the same strata for all candidates.
  - `favorite_check(outcomes) -> dict`, the share of endorsed contested candidates who were the top fundraiser, and their win rate when they were and were not.

- [ ] **Step 1: Write failing tests:** `test_endorsement_after_primary_not_counted`, `test_unknown_date_excluded_from_headline`, `test_hedged_endorsements_excluded`, `test_uncontested_in_own_stratum`, `test_top_two_advance_is_a_win`, `test_withdrawal_is_not_a_win`, `test_wilson_interval_known_values` (for example 3 of 4 gives roughly 0.30 to 0.95), `test_rate_is_none_when_nothing_decided`, `test_favorite_check_shares`.
- [ ] **Step 2: Run them, confirm they fail, implement, then confirm they pass.**
- [ ] **Step 3: Run on real data.** Print the win rate table, the baselines, the favorite check, the review list, and the hedged list. Hand-check up to 10 outcomes against Wikipedia.
- [ ] **Step 4: Commit** with message "Score endorsed candidates against primary outcomes".

### Task 5: Charts, numbers, and the write-up

**Files:**
- Create: `scripts/build_endorsements_report.py`, `reports/endorsements.md`, `reports/figures/endorsements_numbers.json`, `reports/figures/endorsements_*.png`, `tests/test_endorsements_report_numbers.py`
- Modify: `README.md` (link and status), `tasks/todo.md`

**Interfaces:**
- Consumes: Tasks 1 to 4, plus the chart helpers in `scripts/build_tech_money_report.py`.

- [ ] **Step 1: Write the build script** following `scripts/build_billionaire_report.py`. Charts: win rate by endorser and stratum with the interval and counts, endorsed against baseline in the same stratum, and the favorite check. Party colors only where party is the encoding. Each subtitle carries its data date. Load the `dataviz` skill first.
- [ ] **Step 2: Write `reports/endorsements.md`** in the structure of the other sections: the question, how endorsers and endorsements were identified (with links to the CSVs), findings, the selection-bias discussion next to every rate, limitations (the contested proxy and its agreement rate, endorsers not covered, a Republican-heavy list if that is what the data shows), and what's next. Neutral wording. Run the `humanizer` skill.
- [ ] **Step 3: Write `test_endorsements_report_numbers.py`** in the style of `tests/test_billionaire_report_numbers.py`: the committed JSON equals a fresh build, every cited number appears in the prose, and there are no em dashes.
- [ ] **Step 4: Open each PNG, run the full suite, and confirm the frozen files are unchanged:** `git diff --stat pre-election-model main -- reports/predictions/2026-general-model.csv reports/predictions/2026-general-simple.csv` must be empty.
- [ ] **Step 5: Commit** with message "Write the endorsements section for the 2026 House primaries".

## Self-Review Notes
- **Spec coverage:** dataset (Tasks 1 to 2), win rates by incumbent, open seat, and contested primary (Tasks 3 to 4), selection-bias discussion (Decision 6, Tasks 4 to 5), write-up (Task 5). The `candidates.primary_result` column in the schema stays unused on purpose, because outcomes are computed in analysis and not written back to the database.
- **Known risk:** a Democratic-side list may be much smaller than the Republican one. If so the report says so and does not stretch the comparison.
- **Open for you:** the endorser shortlist (Task 1, Step 2 is a stop-and-check-in) and Decisions 1, 3, 5, and 8.
