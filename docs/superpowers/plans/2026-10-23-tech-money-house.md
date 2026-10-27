# Tech Money Section, House Version: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix outside spending so it counts every committee's House money, label the crypto and AI networks with sources, and publish the House version of the tech money write-up before Nov 3, 2026.

**Architecture:** Outside spending moves from the `/schedules/schedule_e/by_candidate/` endpoint to the FEC bulk independent expenditure file, parsed the same way `src/fec/bulk.py` already handles the summary file. A new `src/analysis/tech_money.py` turns the database into tidy DataFrames, `scripts/build_tech_money_report.py` turns those into PNG charts and a numbers file, and `reports/tech-money.md` is the hand-written report that cites them.

**Tech Stack:** Python 3.13, pandas, requests, sqlite3, pytest, matplotlib (new).

**Spec:** `docs/superpowers/specs/2026-10-23-tech-money-page-design.md`

## Why the data source changes (found Oct 23 while planning)
- `by_candidate` totals by FEC candidate ID. Congressional Leadership Fund leaves `candidate_id` blank on its filings (646 of its 669 rows in the bulk file), so it showed $264K instead of about $67.9M through Sept 30. Any committee that files this way is undercounted.
- `https://www.fec.gov/files/bulk-downloads/{cycle}/independent_expenditure_{cycle}.csv` has every row with candidate name, state, district, office, election type (`ele_type`), and support or oppose, and is refreshed daily (latest receipt date was Oct 23).
- After dropping superseded filings, its sums through Sept 30 match each committee's `/committee/{id}/totals/` figure: Think Big exactly, CLF 67.48M vs 67.90M, HMP 46.77M vs 45.72M, Protect Progress 27.63M vs 29.20M.
- Rows with a blank `cand_id` also have a blank party (`cand_pty_aff`), so candidate ID and party are recovered by matching to `candidates` on race and last name.
- The raw `/schedules/schedule_e/` endpoint is not used. It pages by `last_index`, which `FecClient.iter_results` doesn't support, and it returned the same page repeatedly during testing.

## Global Constraints
- No em dashes anywhere: code, comments, docs, report, commit messages.
- NumPy-style docstrings. Comments match the density of `src/fec/bulk.py`.
- Commit messages in plain human voice, no prefixes, no co-author lines.
- Tests run on real saved rows, never invented field names.
- Every snapshot keyed by `pulled_at`. Every chart states its pull date.
- Every `pac_industries.csv` row has a `source_url` meeting the spec's sourcing standard.
- Neutral wording and equal party colors (blue D, red R) in charts and prose.
- Fallback (a): if Task 5's validation doesn't pass, the report shows network spending only and leaves out "share of all outside spending."

## Review Focus
1. **Amendment chains.** An amended filing must replace the original, not add to it. A transaction amended twice (A1 then A2) counts once. Pinned in Task 1.
2. **Blank candidate IDs that don't match any candidate** (misspelled names, candidates missing from `/candidates/`). These rows must keep their `race_id` and money, with `candidate_id` NULL, and be counted in the orphan report, not dropped. Pinned in Tasks 1 and 3.
3. **Two candidates in one race with the same last name.** The name match must not guess. Leave `candidate_id` NULL. Pinned in Task 1.
4. **Senate and presidential rows in the bulk file** must not leak into House totals. Pinned in Task 1.
5. **Rerunning the pull on the same day** must not double outside spending. With the new primary key, same-day reruns still replace rows. Pinned in Task 3.

---

### Task 1: Parse the bulk independent expenditure file

**Files:**
- Create: `src/fec/independent_expenditures.py`
- Create: `tests/fixtures/ie_sample.csv`
- Create: `tests/test_independent_expenditures.py`
- Modify: `scripts/save_fixtures.py` (add a function that writes `ie_sample.csv`)

**Interfaces:**
- Produces:
  - `download_independent_expenditures(cycle: int = CYCLE) -> str`: downloads the CSV, saves a copy to `data/raw/fec/independent_expenditure_{cycle}.csv` like `download_summary` does, returns the text.
  - `parse_independent_expenditures(text: str) -> list[dict]`: rows as dicts keyed by the CSV header, values stripped, empty strings as `None`.
  - `drop_superseded(rows: list[dict]) -> list[dict]`
  - `house_outside_spending(text: str, candidates: list[dict], pulled_at: str) -> list[dict]`: rows for the new `outside_spending` table (columns in Task 2).

- [ ] **Step 1: Save a real fixture.** Add `save_ie_sample()` to `scripts/save_fixtures.py`. It downloads the bulk file and writes the header plus real rows to `tests/fixtures/ie_sample.csv`: every row for one CLF House transaction with a blank `cand_id`, one transaction that has an A1 and an A2 version (search for `amndt_ind == "A2"`), one Senate row, one presidential row, and three or four ordinary House rows with a `cand_id`, one of them with `ele_type == "P"`. Keep it under 30 rows. Note in the docstring which rows serve which test.

- [ ] **Step 2: Write the failing tests** in `tests/test_independent_expenditures.py`, using the fixture's real values:
  - `test_drop_superseded_keeps_only_latest_amendment`: the A2 transaction appears once, with the A2 amount.
  - `test_drop_superseded_removes_filings_listed_as_previous`: no row's `file_num` equals any row's `prev_file_num` in the output.
  - `test_house_only`: no output row comes from the Senate or presidential fixture rows.
  - `test_aggregates_by_committee_candidate_support_election`: two fixture rows with the same committee, candidate, `sup_opp`, and `ele_type` become one row whose `total` is their sum and `count` is 2.
  - `test_blank_id_matched_by_race_and_last_name`: with `candidates=[{"candidate_id": "H6XX01234", "race_id": <CLF row's race>, "name": "<LAST>, <FIRST>", "party": "REP"}]`, the CLF row gets that `candidate_id` and `party == "REP"`.
  - `test_blank_id_unmatched_keeps_race_and_money`: with `candidates=[]`, the CLF row has `candidate_id is None`, the right `race_id`, its full `total`, and `candidate_key == f"{race_id}|{LASTNAME}"`.
  - `test_blank_id_ambiguous_last_name_not_guessed`: two candidates in that race share the last name, so `candidate_id is None`.
  - `test_election_type_kept`: the primary fixture row has `election_type == "P"`.
  - `test_race_id_matches_transform`: House at-large rows get district `"00"`, the same as `src.fec.transform.race_id`.

- [ ] **Step 3: Run the tests and confirm they fail**
  Run: `python -m pytest tests/test_independent_expenditures.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'src.fec.independent_expenditures'`

- [ ] **Step 4: Implement the four functions.**
  - `drop_superseded`: first drop every row whose `file_num` appears in any row's `prev_file_num`, then keep the row with the highest `file_num` for each `(spe_id, tran_id)`.
  - `house_outside_spending`: keep `can_office == "H"`; build `race_id` with `src.fec.transform.race_id`; resolve candidate ID and party (bulk `cand_id` first, otherwise a unique last-name match within the race, comparing uppercased text before the first comma); then sum `exp_amo` and count rows by `(spe_id, candidate_key, sup_opp, ele_type)`.
  - Party when `cand_id` is present: take it from `candidates` by ID, falling back to `cand_pty_aff`, so codes stay consistent with the `candidates` table (`DEM`, `REP`, ...).
  - Use `csv.DictReader` from the standard library, like `parse_summary`.

- [ ] **Step 5: Run the tests and confirm they pass**
  Run: `python -m pytest tests/test_independent_expenditures.py -v`
  Expected: 9 passed

- [ ] **Step 6: Commit**
  ```bash
  git add src/fec/independent_expenditures.py tests/test_independent_expenditures.py tests/fixtures/ie_sample.csv scripts/save_fixtures.py
  git commit -m "Parse the FEC bulk independent expenditure file, including filings with no candidate ID"
  ```

### Task 2: New `outside_spending` table, with the Oct 23 snapshot kept

**Files:**
- Modify: `src/schema.sql`
- Modify: `src/db.py`
- Modify: `tests/test_db.py`

**Interfaces:**
- Produces: the `outside_spending` table with columns `committee_id TEXT NOT NULL, candidate_key TEXT NOT NULL, candidate_id TEXT, candidate_name TEXT, party TEXT, race_id TEXT, election_type TEXT NOT NULL, support_oppose TEXT NOT NULL, pulled_at TEXT NOT NULL, total REAL, count INTEGER`, primary key `(committee_id, candidate_key, support_oppose, election_type, pulled_at)`.
- Produces: `create_schema(conn)` renames an old-style `outside_spending` (one without `election_type`) to `outside_spending_by_candidate_endpoint` before creating the new table.

- [ ] **Step 1: Write the failing tests** in `tests/test_db.py`:
  - `test_create_schema_moves_old_outside_spending`: create the old table by hand, insert one row, run `create_schema`; the row is now in `outside_spending_by_candidate_endpoint`, and `outside_spending` has an `election_type` column.
  - `test_create_schema_twice_keeps_new_rows`: insert a new-style row, run `create_schema` again; the row is still there.

- [ ] **Step 2: Run the tests and confirm they fail**
  Run: `python -m pytest tests/test_db.py -v`
  Expected: the two new tests FAIL

- [ ] **Step 3: Update `schema.sql`** with the new table and a comment explaining `candidate_key` (the FEC ID, or `race_id|LASTNAME` when the filing has none, because SQLite treats NULLs in a primary key as distinct and reruns would duplicate rows) and the `election_type` codes (P primary, G general, R runoff, S special, C convention, O other). **Then update `create_schema`** to check `PRAGMA table_info(outside_spending)` and rename the table when `election_type` is missing. Add a comment that this keeps the Oct 23 snapshot, which was built with a different method.

- [ ] **Step 4: Run all tests and confirm they pass**
  Run: `python -m pytest -v`
  Expected: the new db tests pass. Pipeline tests may fail until Task 3. Note which ones.

- [ ] **Step 5: Commit**
  ```bash
  git add src/schema.sql src/db.py tests/test_db.py
  git commit -m "Give outside spending a race and election type, and keep the old snapshot in its own table"
  ```

### Task 3: Pipeline uses the bulk file

**Files:**
- Modify: `src/pipeline.py`
- Modify: `src/fec/transform.py` (remove `outside_spending_row`)
- Modify: `tests/test_pipeline.py`, `tests/test_transform.py`
- Modify: `scripts/save_fixtures.py` (remove the `OUTSIDE_SPENDING_PATH` import and fixture)
- Delete: `tests/fixtures/outside_spending.json`

**Interfaces:**
- Consumes: `house_outside_spending`, `download_independent_expenditures` (Task 1).
- Produces: `run_pull(client, conn, pulled_at, races, summary_text, ie_text, pac_industries=None, max_pages=None) -> dict`. `orphan_counts` returns keys `totals_without_candidate`, `spending_without_candidate` (rows with `candidate_id IS NULL`), `spending_without_race` (`race_id` not in `races`), `candidates_without_race`.

- [ ] **Step 1: Update the tests** in `tests/test_pipeline.py`: pass `ie_text` read from `ie_sample.csv`, drop the outside spending fixture from `FakeClient`, and add:
  - `test_no_outside_spending_api_calls`: no call in `FakeClient.calls` goes to a `/schedules/` path.
  - `test_rerun_same_day_does_not_duplicate_spending`: two runs with the same `pulled_at` give the same `COUNT(*)` in `outside_spending`.
  - `test_orphan_counts_reports_unmatched_spending`: with the fixture's CLF row and no matching candidate, `spending_without_candidate >= 1`.
  Remove the transform test for `outside_spending_row`.

- [ ] **Step 2: Run the tests and confirm they fail**
  Run: `python -m pytest tests/test_pipeline.py -v`
  Expected: FAIL on the `run_pull` signature

- [ ] **Step 3: Update `run_pull` and `main`.** Delete `OUTSIDE_SPENDING_PATH`, `CANDIDATE_BATCH_SIZE`, `_batches`, the batching loop and its comment. Call `house_outside_spending(ie_text, candidates, pulled_at)`. `main` passes `download_independent_expenditures()`. Update the module docstring to name the new source.

- [ ] **Step 4: Run the full suite and confirm it passes**
  Run: `python -m pytest -v`
  Expected: all pass

- [ ] **Step 5: Run a sample pull**
  Run: `python -m src.pipeline --sample`
  Expected: completes, `outside_spending` rows > 0, and the orphan report prints all four keys

- [ ] **Step 6: Commit**
  ```bash
  git add -A src tests scripts
  git commit -m "Build outside spending from the bulk file instead of the by-candidate endpoint"
  ```

### Task 4: Network labels with sources

**Files:**
- Modify: `src/schema.sql` (`pac_industries` gains `network TEXT NOT NULL`)
- Modify: `src/manual.py`, `tests/test_manual.py`
- Modify: `data/manual/pac_industries.csv` (header becomes `committee_id,network,industry,source_url`)

**Interfaces:**
- Produces: `load_pac_industries(path) -> list[dict]` with keys `committee_id, network, industry, source_url`. `INDUSTRIES = {"crypto", "ai_industry", "ai_safety"}` in `src/manual.py`. Raises `ValueError` for an unknown industry or an empty network.

- [ ] **Step 1: Write the failing tests:** `test_unknown_industry_rejected` (`industry="tech"` raises `ValueError`) and `test_missing_network_rejected`.
- [ ] **Step 2: Run them and confirm they fail.** Run: `python -m pytest tests/test_manual.py -v`
- [ ] **Step 3: Implement the validation and schema change.** `create_schema` uses `CREATE TABLE IF NOT EXISTS`, and the old `pac_industries` table is empty, so add a short note in `db.py` and drop and recreate it if `network` is missing, following the same pattern as Task 2.
- [ ] **Step 4: Research and fill the CSV.** Start from the spec's committee list. For each committee, find a source meeting the spec's standard (FEC filing naming the parent group, shared treasurer, transfers between committees, the group's own statement, or a major outlet naming the committee). For every committee, check fec.gov for affiliated committees not on the list (for example, other Fairshake or Leading the Future affiliates), and include them if sourced. Public First's committees go in only if sourced. If a committee can't be sourced, leave it out and list it in the commit message body. Never use memory as a source.
- [ ] **Step 5: Run the tests and load the CSV.** Run: `python -m pytest -v` then `python -c "from src.manual import load_pac_industries; print(len(load_pac_industries()))"`. Expected: all pass, and the count prints with no error.
- [ ] **Step 6: Commit**
  ```bash
  git add src/schema.sql src/db.py src/manual.py tests/test_manual.py data/manual/pac_industries.csv
  git commit -m "Label crypto and AI super PAC networks with a source for every committee"
  ```

### Task 5: Full pull and validation against committee totals

**Files:**
- Create: `scripts/check_outside_spending.py`
- Modify: `README.md` (Snapshots table, Data Sources row for `outside_spending`, caveats)
- Modify: `tasks/lessons.md`

**Interfaces:**
- Produces: `compare_to_committee_totals(conn, client, pulled_at, committee_ids) -> pandas.DataFrame` with columns `committee_id, name, bulk_through_coverage, fec_reported, coverage_end_date, pct_diff`. `bulk_through_coverage` re-reads the saved bulk CSV (all offices, superseded filings dropped, dated by `dissem_dt`, falling back to `exp_date`, on or before `coverage_end_date`), because `/committee/{id}/totals/` covers all offices through the last periodic report.

- [ ] **Step 1: Run the full pull.** Run: `python -m src.pipeline`. Record the row counts and the orphan report.
- [ ] **Step 2: Write and run the check script** for every labeled network committee plus CLF, HMP, and the 10 largest super PACs by House spending. Print the table. Run: `python scripts/check_outside_spending.py`
- [ ] **Step 3: Decide pass or fallback.** Pass means every labeled network committee is within 5% of its FEC-reported total, and the total of the top 10 super PACs is within 5%. On pass, the report may show "share of all outside spending." Otherwise, use fallback (a). Write the result and the table into the README caveats.
- [ ] **Step 4: Update the README.** In the Snapshots table, mark Oct 23 as built with the by-candidate endpoint (now in `outside_spending_by_candidate_endpoint`) and add today's pull as the official pre-election snapshot. Update the `outside_spending` Data Sources row. Add caveats covering the blank-ID matching (with the unmatched count), primary versus general, and that the bulk file is built from 24- and 48-hour reports.
- [ ] **Step 5: Log the lesson** in `tasks/lessons.md`: the by-candidate endpoint silently dropped filings with no candidate ID. Pattern: compare an aggregate against an independent total for a few large known entities before trusting it.
- [ ] **Step 6: Commit**
  ```bash
  git add scripts/check_outside_spending.py README.md tasks/lessons.md
  git commit -m "Validate outside spending against FEC committee totals and record the pre-election snapshot"
  ```

### Task 6: Analysis tables

**Files:**
- Create: `src/analysis/__init__.py`, `src/analysis/tech_money.py`
- Create: `tests/test_tech_money.py`

**Interfaces:**
- Consumes: the `outside_spending`, `pac_industries`, `committees`, `candidates`, and `races` tables.
- Produces (all take `conn, pulled_at` and return `pandas.DataFrame`):
  - `network_totals`: `network, industry, total, n_candidates`
  - `party_buckets`: `network, bucket, total`, where `bucket` is one of `Supporting Democrats`, `Opposing Democrats`, `Supporting Republicans`, `Opposing Republicans`, `Other or unknown`. `DEM` and `DFL` count as Democrats, and `REP` as Republicans.
  - `competitiveness`: general election only (`election_type == "G"`). Columns `network, seat_type, total`, where `seat_type` is `Competitive` for Toss Up, Lean, or Likely ratings and `Safe` for Solid.
  - `primary_vs_general`: `network, election, total`, where `election` is `Primary`, `General`, or `Other`. Runoff, special, and convention count as `Other`.
  - `top_races(conn, pulled_at, n=10)`: `race_id, cook_rating, network_total, all_super_pac_total`
  - `network_share`: `network, total, share_of_super_pac_spending`. The denominator is all `outside_spending` from committees whose `committee_type` is in `("O", "V", "W")`.

- [ ] **Step 1: Write the failing tests.** Build a temporary database with `create_schema`, insert about 8 hand-written rows covering two networks, one unlabeled super PAC, a party committee (type not in O/V/W), a DFL candidate, a primary row, and a Solid race. Assert exact totals for each function. Include `test_party_committee_excluded_from_denominator` and `test_primary_money_not_in_competitiveness`.
- [ ] **Step 2: Run them and confirm they fail.** Run: `python -m pytest tests/test_tech_money.py -v`
- [ ] **Step 3: Implement** with SQL plus pandas, one small function per output.
- [ ] **Step 4: Run the tests and confirm they pass.** Run: `python -m pytest -v`
- [ ] **Step 5: Commit**
  ```bash
  git add src/analysis tests/test_tech_money.py
  git commit -m "Add tech money analysis tables"
  ```

### Task 7: Charts and the written report

**Files:**
- Create: `scripts/build_tech_money_report.py`
- Create: `reports/tech-money.md`, `reports/figures/*.png`, `reports/figures/tech_money_numbers.json`
- Modify: `requirements.txt` (add `matplotlib`), `README.md` (link to the report, mark Status), `tasks/todo.md`

**Interfaces:**
- Consumes: every function from Task 6, and the pass or fallback result from Task 5.

- [ ] **Step 1: Load the dataviz skill** before writing any chart code.
- [ ] **Step 2: Write the build script.** `python scripts/build_tech_money_report.py --pulled-at YYYY-MM-DD` writes:
  - `network_party_buckets.png`: horizontal stacked bars, one per network, in the five buckets
  - `competitive_vs_safe.png`: general election money by seat type, per network
  - `primary_vs_general.png`
  - `tech_money_numbers.json`: every number the prose cites, plus `top_races`
  - `network_share.png`, only when Task 5 passed
  Every chart's subtitle reads "FEC data as of <pulled_at>". Blue for Democrats, red for Republicans, gray for other, at equal saturation.
- [ ] **Step 3: Run it and look at every PNG.** Run: `python scripts/build_tech_money_report.py --pulled-at <Task 5 date>`. Expected: files written, and each chart is readable at GitHub's rendered width.
- [ ] **Step 4: Write `reports/tech-money.md`.** Sections: the question, the networks and how they were identified (link `pac_industries.csv`), findings with charts, method and caveats, and what's next (Senate and billionaires after Nov 3). Check every number against `tech_money_numbers.json`. Read the prose once for neutrality: no judging verbs, and describe both parties the same way. Run the `humanizer` skill on the prose and confirm there are no em dashes (`grep -cP "\x{2014}" reports/tech-money.md` prints 0).
- [ ] **Step 5: Update the README and todo.** Link the report from the README, update Status, and tick the Step 2 items in `tasks/todo.md` that are done.
- [ ] **Step 6: Commit**
  ```bash
  git add scripts/build_tech_money_report.py reports requirements.txt README.md tasks/todo.md
  git commit -m "Write the House version of the tech money report"
  ```
