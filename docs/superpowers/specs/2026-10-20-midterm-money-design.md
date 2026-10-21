# Midterm Money 2026: Design Spec

## Purpose
A portfolio project analyzing campaign finance and endorsements in the 2026 U.S. House midterms, built pre-election and updated after results are called. Audience: recruiters and hiring managers for data analyst, analytics, and ML roles. Framing is neutral and descriptive.

## Research questions
1. **Industry super PACs.** Which industries spend through super PACs in 2026, how much, for or against whom, and in which races.
2. **Endorsements.** Win rate of endorsed candidates in 2026 primaries, split by incumbents, open seats, and contested primaries, with an explicit selection-bias discussion.
3. **Money and winning.** Whether fundraising share predicts winning after controlling for incumbency and district partisanship (Cook PVI). Pre-election version uses primary outcomes and Cook ratings. General results are added after Nov 3, 2026.

## Phases
| Phase | Delivers | Plan |
|---|---|---|
| 1. Data foundation | SQLite database built from OpenFEC plus hand-built CSVs, refreshable by one command | `plans/2026-10-20-data-foundation.md` |
| 2. Industry super PACs | Analysis + Power BI page 1 | Written after phase 1 data is inspected |
| 3. Endorsements | Endorsement and primary result dataset, analysis, Power BI page 2 | Written after phase 1 |
| 4. Money and winning | Logistic regression, Power BI page 3 | Written after phase 1 |
| 5. Post-election update | General results, model rerun, before and after write-up | After Nov 3 |

Phases 2 to 4 get their own plans because their details depend on what the real data looks like.

## Data sources
- **OpenFEC API** (api.open.fec.gov/v1), key in `.env` as `FEC_API_KEY`.
  - `/candidates/`: 2026 House candidates, filtered to `has_raised_funds=true`.
  - `/committees/`: committee metadata, including super PACs (committee type `O`).
  - `/schedules/schedule_e/by_candidate/`: independent expenditures already aggregated by committee, candidate, and support/oppose. Used instead of raw Schedule E to avoid deduplicating amended filings.
- **Cook ratings and PVI:** two pinned Wikipedia revisions, same method as `midterm-polling-messaging`. The ratings page gives Cook ratings for the ~137 seats any forecaster calls competitive. The main elections page gives Cook PVI for all 435 districts. Unlisted seats are Solid D or Solid R by PVI sign, marked `rating_source = "inferred"`. Missouri uses its pre-2025 map (new map struck down Sept 2026), so its PVI is the 2025 value.
- **Hand-built CSVs** in `data/manual/` (committed, with a source URL per row): `pac_industries.csv`, later `endorsements.csv` and `primary_results.csv`.

- **FEC bulk summary file** (`webl26.zip`, refreshed daily): per-campaign totals including candidate self-funding and all individual donations. Replaced `/candidates/totals/`, which reports neither.

## Fundraising measure
- `external_contributions` = individual contributions - refunds to individuals + PAC contributions + party contributions - refunds to committees.
- `candidate_self_funding` = candidate contributions + candidate loans. Kept separate so self-funders are not counted as strong fundraisers.
- Active candidate: latest report covers through 2026-09-30 or later. The exact general-election population comes from phase 3 primary results.

## Schema
| Table | Grain | Key columns |
|---|---|---|
| `races` | district | race_id (`ST-DD`, at-large is `00`), state, district, cook_rating, cook_pvi, rating_source |
| `candidates` | candidate | candidate_id, name, party, race_id, incumbent_challenge (`I`/`C`/`O`), primary_result (nullable until phase 3) |
| `committees` | committee | committee_id, name, committee_type, designation |
| `candidate_totals` | candidate + pulled_at | coverage_end_date, receipts, disbursements, cash_on_hand, debts_owed, individual_contributions, pac_contributions, party_contributions, candidate_self_funding, external_contributions |
| `outside_spending` | committee + candidate + support_oppose + pulled_at | total, count |
| `pac_industries` | committee | industry, source_url |
| `endorsements` | endorser + candidate | endorsement date, source_url (phase 3) |

Money snapshots are keyed by `pulled_at` so each pull appends a new snapshot and the pre-election numbers stay reproducible.

## Constraints
- Python 3.13, pandas, requests, python-dotenv, pytest. SQLite through the standard library `sqlite3`.
- Respect the API rate limit by reading `X-RateLimit-Remaining` and backing off on HTTP 429. Do not hardcode a limit.
- Main pre-election pull runs after Oct 22, 2026, when pre-general reports (through Oct 14) are filed.
- No em dashes anywhere. NumPy-style docstrings. Plain-voice commit messages with no prefixes and no co-author lines.

## Known caveats to document
- Several states (including Texas and California) redrew House maps for 2026, so district comparisons with 2024 are not like for like. PVI must come from the 2026 ratings page, not older sources.
- Non-voting delegates (DC and territories) file with the FEC but have no Cook rating. They are kept in `candidates` and excluded from analyses.
- FEC totals change as filings arrive. Every chart states its `pulled_at` date.
