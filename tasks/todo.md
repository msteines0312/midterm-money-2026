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

## Step 2: Industry super PACs (Power BI page 1)
- [ ] Define the list of industry super PACs to track (e.g. crypto, AI) with sources
- [ ] Aggregate spending by PAC, party supported or opposed, and race
- [ ] Build Power BI page 1

## Step 3: Endorsements (Power BI page 2)
- [ ] Decide which endorsers to track and document the sourcing method
- [ ] Build the endorsement dataset (endorser, candidate, race, date, primary result)
- [ ] Calculate win rates, split by incumbents, open seats, and contested primaries
- [ ] Write up the selection-bias caveat (endorsers often pick favorites)
- [ ] Build Power BI page 2

## Step 4: Money and winning, pre-election (Power BI page 3)
- [ ] Compute fundraising share per race
- [ ] Logistic regression on primary outcomes: money share, incumbency, PVI
- [ ] Compare fundraising advantage against Cook ratings for the general
- [ ] Build Power BI page 3

## Step 4b: Full pre-election pull
- [x] Run `python -m src.pipeline` on or after Oct 23, 2026 (pre-general reports are due Oct 22) and record the pull date in the README

## Step 5: Post-election update (after Nov 3)
- [ ] Load general election results
- [ ] Rerun the money and winning model on general outcomes
- [ ] Add a before-and-after comparison to the README
- [ ] Screenshots and GIF walkthrough of the dashboard in the README
- [ ] Fill in How to Run, Key Features, and What I Learned
- [ ] Make the repo public
