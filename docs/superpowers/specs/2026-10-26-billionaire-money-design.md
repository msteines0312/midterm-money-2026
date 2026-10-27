# Billionaire Money in 2026 House Races: Design (Write-up Section 2)

Replaces the original "Endorsements" phase in `2026-10-20-midterm-money-design.md`. Matt reframed it on Oct 26 as **endorsement by money**: billionaires fund super PACs, those PACs back or attack candidates, and the section asks who the billionaires are, where their money went, and how their PACs' candidates did. Traditional public endorsements (politicians, party groups) are dropped.

## Intent
Answer two questions for a careful reader, using FEC data and nothing picked by hand:
1. **Who and where:** which billionaires, on both sides, are funding 2026 super PACs, how much, through which PACs, and how much of it reached House races.
2. **Did it win:** how often the House candidates that billionaire-backed super PACs supported in primaries won their primaries. After Nov 3, the same check runs for the general election.

This is descriptive and predictive, not causal. PACs often back candidates who were already favored, so a win rate is not proof the money worked. The write-up says so next to the numbers.

Audience: recruiters and hiring managers on GitHub. The section must read as nonpartisan. Matt does not want readers able to infer his politics.

## Goals
- A billionaire list built by rule, with every number traceable to FEC records or a cited source.
- For each billionaire: total super PAC giving (their own name, plus sourced organization and LLC money), the top recipient PACs, and an estimate of how much of it reached House races.
- A list of billionaire-backed PACs (see Definitions) and the House candidates they supported or opposed in primaries, with outcomes.
- Section 2 of the write-up, `reports/billionaire-money.md`, in the same format as sections 1 and 3: charts, a numbers JSON behind every figure, and caveats next to the numbers they affect.
- Before Nov 3: the primary results. After Nov 3: a general election update, added as a dated section.

## Non-goals
- Traditional endorsements by politicians or groups.
- Senate, governor, presidential, and state races, except as context ("this much of their giving went elsewhere").
- Tracing money through groups that don't disclose donors. Where a trail ends, the write-up says so.
- Causal claims.

## Anti-goals
- **A list that's lopsided because of method.** The top individual donors lean Republican, partly because Democratic megadonors more often give through organizations. Counting only individuals would mislead, which is why sourced organization and LLC money is counted for everyone, with the same rule for both sides.
- **Labels from memory.** Every person-to-entity link needs a public source in the CSV, the same standard as the network labels in section 1.
- **Measuring party performance by accident.** Large party-aligned super PACs (CLF, HMP, SLF, SMP) back nearly every competitive nominee in their party. They don't count as "billionaire-backed" unless the 50% rule says so.
- **Judging language.** No "bought", "flooded", or "pouring". Amounts and outcomes only.

## Decisions made with Matt
1. Section 2 becomes billionaire money, covering both who and where and did it win.
2. **All billionaires, both sides**, not only tech.
3. **Organization and LLC money is attributed** to a person where a public source makes the link.
4. **Billionaire-backed PAC:** one where a single billionaire, together with their sourced connected entities, supplied **at least 50%** of the PAC's 2026-cycle receipts.

## Recon done on Oct 26 (from the FEC Schedule A API, contributions of $250K or more to committee types O, V, and W, 2026 cycle)
- Of 2,438 such contributions, 946 came from individuals, 1,029 from organizations, and the rest from PACs and committees. Organization gifts are larger in total than individual gifts.
- About 407 individuals gave $250K or more, totaling about $1.13B. The largest individuals include Yass, Adelson, Uihlein, Musk, Singer, Griffin, Schwarzman, Hendricks, the Brockmans, Bloomberg, Hoffman, Simon, Mandel, Eychaner, and Pritzker.
- Much of the money went to non-House vehicles (SLF, MAGA Inc., state and governor PACs).
- Candidate single-donor PACs seen: America PAC (Musk), Restoration of America (Uihlein), School Freedom Fund and V-PAC (Yass), Lone Star Rising (Hoffman), and Stand for New York (Bloomberg). These are unverified until the 50% rule is computed.
- Gotchas: `is_individual=true` did not exclude organizations, so filter on `entity_type == "IND"`. Use the API's `last_indexes` for keyset pagination. Drop memo rows (`memo_code == "X"`).

## Definitions
- **Billionaire:** a person on the Forbes 2026 World's Billionaires list (April 2026 edition). Spouses' giving is combined into one household when Forbes lists them jointly or a public source names the couple as giving together (for example the Brockmans). The household rule applies the same way to everyone.
- **Super PAC giving:** contributions to committee types O, V, and W in the 2026 cycle, net of refunds. That's the person's own contributions, plus contributions from entities a public source ties to them. Memo entries are excluded.
- **In the list:** total giving of at least $1M.
- **PAC concentration:** a billionaire's giving to a PAC divided by that PAC's total 2026-cycle receipts (FEC committee totals).
- **House share of a billionaire's money:** for each PAC, the billionaire's share of its receipts times its House independent expenditures, summed over their PACs. This assumes money is spent in proportion to who gave it, and the write-up says it's an estimate.
- **Primary support:** an `outside_spending` row with `support_oppose = 'S'` and `election_type = 'P'` (including primary runoffs where coded) for a House candidate, from the 2026-10-24 snapshot.
- **Primary won:** the supported candidate is a November nominee on the pinned 2026 nominee page (`NOMINEES_PAGE`), matched by race and name with the existing matcher. In California and Washington top-two races, advancing counts as winning. Races still pending a runoff are listed as pending, not scored.
- **Opposed candidates:** reported separately. An opposed candidate who is not a nominee counts as an outcome the PAC wanted.

## Claude's calls (Matt can override)
- **Forbes edition:** April 2026 World's Billionaires, matched by name with a source URL per person in `data/manual/billionaires.csv`. People whose net worth crossed or fell below $1B since April aren't re-checked.
- **Finding candidates:**
  - Start from all individual donors with $1M or more in 2026 super PAC giving.
  - Add every organization donor of $1M or more, and research whether a public source ties it to a person.
  - Keep the people on the Forbes list.
  - Pull each person's complete giving by contributor-name search, all amounts.
- **Entity attribution standard,** applied the same way to everyone:
  - an FEC filing that names the person (for example as the LLC's contact or as the donor behind an earmark)
  - the person's own public statement
  - a major news outlet naming the entity as theirs

  Entities with no source stay unattributed, and their totals are reported as "not traced". Stored in `data/manual/donor_entities.csv` with `entity_name, person, source_url, evidence_type`.
- **Snapshot:** House spending comes from the 2026-10-24 `outside_spending` snapshot, the same snapshot as the predictions. Schedule A and committee totals are pulled once and stamped with their pull date.
- **Output files:** `reports/billionaire-money.md`, charts in `reports/figures/`, and `reports/figures/billionaire_money_numbers.json`. A build script reads only committed CSVs and the database, following `scripts/build_tech_money_report.py`.

## Claude's calls from the builder check (Matt can override)
- **Lean, computed rather than labeled.**
  - Each billionaire gets a computed lean: the share of their House-attributed money that went to supporting Democrats or opposing Republicans, versus supporting Republicans or opposing Democrats. This uses `outside_spending.party` for their PACs, weighted by their share of each PAC.
  - The write-up shows the lean as a number. It never shows a hand-assigned side.
  - PACs with no House spending have no lean.
  - The lopsidedness check compares total money by computed lean, and it is reported openly.
- **The 50% rule, exactly.**
  - The numerator is the billionaire's household's direct contributions to the PAC, plus contributions from their sourced entities.
  - The denominator is the PAC's total 2026-cycle receipts from FEC committee totals, including transfers from other committees.
  - Pass-through money from another PAC is not followed, which is a stated limitation.
  - There is no joint threshold. Two billionaires who each give 30% don't make a PAC billionaire-backed.
  - For PACs between 35% and 50%, entities giving $100K or more are also checked for a sourced link before the PAC is ruled out.
  - Itemized contributions are reconciled against committee totals for every PAC tested. For example, America PAC's 2026 totals report $216M in receipts, but the itemized rows found in recon come to about $50M. Unexplained gaps are reported, and no PAC is classified on numbers that don't reconcile.
- **Primary win rate.**
  - The unit is a distinct candidate in a race. A candidate counts as supported by a PAC if it spent $10,000 or more supporting them in that race's primary.
  - The headline is pooled across all billionaire-backed PACs, with a per-PAC table.
  - Outcomes are checked by FEC candidate ID first, against the nominee IDs already matched in `reports/predictions/2026-general-simple.csv`, then by race and name.
  - A supported candidate not found either way goes in a manual-review list. It is never counted as a loss automatically.
  - Withdrawals count as "not the nominee", and the write-up notes this.
  - Whether a primary was contested can't be determined without full primary candidate lists, so it is stated as a limitation. Uncontested primaries rarely draw independent expenditures.
- **House share.**
  - The House share uses all House independent expenditures in the 2026-10-24 snapshot (primary and general, support and oppose), divided by the PAC's independent expenditures across all offices from the bulk file.
  - It is reported both as dollars and as a percentage of the billionaire's giving.
  - Money not spent as independent expenditures (transfers, contributions, unspent cash) is reported as "other or not yet spent".
  - Receipts are cut off at each PAC's latest report through Oct 14, to match the snapshot.
- **What counts as before Nov 3.** Part 1 means the billionaire list, giving, attribution, the billionaire-backed PAC list with the 50% computation, and the House share. Part 2 (primary) means primary outcomes. Both are due before Nov 3.
- **Forbes.**
  - A per-person Forbes profile URL is enough. The builder doesn't reproduce the whole list.
  - Large donors (at least $1M in giving) who aren't on the April 2026 list are excluded from the analysis but listed in an appendix table with their totals, so readers can see who was left out and why.

## Constraints
- Before Nov 3, 2026: Part 1 and the primary part of Part 2, committed and pushed on a new branch stacked on `money-and-winning`.
- Same conventions as the rest of the repo: pandas, sqlite3, pytest on real saved rows, NumPy docstrings, no em dashes, plain commit messages with no attribution lines, and no data/raw or data/processed in git.
- No 2026 tables from earlier sections are modified. New tables only.
- The frozen prediction files in `reports/predictions/` are never touched.

## Left to the builder
- Table layouts for Schedule A, committee totals, and attribution.
- Name normalization and dedupe for donors (spelling variants and duplicate filings).
- Chart choices, within the neutrality rules.
