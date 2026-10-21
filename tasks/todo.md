# Midterm Money 2026: Task List

Pre-election build first (target: before Nov 3, 2026). General election update after results are called.

## Setup
- [x] Create project folder, README skeleton, .gitignore, .env.example
- [ ] Get an OpenFEC API key from api.data.gov and add it to `.env`
- [ ] Create a virtual environment and `requirements.txt`
- [ ] `git init` and create the GitHub repo (private until results are in)

## Step 1: Data foundation
- [ ] Design SQLite schema: candidates, committees, receipts, independent expenditures
- [ ] Write OpenFEC client with pagination and rate-limit handling
- [ ] Pull 2026 House candidates and their committee financial totals
- [ ] Pull 2026 independent expenditures (Schedule E)
- [ ] Handle committee-to-committee transfers so money is not double counted
- [ ] Load Cook ratings / PVI (reuse cleaning code from midterm-polling-messaging)
- [ ] Document data sources and known caveats in the README

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

## Step 5: Post-election update (after Nov 3)
- [ ] Load general election results
- [ ] Rerun the money and winning model on general outcomes
- [ ] Add a before-and-after comparison to the README
- [ ] Screenshots and GIF walkthrough of the dashboard in the README
- [ ] Fill in How to Run, Key Features, and What I Learned
- [ ] Make the repo public
