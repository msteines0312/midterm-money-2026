# Endorsements in the 2026 House Primaries

*Section 2b of the Midterm Money 2026 write-up. Endorsement lists read October 27, 2026. FEC fundraising data as of October 24, 2026. November nominees from the frozen pre-election predictions.*

## The question

How often did candidates endorsed before their 2026 House primary go on to win it? The plan was to split that rate by incumbents, open seats, and challengers, and by whether the primary was contested. The hard part is selection. Endorsers tend to pick candidates who were already likely to win, so a high win rate on its own says little about what an endorsement did. This section reports the rates next to two checks on that problem. It does not claim to measure an endorsement's effect.

This version covers one endorser, Donald Trump. Two more lists are built but not yet read, for reasons explained below.

All figures come from `scripts/build_endorsements_report.py`, which reads the database and the research files and writes the charts and [`endorsements_numbers.json`](figures/endorsements_numbers.json). Every number below can be checked against that file.

## How endorsers and endorsements were identified

An endorser is tracked when it publishes a public list of its 2026 House primary endorsements and each endorsement can be dated. The same rule applies to both parties. The endorsers and where their lists live are in [`data/manual/endorsers.csv`](../data/manual/endorsers.csv), and every endorsement is in [`data/manual/endorsements.csv`](../data/manual/endorsements.csv) with a source link.

- **Donald Trump.** Ballotpedia keeps a table of his 2026 House endorsements, and each row links the Truth Social post that made it. The page was saved from a browser because Ballotpedia blocks automated reads. The endorsement date is read from the post itself: Truth Social runs on Mastodon, whose post IDs carry the time the post was made. Rows Ballotpedia marks as general election only were dropped (16), along with special elections (2), which leaves 230 primary endorsements, all matched to an FEC candidate ID.
- **Club for Growth PAC and Justice Democrats.** Both publish a list page with no dates. The plan is to read every Wayback Machine copy of each page and date a candidate by the first copy that lists them, which gives a date on or after the real endorsement and so can only make the timing rule stricter. While this section was being written, the archive refused all downloads for about twelve hours, so these two lists are not in this version. Justice Democrats would have been the only endorser on the Democratic side.

Two other Democratic-side groups were checked and dropped. The Working Families Party list had no archived copies in 2026, and EMILY's List's list page is a roster that keeps every past candidate, so it cannot date a 2026 endorsement.

### The rules for counting

- **Timing.** An endorsement counts only if it came on or before the candidate's primary. Primary and runoff dates come from the FEC's 2026 primary dates document, in [`data/manual/primary_dates.csv`](../data/manual/primary_dates.csv). One endorsement came after the primary, one came between the primary and the runoff, and one has no linked post to date it. All three are left out of the win rates.
- **Winning** means becoming the November nominee, the same rule as the billionaire section. In California and Washington, every candidate who advances from the top-two primary counts as a win. Louisiana's House primaries were moved to November 3, so its 3 endorsements are pending.
- **Never on the ballot.** 11 candidates Trump endorsed early, all of them sitting members, retired or left the race before their primary. Ballotpedia records them as not on the primary ballot. They did not lose a primary, so they are left out of the win rates rather than counted as losses.
- **Two candidates in one primary.** If an endorser backs two people on the same ballot, one of them has to lose. That happened once: Trump endorsed Tony Gonzales in TX-23 and later endorsed Brandon Herrera for the runoff. Those 2 rows are left out.
- **Contested** means at least two candidates of the same party in the race each raised $10,000 or more from outside sources. Full primary ballots are not in the database, so this is a proxy. A hand check of 15 random races against Wikipedia's results agreed on 9 of 11 that could be judged. Both misses had a second name on the ballot who raised less than $10,000, so the proxy measures a funded contest, which is a stricter test than a contested ballot.

As a check on the scoring, every outcome was compared with Ballotpedia's own result for that row. They agree on 227 of 227 decided endorsements.

## Findings

### Win rates

![Endorsed candidates who won contested House primaries](figures/endorsements_win_rates.png)

In contested primaries, Trump-endorsed candidates won 94% (76 of 81). By type of race:

| Contested primary | Won |
|---|---|
| Incumbent | 95% (35 of 37) |
| Open seat | 91% (21 of 23) |
| Challenger | 95% (20 of 21) |
| All contested | 94% (76 of 81) |

The lines on the chart are 95% Wilson intervals. With 21 to 37 candidates per group, the intervals are wide and overlap, so the data do not show a difference between the three kinds of race.

"Challenger" is the FEC's label for a candidate running in a seat that already has an incumbent. Here it almost always means a Republican running in the primary for a seat a Democrat holds, not someone running against a Republican incumbent.

Endorsed candidates in primaries with no second funded candidate won 100% (131 of 131). Those are reported but kept out of the headline, because an unopposed candidate wins whether or not anyone endorses them.

Five endorsed candidates did not become the nominee: Cory Mills (FL-07) and Andy Ogles (TN-05), both incumbents; Catalina Lauf (FL-19) and Jackson Lahmeyer (OK-01) in open seats; and Amir Hassan (MI-08), a challenger.

### Against everyone in the same kind of race

![Endorsed candidates against everyone in the same kind of race](figures/endorsements_baseline.png)

The baseline is every Republican in the same kind of contested primary who raised $10,000 or more. In open seats, 25% (41 of 165) of them became the nominee, against 91% (21 of 23) of Trump's endorsed candidates. Among challengers it was 28% (78 of 277) against 95% (20 of 21). For reference, the same rates for Democrats were 22% (53 of 237) and 25% (120 of 477).

The gap is large, but it is not an estimate of what an endorsement does. A contested open seat has several funded candidates and only one nominee, so the baseline rate is low by construction, and endorsers are choosing among those same candidates with knowledge of who is ahead.

There is no incumbent baseline. The database cannot tell a member who lost a primary from one who retired or ran for Senate or governor. All three show up as an incumbent who did not become the nominee. Of the 41 contested Republican incumbents scored that way, 13 are on Trump's list, and Ballotpedia records only 2 of those as losing a primary. Many of the other 28 ran for statewide office or retired. A baseline built on these would mostly measure departures, not primary losses.

### Did endorsements go to the front-runners?

![Endorsed candidates' win rate, by whether they already led in money](figures/endorsements_favorites.png)

In contested primaries, 88% of Trump's endorsed candidates were already the top fundraiser of their party in the race. Those candidates won 96% (68 of 71) of the time. The few who were not the money leader won 80% (8 of 10). Ten candidates is too few to say much, but the pattern fits the selection problem: most endorsements went to candidates who already looked like the favorite by the standard the rest of this project uses.

## Method and caveats

- **Endorsers choose whom to back.** Nothing here separates the effect of an endorsement from an endorser's choice of who to endorse. Trump endorsed most Republican incumbents seeking reelection, often in batches long before any primary, and incumbents rarely lose primaries. The rates describe how his picks did. They do not say his picks would have done worse without him.
- **One endorser.** The section rests on one Republican endorser. There is no Democratic-side comparison in this version, and none should be read into the Democratic baseline rates, which describe all Democratic candidates.
- **The contested proxy** agreed with a hand check on 9 of 11 races, and it misses primaries where the second candidate raised little money. Some primaries counted as uncontested here had more than one name on the ballot.
- **Fundraising** is external contributions (money raised from others, not the candidate's own loans) as of October 24, 2026, which is after every primary except Louisiana's. The "top fundraiser" check uses totals that include money raised after the primary, which can favor the winner.
- **Matching.** Every endorsement was matched to an FEC candidate ID by race and name, with hand-checked fixes for duplicate filings and the Nehls twins in TX-22. None were left unmatched.

## What's next

- Add Club for Growth PAC and Justice Democrats once the Wayback Machine allows downloads again. The build reads cached copies first, so a rerun only fetches what is missing, and the report rebuilds from the same script.
- Score Louisiana's 3 pending endorsements after its November 3 primary.
- After November 3, check whether endorsed nominees did better in the general election than the money model expected.
