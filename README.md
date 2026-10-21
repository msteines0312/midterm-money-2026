# Midterm Money 2026
An analysis of campaign finance and endorsements in the 2026 U.S. House midterms. It asks three questions: where industry super PAC money is going, whether endorsements predict primary wins, and whether a fundraising advantage predicts winning once incumbency and district partisanship are accounted for.

> **Status:** In progress. The data pipeline is built. The pre-election analysis is next, and general election results will be added after November 3, 2026.

## Questions

1. **Industry super PACs.** Which industries are spending through super PACs in 2026, how much, and in which races?
2. **Endorsements.** How often did endorsed candidates win their 2026 primaries, and how much of that is the endorsement versus endorsers picking favorites?
3. **Money and winning.** Does a fundraising advantage predict winning after controlling for incumbency and district partisanship (Cook PVI)?

## Tech Stack
- Python (requests, pandas, BeautifulSoup, pytest)
- SQLite
- Power BI
- Data: FEC OpenFEC API, Cook Political Report ratings and PVI (via Wikipedia), hand-collected labels

## How to Run
1. Clone the repo and create a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   source .venv/bin/activate     # macOS / Linux
   pip install -r requirements.txt
   ```
2. Get a free API key at https://api.data.gov/signup/, copy `.env.example` to `.env`, and paste the key in.
3. Check that everything works with a small pull (one page per endpoint):
   ```bash
   python -m src.pipeline --sample
   ```
4. Build the full database at `data/processed/midterm_money.db`:
   ```bash
   python -m src.pipeline
   ```
   Running it again on a later date adds a new snapshot of the money data without overwriting the old one.
5. Run the tests:
   ```bash
   python -m pytest
   ```

## Data Sources

| Table | Source | Notes |
|---|---|---|
| `candidates` | OpenFEC `/candidates/` | 2026 House candidates who have raised money |
| `candidate_totals` | OpenFEC `/candidates/totals/` | FEC-computed cycle totals, one snapshot per pull date |
| `committees` | OpenFEC `/committees/` | Super PACs (type O) and hybrid PACs (types V and W) |
| `outside_spending` | OpenFEC `/schedules/schedule_e/by_candidate/` | Independent expenditures summed by committee, candidate, and support or oppose |
| `races` | Wikipedia, pinned revisions | Cook ratings and Cook PVI for all 435 districts |
| `pac_industries` | Hand-built, `data/manual/` | Industry label for each tracked super PAC, with a source for every row |

## Data Caveats
- FEC numbers keep changing as campaigns file new reports. Every snapshot is stamped with its pull date, and every chart says which date it uses.
- Individual contributions only count donors who gave more than $200. The totals endpoint doesn't report small-dollar money separately.
- Cook ratings for safe seats are inferred. The Wikipedia ratings page only lists seats that at least one forecaster considers competitive (137 of them). The other 298 get Solid D or Solid R from the sign of their PVI, and `races.rating_source` says which is which.
- Texas, California, and several other states redrew their maps for 2026, so PVI comes from the 2026 tables rather than older lists. Missouri's new map was struck down in September 2026, so its districts keep their 2025 PVI.
- The schema has no foreign keys. FEC endpoints filter candidates differently, so some rows don't match across tables. The pipeline prints how many rows are unmatched on every run instead of dropping them.
- Non-voting delegates (DC and the territories) file with the FEC but have no Cook rating. They stay in `candidates` and are left out of the analysis.

## Key Features
- Rate-limit-aware API client that backs off on HTTP 429 and pauses when the remaining-requests header hits zero
- Snapshot design so pre-election and post-election data can be compared side by side
- Tests built on real saved API responses, which caught that cash on hand arrives from the API as text
- Ratings parser that combines two pinned Wikipedia pages and fails loudly if the pages disagree

## What I Learned
_Coming soon._

## Related Work
- [midterm-polling-messaging](https://github.com/msteines0312/midterm-polling-messaging): 2018 and 2022 midterm polling error and campaign ad messaging analysis.
