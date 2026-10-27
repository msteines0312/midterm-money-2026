# Lessons

## 2026-10-21: Check that a number fits the population and the question, not just the source

**What happened:** The sample pull showed 61 of 100 candidates with under $1 cash on hand. The final code review flagged it, and Matt called it out as not looking right. The values matched the FEC exactly across three endpoints, so the extraction was correct. The methodology was wrong in two ways:

1. **Wrong population.** `/candidates/totals/` returns every 2026 House filer, including paper candidates who never filed a report, campaigns that terminated, and primary losers. Most of the "$0 cash" rows were real zeros for campaigns that no longer exist.
2. **Wrong measure.** `receipts` counts a candidate's own money as fundraising. One Kentucky candidate's $4.99M in receipts was $3.33M of their own money and $1.66M from donors.

**Fix:** Switched totals to the FEC bulk summary file, which splits out self-funding and includes small-dollar donations. Added `external_contributions` (money from others, net of refunds) and `candidate_self_funding`, plus `coverage_end_date` so active campaigns can be identified.

**Pattern to keep:** When a summary statistic looks odd, first prove the extraction is right by comparing sources. Then ask who is in the population and whether the field measures what the question actually asks. "Matches the source" is not the same as "right for the analysis."

## 2026-10-23: Compare an aggregate against an independent total before trusting it

**What happened:** The first outside spending snapshot used the FEC by-candidate endpoint. It silently dropped filings that had no candidate ID, such as large Congressional Leadership Fund expenditures, so committee sums came out low with no error. Nothing in the code or the row counts hinted at it.

**Fix:** Rebuilt `outside_spending` from the FEC bulk independent expenditure file, which keeps every filing, and added `scripts/check_outside_spending.py`. It compares our per-committee sums with each committee's own reported total from `/committee/{id}/totals/`. That check also showed the date field matters (dissemination date versus expenditure date) and that a few committees amend filings to $0.

**Pattern to keep:** Before trusting an aggregate, compare it against an independent total for a few large, known entities. Agreement on those is evidence the method is sound, and a miss points to the cause.
