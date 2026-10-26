-- Schema for the 2026 House money database.
--
-- There are no foreign keys on purpose. Each FEC endpoint filters candidates
-- a little differently (a candidate can have totals but fail the
-- has_raised_funds filter, for example), so some rows won't match across
-- tables. Rejecting them would silently drop real money. Instead the pipeline
-- loads everything and reports how many rows don't match (see orphan_counts).
--
-- Money columns are REAL and nullable. NULL means "not reported yet", which is
-- different from $0.

CREATE TABLE IF NOT EXISTS races (
    race_id     TEXT PRIMARY KEY,   -- "ST-DD", at-large seats are "00"
    state       TEXT NOT NULL,
    district    TEXT NOT NULL,
    cook_rating   TEXT,
    cook_pvi      TEXT,
    rating_source TEXT              -- "cook" if listed, "inferred" if Solid from PVI
);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id        TEXT PRIMARY KEY,
    name                TEXT,
    party               TEXT,
    state               TEXT,
    district            TEXT,
    race_id             TEXT,
    incumbent_challenge TEXT,       -- I = incumbent, C = challenger, O = open seat
    primary_result      TEXT        -- filled in during the endorsements phase
);

CREATE TABLE IF NOT EXISTS committees (
    committee_id   TEXT PRIMARY KEY,
    name           TEXT,
    committee_type TEXT,            -- O = super PAC, V/W = hybrid PAC
    designation    TEXT
);

-- One row per candidate per pull, so earlier snapshots are kept.
-- Source is the FEC bulk summary file, which splits out self-funding.
CREATE TABLE IF NOT EXISTS candidate_totals (
    candidate_id             TEXT NOT NULL,
    pulled_at                TEXT NOT NULL,   -- ISO date of the pull
    coverage_end_date        TEXT,            -- last day covered by the latest report
    receipts                 REAL,            -- everything, including the candidate's own money
    disbursements            REAL,
    cash_on_hand             REAL,            -- negative when a campaign overspent
    debts_owed               REAL,
    individual_contributions REAL,            -- all donors, including under $200
    pac_contributions        REAL,
    party_contributions      REAL,
    candidate_self_funding   REAL,            -- candidate contributions plus candidate loans
    external_contributions   REAL,            -- individuals + PACs + party, minus refunds
    PRIMARY KEY (candidate_id, pulled_at)
);

-- Independent expenditures from the FEC bulk file, summed per committee,
-- candidate, support/oppose, and election type.
-- candidate_key is the FEC candidate ID when the filing has one. Filings with
-- no ID use race_id|LASTNAME, or state|LASTNAME when the district is blank too.
-- The key is never NULL because SQLite treats NULLs in a primary key as
-- distinct, so a rerun would duplicate those rows.
-- election_type codes: P primary, G general, R runoff, S special,
-- C convention, O other.
CREATE TABLE IF NOT EXISTS outside_spending (
    committee_id   TEXT NOT NULL,
    candidate_key  TEXT NOT NULL,
    candidate_id   TEXT,                      -- NULL when the filing has no ID and no match
    candidate_name TEXT,
    party          TEXT,
    race_id        TEXT,                      -- NULL when the filing has no district
    election_type  TEXT NOT NULL,
    support_oppose TEXT NOT NULL,             -- S = support, O = oppose
    pulled_at      TEXT NOT NULL,
    total          REAL,
    count          INTEGER,
    PRIMARY KEY (committee_id, candidate_key, support_oppose, election_type, pulled_at)
);

-- Hand-built labels. Every row cites a source because each one is a judgment call.
CREATE TABLE IF NOT EXISTS pac_industries (
    committee_id TEXT PRIMARY KEY,
    network      TEXT NOT NULL,
    industry     TEXT NOT NULL,
    source_url   TEXT NOT NULL
);

-- 2022 and 2024 House money for training the model, as of each campaign's
-- pre-general report, so it matches the mid-October 2026 snapshot instead of
-- including money raised after election day. Built by src/fec/history.py from
-- the OpenFEC reports API. Separate from candidate_totals so historical loads
-- never touch 2026 rows.
-- Money is the cycle-to-date ("_ytd", Form 3 Column B) figures on the latest
-- election-year report ending on or before that cycle's standard 12G cutoff.
CREATE TABLE IF NOT EXISTS history_money (
    cycle                  INTEGER NOT NULL,
    candidate_id           TEXT NOT NULL,
    committee_id           TEXT,             -- principal committees used, comma-separated when more than one
    external_contributions REAL,             -- individuals + PACs + party, minus refunds
    candidate_self_funding REAL,             -- candidate contributions plus candidate loans
    coverage_end_date      TEXT,             -- end of the latest report used (12G, or an earlier one)
    PRIMARY KEY (cycle, candidate_id)
);

-- 2022 and 2024 House general election results, for training the model.
-- One row per candidate on the November ballot in the 50 states
-- (src/history_results.py). 2022 comes from the FEC's "Federal Elections"
-- results publication. The FEC has not published 2024, so 2024 comes from the
-- certified results on Wikipedia, which give vote shares but not counts.
-- A fusion candidate (NY, CT) gets one row with combined votes across lines.
-- Joined to history_money on (cycle, candidate_id).
CREATE TABLE IF NOT EXISTS history_results (
    cycle               INTEGER NOT NULL,
    race_id             TEXT NOT NULL,
    candidate_id        TEXT,             -- FEC candidate ID from the results sheet
    name                TEXT NOT NULL,    -- 2022 "Last, First" (FEC); 2024 "First Last" (Wikipedia)
    party               TEXT,             -- DEM, REP, or the source's label for anyone else
    votes               INTEGER,          -- November votes (first round for ranked choice); NULL if unopposed, and always NULL for 2024
    vote_share          REAL,             -- percent of the November vote, same first-round rule; NULL if not listed
    won                 INTEGER NOT NULL, -- 1 for the final general winner, after any runoff
    incumbent_challenge TEXT,             -- I/C/O from that cycle's webl file; NULL if the ID isn't in it
    is_incumbent        INTEGER NOT NULL, -- 1 if the results source marks them the incumbent (FEC "(I)" in 2022, Wikipedia's incumbent column in 2024)
    PRIMARY KEY (cycle, race_id, name)
);

-- Cook PVI and Cook rating for every district in 2022 and 2024, from each
-- cycle's own Wikipedia pages pinned to the last revision before election day.
-- Same method as `races`, which holds 2026 and is never touched by history loads.
CREATE TABLE IF NOT EXISTS history_races (
    cycle         INTEGER NOT NULL,
    race_id       TEXT NOT NULL,
    cook_pvi      TEXT,
    cook_rating   TEXT,
    rating_source TEXT,               -- "cook" if listed, "inferred" if Solid from PVI
    PRIMARY KEY (cycle, race_id)
);
