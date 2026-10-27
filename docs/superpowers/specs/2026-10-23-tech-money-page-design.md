# Tech Money in the 2026 Midterms: Design (Write-up Section 1)

Phase 2 of the project in `2026-10-20-midterm-money-design.md`. That spec framed this as Power BI page 1 on "industry super PACs." After looking at the Oct 23 data, it is now about tech money specifically: crypto and AI super PAC networks, plus tech billionaire donors.

**Format change:** the MVP is a written analysis on GitHub instead of a Power BI dashboard. Each phase becomes a section of the write-up (tech money, endorsements, money and winning). Power BI moves to the post-MVP list along with full Senate coverage.

## Intent
Show that a small number of tech-funded super PAC networks and tech billionaires are spending heavily in 2026 races, and show where the money went. The write-up lets the numbers make the case. It describes amounts, targets, and sides. It does not tell the reader what to think about them.

Audience: recruiters and hiring managers for data roles. They should come away thinking the analysis was careful and fair, and they should not be able to tell the author's politics from the write-up. They will most likely read it on GitHub.

## Goals
- Total spending by each tech network in 2026 House races, and its share of all House outside spending.
- Who each network spent for and against, by candidate party and by support or oppose.
- Where the money went: competitive seats versus safe seats (Cook rating), and the top races by dollars.
- After Nov 3: the same networks' Senate spending, and a tech billionaire donor layer covering both parties.

## Non-goals
- Causal claims. The write-up does not say the money changed who won. The money and winning section handles money and outcomes.
- Senate in the endorsements and money and winning sections. They stay House-only for the MVP. Full Senate coverage is a later branch.
- Governor, state, and presidential races.
- Non-tech industries (pharma, oil, AIPAC's United Democracy Project, and so on). They appear only inside the "all other outside spending" total.

## Anti-goals (failure even if it technically works)
- **Reading as partisan.** Examples: labeling only right-leaning donors, wording that judges ("bought," "flooded"), colors that make one side look bad, or picking individuals by hand.
- **Labels from memory.** Every committee-to-network and person-to-list assignment needs a public source in the CSV.
- **Mixing measures.** Billionaire donations (money in) are never added to network spending (money out). They are different money flows and would double count.
- **Charting totals we know are incomplete** without saying so.

## Decisions made with Matt
1. **Networks tracked:** crypto and AI. Starting list from the Oct 23 snapshot, to be confirmed with sources before labeling:
   | Network | Committees (FEC ID) | House spending, Oct 23 |
   |---|---|---|
   | Fairshake (crypto) | Fairshake C00835959, Protect Progress C00848440, Defend American Jobs C00836221 | about $49M |
   | Leading the Future (AI industry) | Think Big C00923417, American Mission C00916692, Leading the Future C00916114 ($0 direct) | about $23M |
   | Public First (AI safety), **unconfirmed** | Jobs and Democracy PAC C00928374, Defending Our Values PAC C00928390, Public First C00930503 ($0 direct) | about $23M |

   The Public First affiliations come from Claude's memory and must be verified. Claude is made by Anthropic, which has reportedly funded Public First. That is disclosed here so the sourcing on this network gets extra scrutiny.
2. **Billionaires on both sides, picked by rule:** anyone on the Forbes billionaires list in the technology category who gave $1M or more to federal super PACs (committee types O, V, W) in the 2026 cycle. Whoever meets the rule is included, whatever their party. Musk is expected to qualify. Most of his 2026 money is in Senate, governor, and presidential races (for example, the Texas Senate primary), so his House footprint is small: America PAC shows $87K.
3. **Billionaires are measured as money in:** what each person gave, and to which super PACs. Networks are measured as money out: what each PAC spent, and in which races. The two are shown separately.
4. **Chambers:** this section covers House and Senate. The endorsements and money and winning sections stay House-only.
5. **Order:**
   - **Before Nov 3:** data gap fix, House network spending, House version of this section. (The other two sections are also due before Nov 3 under their own specs.)
   - **After Nov 3:** Senate spending for the same networks, then the billionaire donor layer.

   Reasoning: the pre-election deadline matters most for the money and winning predictions. Senate spending and donations are past events and are just as valid a week later.
6. **Neutral presentation:** spending is broken into four buckets (supporting Democrats, opposing Democrats, supporting Republicans, opposing Republicans) instead of one net-benefit-to-party number. Party colors follow the usual convention (blue D, red R) and are applied equally.

## Known problem to solve first: outside spending looks incomplete
In the Oct 23 snapshot, Congressional Leadership Fund (C00504530, the main House Republican super PAC) shows only $264K of House independent expenditures. That is almost certainly wrong this late in the cycle. The likely cause is that `/schedules/schedule_e/by_candidate/` is built from processed filings and lags the 24- and 48-hour reports that dominate late spending.

Required before any total goes on a chart:
1. Confirm the gap. Compare CLF and a few other large committees against the raw `/schedules/schedule_e/` endpoint and the committee pages on fec.gov.
2. If it holds, switch `outside_spending` to a source that includes recent 24- and 48-hour reports, without double counting. Amended filings and 24/48-hour reports that are later rolled into periodic reports are the known traps. The original spec chose the aggregated endpoint to avoid exactly this, so the new method has to deal with it explicitly and be tested on real saved responses.
3. Record the method and its limits in the README caveats.

The $481M "all House outside spending" baseline and every network share depend on this.

**Fallback if the fix isn't solid by Nov 3 (Matt's call):** publish the House version with each network's own spending (dollars, sides, races) and leave out "share of all outside spending." Add the share once the fix is confirmed. The networks' own numbers are less exposed to the gap than the overall total, but this should be spot-checked against fec.gov before publishing.

## Open question (after Nov 3)
- **Billionaire rule and Forbes categories.** Forbes files many crypto and venture capital billionaires under "Finance & Investments," not "Technology." A strict Technology rule could leave out the donors most tied to the networks in this section. One candidate rule: Forbes Technology category, or a Forbes source of wealth listed as crypto or tech venture capital. Also to decide: which Forbes list and edition date to use. Matt will decide this before the billionaire layer is built.

## Constraints
- Same stack and conventions as phase 1: Python 3.13, pandas, requests, SQLite through `sqlite3`, pytest on saved real responses, NumPy docstrings, no em dashes, plain commit messages with no co-author lines.
- Snapshots stay keyed by `pulled_at`, and every chart states its pull date.
- Labels live in `data/manual/` with a `source_url` on every row, validated by `src/manual.py`.
- The House version of this section must be done before Nov 3, 2026.

## Claude's calls (Matt can override)
- **Label file shape:** `pac_industries.csv` gains a `network` column (for example `Fairshake`), and `industry` takes one of `crypto`, `ai_industry`, `ai_safety`. The loader validates `industry` against that list.
- **Chamber column:** Senate support needs a `chamber` column (`H`/`S`) on `candidates`, or a way to derive it from the candidate ID prefix, so House and Senate rows can't be mixed in a query by accident.
- **Billionaire name matching:** count contributions made in the person's own name. Gifts through LLCs or trusts are only counted when a public source ties the entity to the person, and that source goes in the CSV. Undercounting is documented as a caveat.
- **Billionaire list file:** `data/manual/tech_billionaires.csv` with name, Forbes source URL, and the name variants used to search FEC records.
- **"Competitive" means** Cook Toss-up, Lean, or Likely. Solid seats count as safe.
- **Primary versus general:** `outside_spending` gains an election column (primary or general) from Schedule E's election type. The competitive-versus-safe split uses general election spending only, because Cook ratings describe the general. Primary spending gets its own view. Fairshake spends heavily in primaries for seats that are safe in November, and lumping that money into "safe seats" would misdescribe what it was for.
- **Denominator:** "all outside spending" means independent expenditures by super PACs and hybrid PACs (committee types O, V, W), the same population the networks belong to. Party committee spending (DCCC, NRCC) and nonprofit spending are reported as separate context numbers, not added to the base. The README states this definition.
- **Snapshot after the fix:** the Oct 23 snapshot is kept as-is and marked in the README as built with the aggregated endpoint. The first pull with the fixed method becomes the official pre-election snapshot, and this section's charts use it. Snapshots built with different methods are not compared with each other.
- **What counts as a source for a network label,** applied the same way to all three networks: FEC evidence (the filing names the parent group, a shared treasurer, or transfers between the committees), the group's own public statement, or reporting from a major news outlet that names the committee. A committee without one of these is left out of the network and stays in "all other" spending.
- **Write-up format:** a markdown report in `reports/` with PNG charts in `reports/figures/`, which GitHub renders directly. A Python script builds every chart and the key numbers from the database, so rerunning it after a new pull refreshes the figures. A notebook was ruled out because the repo rule is to clear notebook outputs before committing, which would remove the charts. The prose is written by hand, and each number in it is checked against the script's output.
- **The Anthropic disclosure** stays in this spec. The public write-up relies on sourced labels instead, so the disclosure doesn't need to appear there.

## Left to the builder
- The exact replacement method for outside spending, within the constraints above.
- How the analysis queries are organized (SQL views or pandas) and where they live.
- Chart types and layout, within the neutrality rules above and the format below.
- Senate pull details: the candidates filter, outside spending batches, and Senate ratings for the competitive-versus-safe split.
