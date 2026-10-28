# Midterm Money 2026: Task List

Pre-election build first (target: before Nov 3, 2026). General election update after results are called.

## Setup
- [x] Create project folder, README skeleton, .gitignore, .env.example
- [x] Get an OpenFEC API key from api.data.gov and add it to `.env`
- [x] Create a virtual environment and `requirements.txt`
- [x] `git init` and create the GitHub repo (private until results are in)

## Step 1: Data foundation
- [x] Design SQLite schema: candidates, committees, receipts, independent expenditures
- [x] Write OpenFEC client with pagination and rate-limit handling
- [x] Pull 2026 House candidates and their committee financial totals
- [x] Pull 2026 independent expenditures (Schedule E, aggregated by committee and candidate)
- [x] Avoid double counting by using FEC-aggregated totals instead of raw filings
- [x] Load Cook ratings and PVI for all 435 districts (method from midterm-polling-messaging)
- [x] Document data sources and known caveats in the README

## Step 2: Tech money (write-up section 1)
Design: `docs/superpowers/specs/2026-10-23-tech-money-page-design.md`
- [x] Decide what to track: crypto and AI super PAC networks, plus tech billionaire donors on both sides
- [x] Confirm whether outside spending is missing recent 24/48-hour reports, and fix it if so
- [x] Label network committees in `pac_industries.csv` with sources
- [x] Aggregate House spending by network, party supported or opposed, election, and race
- [x] Write section 1, House version (before Nov 3)
- [ ] After Nov 3: add Senate spending for the same networks
- [ ] After Nov 3: settle the billionaire rule and add the donor layer

## Step 2b: Billionaire money (write-up section 2, before Nov 3)
Design: `docs/superpowers/specs/2026-10-26-billionaire-money-design.md`. Plan: `docs/superpowers/plans/2026-10-26-billionaire-money.md`
- [x] Task 1: Load Schedule A contributions and PAC committee totals
- [x] Task 2: Research billionaires and entities (sourced CSVs, loaders, tests)
- [x] Task 3: Giving, concentration, and the billionaire-backed PAC list (27 PACs backed, 6 near, 2 unreconciled, 1 could not be tested)
- [x] Task 4: House share and lean
- [x] Task 5: Primary outcomes for billionaire-backed PACs (7 candidates, no review items)
- [x] Task 6: Charts, numbers JSON, write-up (`reports/billionaire-money.md`), and its number-matching test
- [x] Added raw e-filing loader after finding that Schedule A lacked reports filed Oct 15 and 22
- [ ] Optional: finish loading 314 Action Fund's small gifts so Bloomberg's share there can be tested
- [ ] After Nov 3: add Senate spending and general election outcomes for billionaire-backed PACs

## Step 3: Endorsements (write-up section 2)
- [x] Decide which endorsers to track and document the sourcing method
- [x] Build the endorsement dataset (endorser, candidate, race, date, primary result)
- [x] Add Club for Growth PAC and Justice Democrats (archived copies, built with `scripts/build_endorsements.py --cached-only`)
- [x] Calculate win rates, split by incumbents, open seats, and contested primaries
- [x] Write up the selection-bias caveat (endorsers often pick favorites)
- [x] Write section 2
- [ ] After Nov 3: score Louisiana's 4 pending endorsements

## Step 4: Money and winning, pre-election (write-up section 3)
- [x] Compute fundraising share per race
- [x] Logistic regression on 2022 and 2024 general outcomes (money share, incumbency, PVI), evaluated by held-out cycle
- [x] Commit model-based general election predictions (tag pre-election-model)
- [x] Paired bootstrap check of what money adds to the model (supplementary-2026-10-26.json)
- [x] Compare fundraising advantage against Cook ratings for the general
- [x] Commit simple general election predictions (tag pre-election-simple)
- [x] Write section 3 and commit the pre-election predictions before Nov 3 (pre-election version: `reports/money-and-winning.md`. Scoring is added after Nov 3)

## Step 4b: Full pre-election pull
- [x] Run `python -m src.pipeline` on or after Oct 23, 2026 (pre-general reports are due Oct 22) and record the pull date in the README

## Step 5: Post-election update (after Nov 3)
- [ ] Load general election results
- [ ] Score both tagged prediction sets against 2026 general results
- [ ] Test whether adding outside spending (support and oppose, by candidate) improves the model on 2022 and 2024. Planned in the spec but not done before the pre-election-model tag
- [ ] Add a before-and-after comparison to the README
- [ ] Link the write-up from the README
- [ ] Fill in How to Run, Key Features, and What I Learned
- [ ] Make the repo public

## Post-MVP (new branch)
- [ ] Full Senate coverage in sections 2 and 3
- [ ] Power BI dashboard
