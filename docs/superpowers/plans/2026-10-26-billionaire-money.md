# Billionaire Money: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build section 2 of the write-up before Nov 3, 2026: which billionaires fund 2026 super PACs (including sourced organization and LLC money), how much reached House races, which PACs are billionaire-backed (at least 50%), and how those PACs' primary candidates did.

**Architecture:**
- `src/fec/donors.py` pulls Schedule A contributions and PAC committee totals into new tables.
- Two hand-built, sourced CSVs name the billionaires and their entities.
- `src/analysis/billionaires.py` computes giving, concentration, House share, lean, and primary outcomes.
- A build script writes charts, a numbers JSON, and `reports/billionaire-money.md`.

**Tech Stack:** Python 3.13, pandas, requests, sqlite3, pytest, matplotlib.

**Spec:** `docs/superpowers/specs/2026-10-26-billionaire-money-design.md`

## Global Constraints
- No em dashes anywhere. NumPy docstrings. Comment density matches `src/fec/history.py`.
- Plain commit messages, never a Co-Authored-By or attribution line.
- Tests run on real saved API rows, never invented field names.
- Never modify existing tables or the frozen files in `reports/predictions/`. New tables only.
- Every person-to-entity link and every Forbes match has a `source_url`. Nothing is labeled from memory.
- House spending comes from `outside_spending` at `pulled_at = '2026-10-24'`.
- No hand-assigned party side. Lean is computed (spec).
- Neutral wording, with no judging verbs.
- Work on branch `billionaire-money` (stacked on `money-and-winning`). Don't push without the controller's go-ahead.

## Review Focus
1. **Donor name variants** ("ADELSON, MIRIAM DR.", "ADELSON, MIRIAM"): they merge into one person through `contributor_name_variants` in the CSV, while different people who share a surname stay separate. Pinned in Task 3.
2. **Refunds and negative amounts** are netted, not dropped. Pinned in Task 1.
3. **Memo or earmark rows** (`memo_code == "X"`) are excluded so pass-through gifts don't count twice. Pinned in Task 1.
4. **A PAC whose itemized total doesn't reconcile with its committee totals** is reported as unreconciled and never classified as billionaire-backed. Pinned in Task 3.
5. **A supported candidate with no candidate ID or nominee match** goes to the review list, never counted as a loss. Pinned in Task 5.

---

### Task 1: Load Schedule A contributions and PAC totals

**Files:**
- Create: `src/fec/donors.py`, `tests/test_donors.py`, `tests/fixtures/schedule_a_sample.json`, `tests/fixtures/pac_totals_sample.json`
- Modify: `src/fec/client.py` (add keyset iteration), `tests/test_client.py`, `src/schema.sql`, `scripts/save_fixtures.py`
- Create: `scripts/load_donors.py`

**Interfaces:**
- Produces:
  - `FecClient.iter_keyset(path, params, max_pages=None)`: yields results, following `pagination.last_indexes` by merging them into the next request's params. Stops when results are empty or `last_indexes` is missing.
  - Table `donor_contributions(sub_id TEXT PRIMARY KEY, cycle INTEGER, committee_id TEXT, contributor_name TEXT, entity_type TEXT, amount REAL, receipt_date TEXT, memo_code TEXT, pulled_at TEXT)`.
  - Table `pac_totals(committee_id TEXT, cycle INTEGER, receipts REAL, independent_expenditures REAL, coverage_end_date TEXT, pulled_at TEXT, PRIMARY KEY (committee_id, cycle, pulled_at))`.
  - `contribution_row(rec: dict, pulled_at: str) -> dict`.
  - `large_contributions(client, cycle: int, min_amount: float) -> list[dict]`: queries `/schedules/schedule_a/` with `two_year_transaction_period`, `min_amount`, `recipient_committee_type` O/V/W, and `sort=-contribution_receipt_amount`.
  - `contributions_by_name(client, cycle: int, name: str) -> list[dict]`: all amounts, recipient types O/V/W.
  - `contributions_to_committee(client, cycle: int, committee_id: str) -> list[dict]`
  - `pac_totals_rows(client, cycle: int, committee_ids: list[str], pulled_at: str) -> list[dict]`
  - `net_amount(rows) -> float`: sums `amount` across non-memo rows, so refunds (negative) reduce the total.

- [ ] **Step 1: Save real fixtures.** Use the API, with the key stripped as in `scripts/save_fixtures.py`. Save one page of large contributions (it must include an `entity_type` of IND, ORG, and PAC, a memo row, and a negative amount if one can be found, possibly by also querying a known refund), plus committee totals for America PAC (C00879510) and one other PAC.
- [ ] **Step 2: Write failing tests:** `test_iter_keyset_follows_last_indexes` (a fake session with two pages), `test_contribution_row_fields`, `test_memo_rows_excluded_from_net`, `test_refunds_reduce_net`, `test_pac_totals_row_fields`.
- [ ] **Step 3: Run them and confirm they fail.** Run: `.venv/Scripts/python -m pytest tests/test_donors.py tests/test_client.py -v`
- [ ] **Step 4: Implement.** `iter_keyset` must not change `iter_results`.
- [ ] **Step 5: Write `scripts/load_donors.py`** with two modes. `--large` loads all contributions of $250K or more for 2026. `--names` and `--committees` read a list and load contributions by name or by committee. It writes to `data/processed/midterm_money.db` with today's `pulled_at`, then prints counts. Run `--large` for real and record the row count and how many calls it took.
- [ ] **Step 6: Run the full suite, then commit** with message "Load 2026 super PAC contributions and committee totals".

### Task 2: Research billionaires and entities (sourced CSVs)

**Files:**
- Create: `data/manual/billionaires.csv` with columns `person,household_members,contributor_name_variants,forbes_url,note`. Use `;` as the separator inside fields.
- Create: `data/manual/donor_entities.csv` with columns `entity_name,person,source_url,evidence_type,note`. `evidence_type` is one of `fec_filing`, `own_statement`, or `news`.
- Create: `data/manual/large_donors_not_on_forbes.csv` with columns `donor_name,total,note`.
- Modify: `src/manual.py` (add `load_billionaires`, `load_donor_entities`), `tests/test_manual.py`.

**Interfaces:**
- Produces:
  - `load_billionaires(path) -> list[dict]`: `household_members` and `contributor_name_variants` come back split into lists. It raises if `forbes_url` is empty.
  - `load_donor_entities(path) -> list[dict]`: it raises if `source_url` is empty or `evidence_type` is unknown.

- [ ] **Step 1: Write failing loader tests:** `test_billionaire_requires_forbes_url`, `test_variants_split`, `test_entity_requires_source`, `test_entity_evidence_type_validated`.
- [ ] **Step 2: Run them, confirm they fail, implement, then confirm they pass.**
- [ ] **Step 3: Build the candidate list from the database.**
  - Individuals (`entity_type = 'IND'`) with $1M or more net, after merging obvious variants.
  - Organizations with $1M or more net.
  - Print both lists with totals.
- [ ] **Step 4: Research each candidate.** For each individual: is there a Forbes profile for the April 2026 World's Billionaires list (record the URL), what are the name variants in the FEC data, and does a spouse give alongside them under the household rule? Individuals who aren't on Forbes go in `large_donors_not_on_forbes.csv`. For each organization of $1M or more: is there a public source (an FEC filing that names the person, their own statement, or a major news outlet) tying it to a billionaire? Unsourced organizations aren't added; list them in the commit body. Use WebSearch/WebFetch and the FEC API, never memory. Apply the same standard to everyone, regardless of party.
- [ ] **Step 5: Load the full giving.** Run `scripts/load_donors.py --names` for every variant of every listed person and their entities.
- [ ] **Step 6: Run the full suite, then commit** with message "Add sourced billionaire and donor entity lists". The commit body lists the organizations left unattributed and their totals.

### Task 3: Giving, concentration, and the billionaire-backed PAC list

**Files:**
- Create: `src/analysis/billionaires.py`, `tests/test_billionaires.py`

**Interfaces:**
- Consumes: Task 1 tables, plus the Task 2 loaders.
- Produces:
  - `household_giving(conn, billionaires, entities, cycle=2026) -> DataFrame`, with columns `person, committee_id, direct, via_entities, total`. Memo rows are excluded and refunds netted.
  - `reconcile(conn, committee_ids, cycle=2026, tolerance=0.05) -> DataFrame`, with columns `committee_id, itemized, receipts, diff_pct, reconciled`. Itemized means the sum of non-memo `donor_contributions` to the PAC, loaded with `contributions_to_committee`. Reconciled means `abs(diff_pct) <= tolerance`.
  - `concentration(giving, conn, cycle=2026) -> DataFrame`, with columns `committee_id, person, share`, where share = total over receipts.
  - `billionaire_backed(concentration_df, reconcile_df, threshold=0.5) -> DataFrame`, with columns `committee_id, person, share, status`. Status is `backed` for share of at least 0.5 that reconciles, `unreconciled` for share of at least 0.5 that doesn't reconcile, and `near` for share between 0.35 and 0.5. There is no joint threshold.

- [ ] **Step 1: Write failing tests on a tmp database:**
  - `test_variants_merge_to_one_person`
  - `test_same_surname_different_people_stay_separate`
  - `test_entity_money_attributed`
  - `test_memo_excluded`
  - `test_refund_nets`
  - `test_share_at_threshold_is_backed` (exactly 0.5)
  - `test_unreconciled_never_backed`
  - `test_two_donors_at_30_percent_not_backed`
  - `test_near_band_flagged`
- [ ] **Step 2: Run them, confirm they fail, implement, then confirm they pass.**
- [ ] **Step 3: Run on real data.**
  - Load `contributions_to_committee` and `pac_totals_rows` for every PAC where any billionaire's share is 0.2 or more.
  - Print the reconcile table and the backed, near, and unreconciled lists.
  - For `near` PACs, research entities of $100K or more (as in Task 2 Step 4) and update the CSV.
  - For any `unreconciled` PAC (America PAC is expected to be one), investigate the gap. Check whether the API is missing pages, whether money came through transfers or unitemized gifts, or whether the totals belong to a different period. Report the cause in a code comment and in the task report. Don't change the rule to force a classification.
- [ ] **Step 4: Run the full suite, then commit** with message "Compute billionaire giving and identify billionaire-backed super PACs".

### Task 4: House share and lean

**Files:**
- Modify: `src/analysis/billionaires.py`, `tests/test_billionaires.py`

**Interfaces:**
- Produces:
  - `house_share(giving, conn, pulled_at='2026-10-24') -> DataFrame`, with columns `person, total_giving, house_dollars, house_pct, other_or_unspent`.
    - For each PAC: the person's share of receipts times the PAC's House IE total in `outside_spending` (all election types and both sides, committee types O/V/W).
    - The PAC's IE total across all offices comes from the saved bulk IE file through `src.fec.independent_expenditures`.
    - `other_or_unspent` = total_giving minus the person's attributed share of the PAC's all-office IE.
  - `lean(giving, conn, pulled_at='2026-10-24') -> DataFrame`, with columns `person, dem_helping, rep_helping, dem_share`.
    - Dem-helping means supporting DEM or DFL, or opposing REP. Rep-helping means the reverse.
    - Each is weighted by the person's share of each PAC.
    - `dem_share` is NaN when there's no House spending.

- [ ] **Step 1: Write failing tests:** `test_house_share_proportional`, `test_other_or_unspent_nonnegative_when_pac_underspent`, `test_lean_counts_oppose_as_helping_other_party`, `test_lean_nan_without_house_spending`.
- [ ] **Step 2: Run them, confirm they fail, implement, then confirm they pass.**
- [ ] **Step 3: Run on real data and print both tables.** Report the total money by lean bucket (`dem_share` above 0.5, below 0.5, or NaN) as the lopsidedness check.
- [ ] **Step 4: Commit** with message "Estimate how much billionaire money reached House races and which way it leaned".

### Task 5: Primary outcomes for billionaire-backed PACs

**Files:**
- Modify: `src/analysis/billionaires.py`, `tests/test_billionaires.py`

**Interfaces:**
- Consumes: `billionaire_backed` (status `backed` only), the `outside_spending` table, `reports/predictions/2026-general-simple.csv` (nominee candidate IDs, read-only), and `src.nominees.parse_nominees` plus the name matching in `src.predict.simple` for fallback.
- Produces:
  - `primary_support(conn, backed_pacs, pulled_at='2026-10-24', min_spend=10000) -> DataFrame`, with columns `committee_id, person, race_id, candidate_key, candidate_id, candidate_name, party, support_oppose, total`. It uses `election_type` 'P' plus primary runoffs if coded.
  - `primary_outcomes(support_df, nominee_ids: set, nominees: list) -> DataFrame`. It adds an `outcome` column:
    - `won`: nominee by ID, or by race and name
    - `lost`: not a nominee, with a candidate_id, and the race's nominees are known
    - `review`: no candidate_id and no name match, or the race has unconfirmed status
  - Opposed candidates get `outcome_for_pac`, which is `wanted` when the opposed candidate isn't a nominee.
  - `win_rates(outcomes_df) -> dict`: pooled and per-PAC counts and rates over supported candidates with won or lost outcomes, plus the number in `review`.

- [ ] **Step 1: Write failing tests:**
  - `test_min_spend_threshold` (a $9,999 row is excluded)
  - `test_distinct_candidate_counted_once_per_race` (two PACs backing one candidate count once in the pooled rate)
  - `test_win_by_candidate_id`
  - `test_win_by_name_fallback`
  - `test_unmatched_goes_to_review`
  - `test_top_two_advance_counts_as_win`
  - `test_opposed_reported_separately`
- [ ] **Step 2: Run them, confirm they fail, implement, then confirm they pass.**
- [ ] **Step 3: Run on real data.** Print the per-PAC table, the pooled rate, and the review list. Hand-check up to 10 review items against Wikipedia and add a note in the report.
- [ ] **Step 4: Commit** with message "Score primary outcomes for candidates backed by billionaire-funded super PACs".

### Task 6: Charts, numbers, and the write-up

**Files:**
- Create: `scripts/build_billionaire_report.py`, `reports/billionaire-money.md`, `reports/figures/billionaire_money_numbers.json`, `reports/figures/*.png`, `tests/test_billionaire_report_numbers.py`
- Modify: `README.md` (link to the section, update Status), `tasks/todo.md`

**Interfaces:**
- Consumes: Tasks 3 to 5 functions, plus the CSVs.

- [ ] **Step 1: Load the `dataviz` skill.** Then write the build script, following `scripts/build_money_winning_report.py`.
  - Charts: giving by person, split into direct and through entities; House share per person; and primary win rates per backed PAC with counts.
  - Party colors only where party is the encoding.
  - Each chart's subtitle carries its data date.
- [ ] **Step 2: Write `reports/billionaire-money.md`,** in the same structure as `reports/tech-money.md`.
  - The question.
  - How billionaires and entities were identified, with links to the CSVs.
  - Giving and where it went.
  - The lopsidedness check, explained: computed lean, and the fact that more of one side's money moves through organizations.
  - Billionaire-backed PACs, including unreconciled ones and why.
  - Primary outcomes, with the selection-bias caveat next to the rate.
  - Limitations: untraceable dark money, pass-throughs not followed, the proportional House-share assumption, contested primaries unknown, and the Forbes April snapshot.
  - What's next: the general election after Nov 3.
  - Neutral wording. Run the `humanizer` skill.
- [ ] **Step 3: Write `test_billionaire_report_numbers.py`** in the style of `tests/test_money_winning_report_numbers.py` (or whatever section 3's test file is named). The committed JSON must equal a fresh build, every cited number must appear in the prose, and there must be no em dashes.
- [ ] **Step 4: Open each PNG, run the full suite, and confirm no frozen file changed:** `git diff --stat money-and-winning -- reports/predictions/` must be empty.
- [ ] **Step 5: Commit** with message "Write section 2 on billionaire money in 2026 House races".
