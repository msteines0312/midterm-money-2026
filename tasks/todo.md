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

## Step 3: Endorsements (write-up section 2)
- [ ] Decide which endorsers to track and document the sourcing method
- [ ] Build the endorsement dataset (endorser, candidate, race, date, primary result)
- [ ] Calculate win rates, split by incumbents, open seats, and contested primaries
- [ ] Write up the selection-bias caveat (endorsers often pick favorites)
- [ ] Write section 2

## Step 4: Money and winning, pre-election (write-up section 3)
- [ ] Compute fundraising share per race
- [ ] Logistic regression on primary outcomes: money share, incumbency, PVI
- [ ] Compare fundraising advantage against Cook ratings for the general
- [ ] Write section 3 and commit the pre-election predictions before Nov 3

## Step 4b: Full pre-election pull
- [x] Run `python -m src.pipeline` on or after Oct 23, 2026 (pre-general reports are due Oct 22) and record the pull date in the README

## Step 5: Post-election update (after Nov 3)
- [ ] Load general election results
- [ ] Rerun the money and winning model on general outcomes
- [ ] Add a before-and-after comparison to the README
- [ ] Link the write-up from the README
- [ ] Fill in How to Run, Key Features, and What I Learned
- [ ] Make the repo public

## Post-MVP (new branch)
- [ ] Full Senate coverage in sections 2 and 3
- [ ] Power BI dashboard
