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
    industry     TEXT NOT NULL,
    source_url   TEXT NOT NULL
);
