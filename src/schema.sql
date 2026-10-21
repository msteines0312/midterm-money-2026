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
    cook_rating TEXT,
    cook_pvi    TEXT
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

-- One row per candidate per pull, so earlier snapshots are kept
CREATE TABLE IF NOT EXISTS candidate_totals (
    candidate_id             TEXT NOT NULL,
    pulled_at                TEXT NOT NULL,   -- ISO date of the pull
    receipts                 REAL,
    disbursements            REAL,
    cash_on_hand             REAL,
    individual_contributions REAL,
    pac_contributions        REAL,
    PRIMARY KEY (candidate_id, pulled_at)
);

-- Independent expenditures, already summed by the FEC per committee,
-- candidate, and support/oppose
CREATE TABLE IF NOT EXISTS outside_spending (
    committee_id   TEXT NOT NULL,
    candidate_id   TEXT NOT NULL,
    support_oppose TEXT NOT NULL,             -- S = support, O = oppose
    pulled_at      TEXT NOT NULL,
    total          REAL,
    count          INTEGER,
    PRIMARY KEY (committee_id, candidate_id, support_oppose, pulled_at)
);

-- Hand-built labels. Every row cites a source because each one is a judgment call.
CREATE TABLE IF NOT EXISTS pac_industries (
    committee_id TEXT PRIMARY KEY,
    industry     TEXT NOT NULL,
    source_url   TEXT NOT NULL
);
