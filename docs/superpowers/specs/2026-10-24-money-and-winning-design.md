# Money and Winning: Design (Write-up Section 3)

Phase 4 of `2026-10-20-midterm-money-design.md`. The original plan modeled primary outcomes. That changed on Oct 24: the pre-election deliverable is now a set of **general election predictions** committed to git before Nov 3, 2026, and scored after results are in. Primary outcomes and the "super PAC era" history are later work (see Non-goals).

## Intent
Answer one question for a careful reader: **does money predict who wins a House general election?** That means asking whether the money edge still predicts winning once incumbency and district partisanship are accounted for. The section treats this as prediction, not cause. Money follows likely winners as much as it creates them, and the write-up says so plainly.

The git timestamp is part of the point. Predictions are committed before Nov 3, so nobody can say they were fit to the results.

Audience: recruiters and hiring managers for data roles, reading on GitHub. Same neutrality rules as the tech money section.

## Goals
1. **Simple predictions (committed first, target Oct 28):** for every contested 2026 House general, the money leader and their share, the Cook favorite, and outside spending shown alongside.
2. **Model predictions (committed before Nov 3 if ready and checked):** a logistic regression trained on the 2022 and 2024 House generals, giving each 2026 nominee a win probability from money share, incumbency, and PVI.
3. **After Nov 3:** score the money rule, the Cook favorite, and the model against results, then write section 3 with the scored results.

## Non-goals
- Causal claims about money.
- Primary election outcomes. They would need a primary results dataset, which is endorsements-phase work.
- **The "super PAC era" section** (how outside money changed from about 2008 to 2026). Matt wants this. It's a separate post-Nov 3 project that reuses the bulk-file pipeline across past cycles.
- Senate races.

## Anti-goals
- Any change to the 2026 predictions after Nov 3. The committed file is frozen. Corrections after Nov 3 go in a separate, clearly dated file.
- A model that could be accused of hindsight. If it isn't committed before Nov 3, it ships labeled "built after the election."
- Counting self-funding as fundraising. A candidate's own money never counts toward money share.
- Hiding races where the money rule loses. The disagreement list (money leader versus Cook favorite) is published in full.

## Decisions made with Matt
- General election predictions before Nov 3. The primary model is dropped from the pre-election scope.
- Both a simple rule plus the Cook comparison and a trained model.
- Order: simple predictions locked in first, around Oct 28, so the timestamp is safe. The model follows before Nov 3 if it's ready, otherwise after, clearly labeled.
- The "super PAC era" history is post-Nov 3.
- **Training money is pre-election money.** For 2022 and 2024, each campaign's totals come from what it had reported as of its pre-general report, from the OpenFEC reports API. That matches the 2026 snapshot, which covers reports through Oct 14. End-of-cycle totals (`webl22`, `webl24`) would include money raised after the election, which leaks the outcome into the money feature. Those files may still be used for the candidate list and IDs, but not for money. This adds a few days, so the model may land just after Nov 3, labeled as built after the election.
- **Push and tag when verified:** the builder pushes each prediction commit and its tag to GitHub as soon as the predictions are verified, without asking first. The work goes on a new branch stacked on `tech-money`, and open PRs are left alone.

## Definitions
- **Money share:** in each race, a candidate's `external_contributions` divided by the total for the top two nominees. Negative values are floored at 0. A nominee with no FEC record counts as $0, because campaigns under the FEC's $5,000 threshold don't file.
- **Money leader:** the nominee with a share above 50%.
- **Cook favorite:** the party Cook rates as Likely or Lean, plus Solid (including inferred Solid). Toss Up has no favorite.
- **Contested race:** two or more general election nominees on the ballot. Unopposed races are listed but not scored.
- **Incumbent:** `incumbent_challenge = 'I'` for the 2026 cycle. Same-party top-two races (CA, WA) are scored on money only, with no Cook favorite.

## Claude's calls (Matt can override)
- **Nominee list:** use a source that names the November nominees per district. First choice is the 2026 House elections Wikipedia page, pinned by revision ID as in `src/ratings.py`. Match nominees to FEC candidate IDs by state, district, and last name, with a hand-checked CSV in `data/manual/` for anything that doesn't match. Cross-check against the Oct 23 pre-general filers. Every nominee who raised money should appear there, and the reverse check finds stragglers.
- **Snapshot:** money comes from the 2026-10-23 snapshot. It already includes pre-general reports through Oct 14.
- **Rule uses candidate money only.** Outside spending (support and oppose, by candidate) appears as context columns. The model tests whether adding outside spending improves prediction on 2022/2024.
- **Training data:** House generals in 2022 and 2024, with money as of the pre-general report (see Decisions). Results come from the FEC's official results publication for each election, keyed by FEC candidate ID. If 2024 isn't published or doesn't parse, fall back to another documented public source. PVI comes from each cycle's own Cook PVI, using the same pinned-Wikipedia method.
- **Model:** logistic regression (scikit-learn). Inputs are money share, an incumbent flag, and PVI oriented toward the candidate's party. Evaluation uses leave-one-cycle-out (train 2022 and test 2024, then the reverse) and reports accuracy, Brier score, and calibration. It also compares against the money rule and the Cook favorite on the same held-out races. Same-party and third-party races are left out of training.
- **Where predictions live:** `reports/predictions/2026-general-simple.csv` and `reports/predictions/2026-general-model.csv`, each committed and pushed before Nov 3, with a git tag (`pre-election-simple`, `pre-election-model`) on the commit.
- **Which nominees count:** money share and the model use the Democratic and Republican nominees in D versus R races. Races without a D versus R pair (same-party top-two, or a major party with no nominee) use the top two nominees by money for the money rule, have no Cook favorite, and are left out of the model. A race where a third-party or independent nominee raised more than either major-party nominee is flagged and left out of the model and model scoring.
- **Model unit:** one row per race: the probability that the Democratic nominee wins a D versus R race. The two probabilities in a race always sum to 1, and the Brier score is computed per race.
- **Abstentions:** Toss Up (no Cook favorite) and an exact 50% money share (no money leader) are abstentions, not wrong answers. Scoring reports each predictor's accuracy on the races where it made a call, how many races it covered, and accuracy on the shared set of races where all three made a call, so the predictors are compared on the same races.
- **Unsettled nominees:** a race whose nominee isn't confirmed in the pinned nominee source (a pending runoff, a withdrawal, or a replacement) is listed as "nominee unconfirmed" and isn't scored. No guessing in a frozen file.
- **Historical Cook ratings:** for 2022 and 2024, use each cycle's House ratings Wikipedia page, pinned to the last revision before that election day. Seats not listed get inferred Solid from PVI, the same method as 2026.
- **Scoring:** after Nov 3, results for 2026 come from the AP or state results as reported, and are switched to official results when those are published. Called races only. Uncalled races are listed as pending.

## Constraints
- Same stack and conventions as phases 1 and 2. pandas, sqlite3, and pytest on real saved rows. scikit-learn is a new dependency for the model. NumPy docstrings, no em dashes, plain commit messages with no co-author lines.
- Simple predictions committed and pushed by about Oct 28, 2026. The model is committed and pushed before Nov 3 to count as pre-election.
- Prediction files are never edited after their tag.

## Left to the builder
- Parsing details for the nominee source and the FEC results files.
- How past-cycle data is stored. Separate tables keyed by cycle, or a separate database, as long as 2026 snapshots stay untouched.
- Chart choices for section 3, within the neutrality rules.
