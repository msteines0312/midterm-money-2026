# Lessons

## 2026-10-21: Check that a number fits the population and the question, not just the source

**What happened:** The sample pull showed 61 of 100 candidates with under $1 cash on hand. The final code review flagged it, and Matt called it out as not looking right. The values matched the FEC exactly across three endpoints, so the extraction was correct. The methodology was wrong in two ways:

1. **Wrong population.** `/candidates/totals/` returns every 2026 House filer, including paper candidates who never filed a report, campaigns that terminated, and primary losers. Most of the "$0 cash" rows were real zeros for campaigns that no longer exist.
2. **Wrong measure.** `receipts` counts a candidate's own money as fundraising. One Kentucky candidate's $4.99M in receipts was $3.33M of their own money and $1.66M from donors.

**Fix:** Switched totals to the FEC bulk summary file, which splits out self-funding and includes small-dollar donations. Added `external_contributions` (money from others, net of refunds) and `candidate_self_funding`, plus `coverage_end_date` so active campaigns can be identified.

**Pattern to keep:** When a summary statistic looks odd, first prove the extraction is right by comparing sources. Then ask who is in the population and whether the field measures what the question actually asks. "Matches the source" is not the same as "right for the analysis."
