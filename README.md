# Midterm Money 2026
An analysis of campaign finance and endorsements in the 2026 U.S. House midterms. It asks three questions: where industry super PAC money is going, whether endorsements predict primary wins, and whether a fundraising advantage predicts winning once incumbency and district partisanship are accounted for.

> **Status:** In progress. The data pipeline is built, and the House version of section 1 is written: [Tech money in the 2026 House races](reports/tech-money.md). The billionaire money section is written too: [Billionaire money in the 2026 House races](reports/billionaire-money.md). The pre-election version of section 3 is also written: [Money and winning in the 2026 House races](reports/money-and-winning.md). Its scoring against results will be added after November 3, 2026, and the endorsements section is next. Two sets of pre-election House predictions are committed and tagged in [reports/predictions](reports/predictions/README.md): simple predictions (money leader next to Cook rating, tag `pre-election-simple`) and a logistic regression model trained on the 2022 and 2024 generals (tag `pre-election-model`).

## Questions

1. **Industry super PACs.** Which industries are spending through super PACs in 2026, how much, and in which races?
2. **Endorsements.** How often did endorsed candidates win their 2026 primaries, and how much of that is the endorsement versus endorsers picking favorites?
3. **Money and winning.** Does a fundraising advantage predict winning after controlling for incumbency and district partisanship (Cook PVI)?

## Tech Stack
- Python (requests, pandas, BeautifulSoup, pytest)
- SQLite
- matplotlib for the write-up charts
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
3. Check that everything works with a small pull (one page per endpoint). This writes to a separate `midterm_money_sample.db` so test runs never mix with real snapshots:
   ```bash
   python -m src.pipeline --sample
   ```
4. Build the full database at `data/processed/midterm_money.db`:
   ```bash
   python -m src.pipeline
   ```
   Running it again on a later date adds a new snapshot of the money data without overwriting the old one.
5. Build the 2022 and 2024 training data for the money model. The first command pulls each campaign's pre-general money from the API (it takes a while). The second loads results, PVI, and ratings, and prints how many Democrat-versus-Republican candidates matched to money:
   ```bash
   python scripts/load_history_money.py
   python -m src.pipeline --history
   python scripts/load_history_money.py --supplement
   python -m src.pipeline --history
   ```
   `--supplement` adds money for candidates the FEC's bulk linkage file leaves out (see the caveats below). It needs the `history_results` rows from the first `--history` run, so the order matters. A plain `load_history_money.py` run replaces a whole cycle, so run `--supplement` again after one. The second `--history` run reprints the match counts with that money included.
6. Build the 2026 predictions. The simple file needs the 2026-10-24 money snapshot from step 4. The model file trains on the history tables from step 5. The last script adds the paired bootstrap check of what money adds to the model (2022 and 2024 only):
   ```bash
   python scripts/build_simple_predictions.py
   python scripts/build_model_predictions.py
   python scripts/money_contribution_check.py
   ```
   The first two overwrite the tagged files in `reports/predictions/`, so run them only to check that a rebuild matches (`git diff` should show nothing), and never commit a changed copy.
7. Run the tests:
   ```bash
   python -m pytest
   ```

## Data Sources

| Table | Source | Notes |
|---|---|---|
| `candidates` | OpenFEC `/candidates/` | 2026 House candidates who have raised money |
| `candidate_totals` | FEC bulk summary file (`webl26.zip`) | Cycle totals per campaign, with self-funding split out. One snapshot per pull date |
| `committees` | OpenFEC `/committees/` | Super PACs (type O) and hybrid PACs (types V and W) |
| `outside_spending` | FEC bulk independent expenditure file (`independent_expenditure_2026.csv`) | House independent expenditures summed by committee, candidate, support or oppose, and primary or general. Superseded filings are dropped |
| `races` | Wikipedia, pinned revisions | Cook ratings and Cook PVI for all 435 districts |
| `pac_industries` | Hand-built, `data/manual/` | Industry label for each tracked super PAC, with a source for every row |
| `history_money` | OpenFEC `/reports/house-senate/` | 2022 and 2024 House money as of each campaign's pre-general report |
| `history_results` | 2022: FEC [Federal Elections 2022](https://www.fec.gov/documents/5676/federalelections2022.xlsx). 2024: Wikipedia, pinned post-certification revision | One row per November general candidate, with the winner, vote share, and incumbency |
| `history_races` | Wikipedia, each cycle's pages pinned to the last revision before election day | Cook PVI and Cook rating for every district in 2022 and 2024 |

### Snapshots
| Pull date | Purpose | Notes |
|---|---|---|
| 2026-10-23 | Pre-election | Pulled the day after pre-general reports were due. 744 campaigns report through October 14 |
| 2026-10-23 | Pre-election, outside spending | Official outside spending snapshot, built from the FEC bulk independent expenditure file (`outside_spending`). An earlier build the same day used the by-candidate endpoint and is kept in `outside_spending_by_candidate_endpoint` because it dropped filings with no candidate ID |
| 2026-10-24 | Pre-election predictions | Pulled after the 10-23 bulk file lagged pre-general reports. Both tagged prediction sets use this snapshot's money |

### Reproducing the tagged predictions
The tagged prediction files (`pre-election-simple` at commit `c18c0db`, `pre-election-model` at `eb42038`) depend on the local 2026-10-24 snapshot and on pinned Wikipedia revisions. The FEC files and API keep changing as campaigns file and amend reports, so a fresh pull on a later date gives different money and will not reproduce the tagged files. The build scripts read the snapshot by its pull date, so rebuilding from the same local database gives byte-identical files.

## Data Caveats
- FEC numbers keep changing as campaigns file new reports. Every snapshot is stamped with its pull date, and every chart says which date it uses.
- Fundraising is measured as `external_contributions`: money from individuals (all donation sizes), PACs, and party committees, minus refunds. A candidate's own contributions and loans are tracked separately in `candidate_self_funding`, so someone who writes their campaign a $3M check doesn't look like a $3M fundraiser. In the October 23 snapshot, 329 active House candidates got more than half their money from themselves.
- The FEC file lists every 2026 House campaign that raised money, including ones that dropped out, closed, or lost a primary. A campaign counts as active if its latest report covers through September 30, 2026 (the October quarterly). In the October 23 snapshot, that cuts 2,557 campaigns to 1,674. The exact set of candidates on the November ballot comes from primary results in the endorsements phase.
- Negative cash on hand is real, not an error. It's how the FEC records a campaign that spent more than it raised and owes debts.
- Cook ratings for safe seats are inferred. The Wikipedia ratings page only lists seats that at least one forecaster considers competitive (137 of them). The other 298 get Solid D or Solid R from the sign of their PVI, and `races.rating_source` says which is which.
- Texas, California, and several other states redrew their maps for 2026, so PVI comes from the 2026 tables rather than older lists. Missouri's new map was struck down in September 2026, so its districts keep their 2025 PVI.
- The schema has no foreign keys. FEC endpoints filter candidates differently, so some rows don't match across tables. The pipeline prints how many rows are unmatched on every run instead of dropping them.
- Non-voting delegates (DC and the territories) file with the FEC but have no Cook rating. They stay in `candidates` and are left out of the analysis. Four other candidates also have no matching race because their FEC filings list a district that doesn't exist (GA-00, GA-23, NM-66, and one Maryland filing with no district).
- A few FEC reports have coverage end dates after the pull date (November 3 and December 31, 2026). These look like filing errors, so don't trust `coverage_end_date` as a precise filing date for those rows.
- Outside spending comes from the FEC bulk independent expenditure file, which is built from 24- and 48-hour reports. It can include filings that have not yet appeared in a committee's periodic report, and a committee can amend a filing to $0 that its periodic report still counts.
- About 41 `outside_spending` rows (one per committee, candidate, and side) have no candidate ID, either because the filing left it blank or because the name could not be matched. Blank-ID rows are matched to a candidate by race and last name. If two candidates in a race share a last name, the match is skipped and the money is kept under a `race|LASTNAME` key. Rows with a blank district use the candidate's race when the ID is known and otherwise get no race.
- Some filings use a candidate ID that isn't in `candidates`, for example because a candidate who switched districts got a new FEC ID (Colin Allred files as H6TX33082, but `candidates` lists him as H8TX32098). These get the same race and last name match as blank IDs and take the matched candidate's ID and party. When no single candidate matches, the filed ID is kept. In the October 23 snapshot this cut the rows with an ID missing from `candidates` from 140 to 77. The snapshot's `outside_spending` rows were rebuilt on October 24 from the saved October 23 bulk file (`python -m src.pipeline --rebuild-outside-spending 2026-10-23`), which changes no other table.
- Rows with a blank amount, a blank support or oppose flag (4 real House rows), or a blank state are skipped. Party names are mapped to DEM, REP, and DFL.
- Outside spending is stored by election type, so primary and general election money are separate rows. Totals that mix them include both.
- The bulk file contains one individual filer whose filing lists the name "Warren Buffet" (C00946087), with about $13 billion of independent expenditures for a candidate named Bettis. It is not a registered super PAC and is not in `committees`, so analysis totals only count committees in the `committees` table (super PACs and hybrid PACs).
- Validation against FEC committee totals (`scripts/check_outside_spending.py`, October 23 snapshot). Our figure is the bulk file for all offices through each committee's last reported coverage date, dated by expenditure date, compared with `/committee/{id}/totals/`. The pass rule was every labeled network committee within 5% and the top 10 super PACs within 5% in total. The top 10 total matched (1.20%) and every network committee matched except Jobs and Democracy PAC (-10.69%), so the check **failed** and the verdict is fallback (a): the report shows network spending only. The share of all outside spending is left out of the report until a re-check passes.

| Committee | Network | Bulk file through coverage | FEC reported | Coverage end | Difference |
|---|---|---|---|---|---|
| FAIRSHAKE | Fairshake | $19,274,814 | $19,412,478 | 2026-10-14 | -0.71% |
| DEFEND AMERICAN JOBS | Fairshake | $88,281,415 | $88,319,034 | 2026-10-14 | -0.04% |
| PROTECT PROGRESS | Fairshake | $29,181,489 | $29,197,272 | 2026-10-14 | -0.05% |
| LEADING THE FUTURE | Leading the Future | $0 | $0 | 2026-10-14 | n/a |
| AMERICAN MISSION | Leading the Future | $13,443,607 | $13,421,107 | 2026-09-30 | 0.17% |
| THINK BIG | Leading the Future | $18,169,566 | $18,169,566 | 2026-09-30 | 0.00% |
| JOBS AND DEMOCRACY PAC | Public First | $15,964,202 | $17,875,336 | 2026-09-30 | -10.69% |
| DEFENDING OUR VALUES PAC | Public First | $7,365,832 | $7,365,832 | 2026-09-30 | 0.00% |
| PUBLIC FIRST | Public First | $0 | $0 | 2026-09-30 | n/a |
| CLF | none | $67,894,510 | $67,898,719 | 2026-09-30 | -0.01% |
| HMP | none | $46,771,985 | $45,720,411 | 2026-09-30 | 2.30% |
| NO GOING BACK PAC INC. | none | $187,901,795 | $187,807,636 | 2026-10-14 | 0.05% |
| SAFETY & AFFORDABILITY PAC INC. | none | $16,216,833 | $16,216,833 | 2026-10-14 | 0.00% |
| LCV VICTORY FUND | none | $32,393,314 | $26,076,915 | 2026-10-14 | 24.22% |
| UNITED DEMOCRACY PROJECT | none | $53,684,196 | $53,603,927 | 2026-10-14 | 0.15% |
| YOUR COMMUNITY PAC | none | $13,053,517 | $12,961,740 | 2026-09-30 | 0.71% |

  Two committees with $0 on both sides (Leading the Future, Public First) agree trivially and do not count toward pass or fail. Jobs and Democracy PAC's gap is $1,911,134 ($17,875,336 reported versus $15,964,202 from our deduplicated figure). About $1.5M of it appears to come from 24- and 48-hour filings amended to $0 after its periodic report. The rest is unexplained. HMP (2.30%) and LCV Victory Fund (24.22%) are not labeled networks and do not affect the verdict.

### Training data caveats (2022 and 2024)
- The FEC has not published its 2024 results volume, and the MIT Election Lab file needs a personal sign-in form to download. So 2024 results come from the certified tables on the [2024 House elections page](https://en.wikipedia.org/w/index.php?title=2024_United_States_House_of_Representatives_elections&oldid=1267103610) (first revision on or after January 3, 2025). Those tables give vote shares, not counts, so `votes` is empty for 2024. Indiana and Kansas list no shares at all. Winners come from the page's check marks, which matter in CA-13, where both candidates round to 50.0%.
- Candidates are matched to FEC IDs by race and last name against that cycle's FEC summary file. If that fails, a second pass looks for both the first and last name anywhere in the FEC name, which catches swapped names ("NICK, LALOTA") and married or hyphenated ones ("ARENHOLZ, ASHLEY HINSON"). Hand-checked overrides, each with a note, are in `data/manual/history_matches.csv`. About 50 IDs in the 2022 FEC sheet are older registrations that never meet the candidate's money, so those are matched by name too. Some candidates have two FEC IDs that share one committee. These are folded into one, so their money is never counted twice.
- Louisiana held November jungle elections in both years. A Louisiana race counts as Democrat versus Republican only if exactly one of each was on the ballot. That is LA-01 and LA-02 in 2022 and none in 2024. Neither year had a House runoff in Georgia or Louisiana.
- Ranked-choice races (Alaska, Maine) use first-round votes and the final winner.
- The FEC's bulk files for past cycles (webl22, webl24, ccl22, ccl24) leave out some candidates whose FEC record has since rolled forward to 2026. Glenn Ivey (MD-04) lists 2012, 2016, and 2026, for example. Those candidates were found with the OpenFEC candidate search and recorded as hand-checked overrides, and `--supplement` pulls their pre-general money through the API with the same report rules. After that, every 2022 and 2024 winner has pre-general money. About 5% (2022) and 6% (2024) of Democrat-versus-Republican candidates still have none, nearly all small campaigns with no qualifying report.
- New York's 2024 map was redrawn in February 2024, after Cook's last PVI release. The 2024 page's state tables show PVIs recalculated for the new map (NY-19 R+1, NY-22 D+3), while Cook's published list still shows the 2022-map values (NY-19 EVEN). The new-map values are used because that map was on the ballot.

## Key Features
- Rate-limit-aware API client that backs off on HTTP 429 and pauses when the remaining-requests header hits zero
- Snapshot design so pre-election and post-election data can be compared side by side
- Tests built on real saved API responses and real FEC file rows, which caught that cash on hand arrives from the API as text
- Fundraising measure that separates money raised from others from candidates funding themselves
- Ratings parser that combines two pinned Wikipedia pages and fails loudly if the pages disagree

## What I Learned
_Coming soon._

## Related Work
- [midterm-polling-messaging](https://github.com/msteines0312/midterm-polling-messaging): 2018 and 2022 midterm polling error and campaign ad messaging analysis.
