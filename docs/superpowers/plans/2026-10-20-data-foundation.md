# Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a SQLite database of 2026 House candidates, fundraising totals, super PACs, outside spending, and Cook ratings that one command can refresh.

**Architecture:** A small `src/` package. `fec/client.py` handles HTTP, pagination, and rate limits. `fec/transform.py` turns API records into table rows using pure functions. `db.py` owns the schema and inserts. `ratings.py` parses Cook ratings from a pinned Wikipedia revision. `pipeline.py` wires them together behind a CLI. Every network-facing piece accepts an injected session or client so tests never call the real API.

**Tech Stack:** Python 3.13, requests, pandas, beautifulsoup4, python-dotenv, pytest, sqlite3 (standard library).

**Spec:** `docs/superpowers/specs/2026-10-20-midterm-money-design.md` (phase 1). Phases 2 to 5 get their own plans.

## Global Constraints

- Python 3.13. Run tests with `python -m pytest` from the repo root.
- Imports use `from src...`, enabled by `pytest.ini` with `pythonpath = .` (same as `midterm-polling-messaging`).
- Every path comes from `src/config.py`. No module hardcodes a file location.
- OpenFEC base URL: `https://api.open.fec.gov/v1`. Cycle: `2026`. API key read from `.env` as `FEC_API_KEY`.
- Never hardcode a rate limit. Read `X-RateLimit-Remaining` and back off on HTTP 429.
- Missing money values are stored as `NULL`, never coerced to `0`.
- `race_id` format is `ST-DD` with a zero-padded district. At-large seats are `00` (the FEC's own convention), e.g. `AK-00`, `CA-07`.
- No em dashes in code, comments, docstrings, markdown, or commit messages.
- NumPy-style docstrings on every public function.
- Commit messages in plain human voice. No `feat:`-style prefixes, no emoji, no co-author lines.

## Review Focus

1. **At-large districts.** The FEC sends `"00"` (or sometimes `"0"` or empty) and Wikipedia says `"Alaska at-large"`. Both must become `AK-00` or the ratings join silently drops those states. Pinned in Task 4 and Task 5.
2. **A 429 in the middle of pagination.** The client must retry the same page and continue, with no lost or duplicated pages. Pinned in Task 2.
3. **Candidates with no money reported yet.** A `None` from the API must stay `NULL`. Treating it as `$0` would make new candidates look like they raised nothing. Pinned in Task 4.
4. **Rerunning the pull.** Running twice with the same `pulled_at` must not duplicate rows. A new `pulled_at` must append a new snapshot. Pinned in Task 3 and Task 7.
5. **Non-voting delegates and unknown labels.** DC and territory candidates must load without errors. A ratings label that doesn't match a state must raise an error naming the label, not crash on a `KeyError`. Pinned in Task 4 and Task 5.

## File Structure

```
midterm-money-2026/
  pytest.ini
  requirements.txt
  src/
    __init__.py
    config.py           paths, constants, load_api_key()
    states.py           STATE_CODES: state name -> postal code (50 states + DC + territories)
    db.py               connect(), create_schema(), upsert_rows()
    schema.sql          CREATE TABLE statements
    ratings.py          Wikipedia Cook ratings download + parse
    manual.py           load_pac_industries() for hand-built CSVs
    pipeline.py         run_pull() + CLI
    fec/
      __init__.py
      client.py         FecClient
      transform.py      race_id() and *_row() mappers
  tests/
    fixtures/           real API responses saved in Task 4
    test_config.py
    test_client.py
    test_db.py
    test_transform.py
    test_ratings.py
    test_manual.py
    test_pipeline.py
  data/
    manual/pac_industries.csv   committed, hand-built
    raw/                        gitignored
    processed/                  gitignored, holds midterm_money.db
```

---

### Task 1: Project scaffolding and config

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `src/__init__.py`, `src/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `PROJECT_ROOT`, `DATA_DIR`, `RAW_DIR`, `MANUAL_DIR`, `PROCESSED_DIR`, `DB_PATH` (`PROCESSED_DIR / "midterm_money.db"`), `FEC_BASE_URL`, `CYCLE = 2026`; `load_api_key(env_path: Path | None = None) -> str`.

- [ ] **Step 1: Create `requirements.txt`** with `requests`, `pandas`, `beautifulsoup4`, `python-dotenv`, `pytest`. Create `pytest.ini` copied from `midterm-polling-messaging` (`pythonpath = .`, `testpaths = tests`).

- [ ] **Step 2: Create a virtual environment and install**

Run: `python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt`
Expected: installs without errors.

- [ ] **Step 3: Write the failing tests**

```python
def test_load_api_key_reads_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("FEC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("FEC_API_KEY=abc123\n")
    assert load_api_key(env) == "abc123"

def test_load_api_key_missing_explains_how_to_fix(tmp_path, monkeypatch):
    monkeypatch.delenv("FEC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="api.data.gov"):
        load_api_key(tmp_path / ".env")
```

- [ ] **Step 4: Run to verify failure**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 5: Implement `src/config.py`**, following the module docstring and comment style of `midterm-polling-messaging/src/config.py`. `load_api_key` calls `dotenv_values(env_path or PROJECT_ROOT / ".env")`, falls back to `os.environ`, and raises `RuntimeError` telling the user to copy `.env.example` and get a key at api.data.gov.

- [ ] **Step 6: Run to verify pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pytest.ini src/__init__.py src/config.py tests/test_config.py
git commit -m "Add project config and API key loading"
```

---

### Task 2: OpenFEC client

**Files:**
- Create: `src/fec/__init__.py`, `src/fec/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `FEC_BASE_URL` from Task 1.
- Produces: `class FecApiError(Exception)`; `class FecClient(api_key: str, session=None, sleep=time.sleep, max_retries: int = 5, cooldown_seconds: int = 60)` with `get(path: str, params: dict | None = None) -> dict` and `iter_results(path: str, params: dict | None = None, max_pages: int | None = None) -> Iterator[dict]`.

Behavior the tests pin:
- `get` adds `api_key` to params and sends `GET {FEC_BASE_URL}{path}`.
- HTTP 429: sleep `min(2 ** attempt, 60)` seconds and retry the same request, up to `max_retries`, then raise `FecApiError`.
- Any other non-200 status raises `FecApiError` immediately with the status code and response text (a 403 means a bad key, and retrying won't help).
- When a response has `X-RateLimit-Remaining` of `"0"`, sleep `cooldown_seconds` before returning.
- `iter_results` requests `per_page=100`, yields each item in `results`, and stops when `page >= pagination["pages"]` or after `max_pages`.

- [ ] **Step 1: Write the failing tests** using a fake session (no extra dependencies):

```python
class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code, self._payload = status_code, payload or {}
        self.headers, self.text = headers or {}, "error body"
    def json(self):
        return self._payload

class FakeSession:
    """Returns queued responses in order and records each request's params."""
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)

def page(n, pages, items):
    return FakeResponse(payload={"results": items, "pagination": {"page": n, "pages": pages}})
```

Tests:
- `test_get_sends_api_key`: assert `session.calls[0][1]["api_key"] == "KEY"` and the URL ends with `/candidates/`.
- `test_iter_results_follows_every_page`: 3 pages of 2 items each, so the result list has 6 items and `[c[1]["page"] for c in session.calls] == [1, 2, 3]`.
- `test_iter_results_respects_max_pages`: 3 pages available, `max_pages=1`, so 2 items and one call.
- `test_retries_429_on_same_page`: responses `[page(1, 2, a), FakeResponse(429), page(2, 2, b)]`, so all items come back, the page params are `[1, 2, 2]`, and `sleeps == [2]` (the attempt counter starts at 1).
- `test_gives_up_after_max_retries`: six 429s with `max_retries=5` raises `FecApiError`.
- `test_403_raises_without_retry`: raises `FecApiError` matching `"403"`, with exactly one call.
- `test_cools_down_when_remaining_hits_zero`: headers `{"X-RateLimit-Remaining": "0"}` with `cooldown_seconds=60`, so `sleeps == [60]`.

`sleep` is injected as `sleeps.append` so the tests never actually wait.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `FecClient` in `src/fec/client.py`.** Default `session` is `requests.Session()`. Use `timeout=30` on every request. Add a comment explaining why a 429 is retried but other errors are not.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_client.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/fec tests/test_client.py
git commit -m "Add OpenFEC client with pagination and rate limit handling"
```

---

### Task 3: SQLite schema and inserts

**Files:**
- Create: `src/schema.sql`, `src/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `connect(db_path: Path) -> sqlite3.Connection` (creates the parent folder); `create_schema(conn) -> None` (safe to run repeatedly); `upsert_rows(conn, table: str, rows: list[dict]) -> int` (returns the row count, raises `ValueError` for a table not in the schema).

Tables and primary keys:

| Table | Columns | Primary key |
|---|---|---|
| `races` | race_id, state, district, cook_rating, cook_pvi | race_id |
| `candidates` | candidate_id, name, party, state, district, race_id, incumbent_challenge, primary_result | candidate_id |
| `committees` | committee_id, name, committee_type, designation | committee_id |
| `candidate_totals` | candidate_id, pulled_at, receipts, disbursements, cash_on_hand, individual_contributions, pac_contributions | (candidate_id, pulled_at) |
| `outside_spending` | committee_id, candidate_id, support_oppose, pulled_at, total, count | (committee_id, candidate_id, support_oppose, pulled_at) |
| `pac_industries` | committee_id, industry, source_url | committee_id |

Money columns are `REAL`, `pulled_at` is `TEXT` in ISO date format. **No foreign keys:** each FEC endpoint filters differently (for example, a candidate can have totals but fail the `has_raised_funds` filter), so orphan rows are expected. Task 7 reports orphan counts instead of rejecting rows. Put this reasoning in a comment at the top of `schema.sql`.

- [ ] **Step 1: Write the failing tests** (use `tmp_path / "test.db"`)
  - `test_create_schema_is_repeatable`: call twice, and `sqlite_master` lists all 6 tables.
  - `test_upsert_same_row_twice_keeps_one`: upsert the same candidate twice, `COUNT(*) == 1`, and the second call's `name` value wins.
  - `test_new_pulled_at_appends_snapshot`: totals for `H6XX00001` at `2026-10-20` and `2026-10-23`, so `COUNT(*) == 2`.
  - `test_upsert_rejects_unknown_table`: `pytest.raises(ValueError, match="nope")`.
  - `test_null_money_stays_null`: insert `receipts=None`, and reading it back gives `None`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/schema.sql` and `src/db.py`.** `create_schema` runs the file with `executescript` (all statements use `CREATE TABLE IF NOT EXISTS`). `upsert_rows` checks the table name against the tables in `sqlite_master` before building `INSERT OR REPLACE`. Comment that table names can't be bound as SQL parameters, which is why they're validated.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/schema.sql src/db.py tests/test_db.py
git commit -m "Add SQLite schema with snapshot keys for FEC money data"
```

---

### Task 4: Real API fixtures and record transforms

**Files:**
- Create: `scripts/save_fixtures.py`, `tests/fixtures/*.json`, `src/fec/transform.py`
- Test: `tests/test_transform.py`

**Interfaces:**
- Consumes: `FecClient`, `load_api_key`.
- Produces: `race_id(state: str, district: str | None) -> str`; `candidate_row(rec: dict) -> dict`; `committee_row(rec: dict) -> dict`; `totals_row(rec: dict, pulled_at: str) -> dict`; `outside_spending_row(rec: dict, pulled_at: str) -> dict`. Output keys match the Task 3 column names exactly.

- [ ] **Step 1: Save one real page from each endpoint.** `scripts/save_fixtures.py` calls `client.get` once (with `per_page=5`) for each endpoint below and writes `tests/fixtures/<name>.json`. It also strips `api_key` from any URL in the payload before saving.

| Fixture | Path | Params |
|---|---|---|
| `candidates` | `/candidates/` | `office=H, election_year=2026, has_raised_funds=true` |
| `totals` | `/candidates/totals/` | `office=H, election_year=2026, cycle=2026` |
| `committees` | `/committees/` | `cycle=2026, committee_type=["O", "V", "W"]` |
| `outside_spending` | `/schedules/schedule_e/by_candidate/` | `cycle=2026, office=H` |

Run: `python scripts/save_fixtures.py`
Expected: 4 JSON files, each with a non-empty `results` list.

- [ ] **Step 2: Confirm field names against the fixtures.** These are the expected source fields. If a fixture uses a different name, use the fixture's name and note it in a comment:

| Output column | Source field |
|---|---|
| cash_on_hand | `cash_on_hand_end_period` |
| individual_contributions | `individual_contributions` |
| pac_contributions | `other_political_committee_contributions` |
| support_oppose | `support_oppose_indicator` (`S` / `O`) |
| total | `total` |

- [ ] **Step 3: Write the failing tests**

```python
@pytest.mark.parametrize("state, district, expected", [
    ("CA", "7", "CA-07"), ("CA", "07", "CA-07"),
    ("AK", "00", "AK-00"), ("AK", "0", "AK-00"), ("WY", None, "WY-00"), ("DC", "00", "DC-00"),
])
def test_race_id(state, district, expected):
    assert race_id(state, district) == expected
```

Plus:
- `test_candidate_row_from_fixture`: the first fixture record maps to exactly the 8 `candidates` columns, with `primary_result is None` and `race_id` built by `race_id()`.
- `test_totals_row_keeps_missing_money_null`: a record with `receipts: None` gives `row["receipts"] is None`.
- `test_totals_row_from_fixture` and `test_outside_spending_row_from_fixture`: the keys equal the Task 3 column sets and `pulled_at` is passed through.

- [ ] **Step 4: Run to verify failure**

Run: `python -m pytest tests/test_transform.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 5: Implement `src/fec/transform.py`.** Each `*_row` function is a plain dict built with `rec.get(...)`. No pandas.

- [ ] **Step 6: Run to verify pass**

Run: `python -m pytest tests/test_transform.py -v`
Expected: all passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/save_fixtures.py tests/fixtures src/fec/transform.py tests/test_transform.py
git commit -m "Map FEC candidate, totals, committee, and spending records to table rows"
```

---

### Task 5: Cook ratings and PVI from Wikipedia

**Files:**
- Create: `src/states.py`, `src/ratings.py`
- Modify: `src/config.py` (add `WIKIPEDIA_DIR`, `COOK_RATINGS_PAGE = (title, revision_id)`)
- Test: `tests/test_ratings.py`

**Interfaces:**
- Consumes: `race_id()` from Task 4.
- Produces: `STATE_CODES: dict[str, str]` (uppercase name to postal code, 50 states + DC + AS, GU, MP, PR, VI); `normalize_rating(raw: str) -> str`; `parse_ratings_table(html: str) -> pd.DataFrame` with columns `label, cook_pvi, cook_rating`; `label_to_race_id(label: str) -> str`; `download_ratings_page(page=COOK_RATINGS_PAGE) -> Path`; `load_races(html_path: Path) -> list[dict]` (rows for the `races` table).

- [ ] **Step 1: Pin the source page.** Find the Wikipedia page holding the 2026 House Cook ratings table with a PVI column (check `2026_United_States_House_of_Representatives_elections` first). Copy the current revision ID from the page history into `COOK_RATINGS_PAGE`. Add a comment that it's pinned so the same table can be downloaded again.

- [ ] **Step 2: Write the failing tests.** Port `normalize_rating` and `parse_cook_table` from `midterm-polling-messaging/src/polling/ratings.py`, including their tests, and extend the parser to capture the column whose header starts with `"PVI"` or `"CPVI"`. The HTML fixture has a footnote in the header, a repeated header row, `"Alaska at-large"`, and `"Lean R (flip)"`. New tests:

```python
@pytest.mark.parametrize("label, expected", [
    ("Arizona 2", "AZ-02"), ("Alaska at-large", "AK-00"), ("New York 17", "NY-17"),
])
def test_label_to_race_id(label, expected):
    assert label_to_race_id(label) == expected

def test_label_to_race_id_unknown_state_names_label():
    with pytest.raises(ValueError, match="Atlantis 1"):
        label_to_race_id("Atlantis 1")
```

Also `test_parse_ratings_table_captures_pvi`: the AK row has `cook_pvi == "R+8"`.

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_ratings.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `src/states.py` and `src/ratings.py`.** The module docstring credits the method to `midterm-polling-messaging` and explains that 2026 PVI must come from the 2026 page, because Texas, California, and other states redrew their maps. `download_ratings_page` uses the same Wikipedia URL and `User-Agent` approach as the old project and saves to `data/raw/wikipedia/`.

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_ratings.py -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/states.py src/ratings.py src/config.py tests/test_ratings.py
git commit -m "Parse 2026 Cook House ratings and PVI from a pinned Wikipedia revision"
```

---

### Task 6: Hand-built PAC industry labels

**Files:**
- Create: `data/manual/pac_industries.csv` (header only: `committee_id,industry,source_url`), `src/manual.py`
- Modify: `src/config.py` (add `PAC_INDUSTRIES_CSV`)
- Test: `tests/test_manual.py`

**Interfaces:**
- Produces: `load_pac_industries(path: Path = PAC_INDUSTRIES_CSV) -> list[dict]`.

Rows are filled in during phase 2. This task only makes sure that any row added later is valid.

- [ ] **Step 1: Write the failing tests** (CSV written to `tmp_path`)
  - `test_loads_valid_rows`: 2 rows in gives 2 dicts with the 3 keys.
  - `test_header_only_file_returns_empty_list`.
  - `test_row_without_source_raises`: `ValueError` matching the committee_id. Every label is a judgment call, so it has to cite where it came from.
  - `test_duplicate_committee_raises`: `ValueError` matching `"duplicate"`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_manual.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `load_pac_industries`** with `csv.DictReader`, stripping whitespace from values.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_manual.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add data/manual/pac_industries.csv src/manual.py src/config.py tests/test_manual.py
git commit -m "Add validated loader for hand-labeled PAC industries"
```

---

### Task 7: Pipeline and CLI

**Files:**
- Create: `src/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `run_pull(client, conn, pulled_at: str, races: list[dict], max_pages: int | None = None) -> dict[str, int]` (rows written per table); `orphan_counts(conn) -> dict[str, int]`; CLI `python -m src.pipeline [--sample]`.

`run_pull` order: `races`, `candidates`, `committees`, `candidate_totals`, `outside_spending`, `pac_industries`. It uses the endpoint params from the Task 4 table, with `per_page=100`. Ratings are passed in as `races` so `run_pull` stays testable without the network. `orphan_counts` returns how many `candidate_totals` and `outside_spending` rows have a `candidate_id` not in `candidates`, and how many `candidates` have a `race_id` not in `races` (delegates land here by design). The CLI uses today's date as `pulled_at`, `DB_PATH`, and `max_pages=1` with `--sample`, and prints both dicts.

- [ ] **Step 1: Write the failing tests** with a `FakeClient` whose `iter_results(path, params, max_pages)` yields the saved fixture `results` for that path:
  - `test_run_pull_fills_every_table`: every count is greater than 0 except `pac_industries`.
  - `test_rerun_same_day_does_not_duplicate`: two runs with `pulled_at="2026-10-20"` give the same `COUNT(*)` in `candidate_totals`.
  - `test_new_day_appends_snapshot`: a second run with `"2026-10-23"` doubles the `candidate_totals` count, while `candidates` stays the same.
  - `test_orphan_counts_reports_missing_race`: a candidate with `race_id="DC-00"` and no DC row in `races` gives `orphan_counts(conn)["candidates_without_race"] == 1`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/pipeline.py`**

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "Add pipeline that builds the database from FEC and Cook ratings"
```

---

### Task 8: Sample pull, docs, and full pre-election pull

**Files:**
- Modify: `README.md`, `tasks/todo.md`

- [ ] **Step 1: Run a sample pull against the real API**

Run: `python -m src.pipeline --sample`
Expected: nonzero counts for every FEC table and a printed orphan report, with no errors.

- [ ] **Step 2: Sanity-check the data** with `sqlite3 data/processed/midterm_money.db`:
  - `SELECT COUNT(*) FROM races;` should be about 435 voting districts.
  - `SELECT * FROM races WHERE race_id LIKE '%-00';` should list the at-large states.
  - `SELECT incumbent_challenge, COUNT(*) FROM candidates GROUP BY 1;` should contain only `I`, `C`, `O`.

Write down anything surprising for the phase 2 plan.

- [ ] **Step 3: Update `README.md`** with How to Run (venv, `.env`, `python -m src.pipeline`), the data sources, and the caveats from the spec. Check off the completed items in `tasks/todo.md`.

- [ ] **Step 4: Commit**

```bash
git add README.md tasks/todo.md
git commit -m "Document how to build the database and known data caveats"
```

- [ ] **Step 5: Full pre-election pull on or after Oct 23, 2026** (after pre-general reports are filed on Oct 22)

Run: `python -m src.pipeline`
Expected: completes, `races` has about 435 rows (delegates have no Cook rating, so they show up in the orphan report instead), and `candidate_totals` has one row per candidate for that day. Record the `pulled_at` date in the README.
