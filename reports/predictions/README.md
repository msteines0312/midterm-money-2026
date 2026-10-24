# 2026 House general election predictions, simple version

This folder holds the first of two sets of pre-election predictions for the 2026 U.S. House general elections. Each race gets two plain rules and no model: which nominee has raised more outside money (the **money leader**), and which party the Cook Political Report rates ahead (the **Cook favorite**). The file puts them side by side so a reader can see where they agree and where they do not. It is committed before election day so it can be scored against results afterward.

File: [`2026-general-simple.csv`](2026-general-simple.csv). Built by [`scripts/build_simple_predictions.py`](../../scripts/build_simple_predictions.py).

## Frozen after the tag

The CSV is tagged `pre-election-simple` and is never edited after that. If a number turns out to be wrong, the fix goes in a new dated file next to this one.

## What goes into each prediction

- **Money.** Each nominee's `external_contributions` from the FEC bulk summary file pulled on 2026-10-24: individual contributions minus refunds, plus PAC and party contributions, minus committee refunds. The candidate's own money (contributions and loans) is never counted, and negative totals count as $0. A nominee with no FEC match counts as $0.
- **Money snapshot date.** Money is from the 2026-10-24 snapshot, which includes reports through Oct 14 (the Pre-General deadline). The first build used the 2026-10-23 snapshot, but that bulk file had not yet absorbed some candidates' Pre-General reports: 176 funded nominees in Democrat-versus-Republican races still showed a Sep 30 or earlier report. A fresh pull on 2026-10-24 fixed this, so the date moved. The 2026-10-23 rows stay in the database unchanged.
- **Races whose money leader changed between snapshots.** FL-27 (Republican to Democratic), NV-02 (Republican to Democratic), and TX-15 (Republican to Democratic). No other race changed.
- **Nominees.** Parsed from Wikipedia's page on the 2026 House elections at a pinned revision (ID 1381568365). All 435 races have confirmed nominees at that revision. Nominees are matched to FEC candidates by race and last name, with 57 hand-checked overrides in `data/manual/nominee_matches.csv`.
- **Cook rating.** Read from Wikipedia's Cook ratings table at a pinned revision, because Cook's own lists are paywalled. That table lists only competitive seats, so for the rest the rating is inferred from district partisanship (PVI) as Solid D or Solid R. The CSV does not mark which is which; see the note at the end of this file.
- **Abstentions.** A Toss Up rating gives no Cook favorite. An exact 50% money share gives no money leader. Abstentions are not misses and are left out when the two rules are compared.

## Which races are scored

Only `D_vs_R` races (one Democratic and one Republican nominee, third parties allowed) are compared against Cook. In `same_party` and `other` races, `money_leader_party` is only the party of the richer nominee (for example DEM in a race between two Democrats), which says nothing about a Cook favorite, so those rows are listed but not scored. `unopposed` races are listed and not scored.

## Columns

| Column | Meaning |
|---|---|
| `race_id` | State and district, such as `WI-03`. At-large seats use `00`. |
| `status` | `confirmed` or `unconfirmed`, from the nominee page. |
| `race_type` | `D_vs_R`, `unopposed`, `same_party` (two nominees from one major party), or `other`. |
| `dem_name`, `dem_candidate_id` | The Democratic nominee and FEC candidate ID. In `same_party` and `other` races, the richer of the top two nominees by money. |
| `rep_name`, `rep_candidate_id` | The Republican nominee and FEC candidate ID. In `same_party` and `other` races, the second of the top two. |
| `dem_money`, `rep_money` | External money in dollars for the two nominees above. |
| `dem_money_share` | `dem_money` divided by the sum of both. Empty when both are $0 or the race has one nominee. |
| `money_leader_party` | `DEM` or `REP` for the side with more money. Empty on an exact 50% share, when neither has money, or when the richer of two is not a major-party nominee. |
| `cook_rating` | Cook's rating, such as `Lean R`. |
| `cook_favorite_party` | `DEM` or `REP` for Lean, Likely, or Solid ratings. Empty for Toss Up and for races that are not `D_vs_R`. |
| `incumbent_party` | Party of the sitting member if that member is a nominee. Empty otherwise. |
| `outside_support_dem`, `outside_oppose_dem`, `outside_support_rep`, `outside_oppose_rep` | General election super PAC spending for or against each nominee, in dollars. Context only, not used by either rule. |
| `money_and_cook_agree` | `True` or `False` when both rules made a call, empty otherwise. |
| `third_party_outraised` | `True` when a third-party or independent nominee raised more than the lower of the two major-party nominees. |
| `notes` | Plain-language notes, including nominees with no FEC match. |

## Counts

- Races: 435 (410 `D_vs_R`, 11 `other`, 9 `same_party`, 5 `unopposed`).
- Among `D_vs_R` races, Cook abstentions (Toss Up): 21. Money abstentions: 0.
- Both rules made a call in 389 races. They name the same party in 369 and different parties in 20.
- Four Democratic or Republican nominees have no FEC record (LA-02 Renada Collins, LA-03 Kate Cotten, LA-03 Caleb Walker, MD-04 George McDermott) and count as $0. Independent and minor-party nominees without a match also count as $0 and were not searched one by one. Because they count as $0, the other nominee leads on money by default in their races: in MD-04 (a `D_vs_R` race, so it is scored) Glenn Ivey leads because Republican George McDermott has no FEC record, and in LA-02 and LA-03 (`other` races, not scored) the missing Collins, Cotten and Walker never appear in the top two by money.

## Races where money and Cook name different parties

| Race | Nominees | Money leader | Cook rating |
|---|---|---|---|
| AL-02 | Shomari Figures (D) vs. Rhett Marques (R) | Democratic | Likely R |
| CO-04 | Eileen Laubacher (D) vs. Lauren Boebert (R) | Democratic | Solid R |
| CO-05 | Jessica Killin (D) vs. Jeff Crank (R) | Democratic | Lean R |
| FL-07 | Bale Dalton (D) vs. Ryan Elijah (R) | Democratic | Likely R |
| FL-09 | Darren Soto (D) vs. Dan Green (R) | Democratic | Likely R |
| FL-27 | Eliott Rodriguez (D) vs. María Elvira Salazar (R) | Democratic | Lean R |
| GA-14 | Shawn Harris (D) vs. Clay Fuller (R) | Democratic | Solid R |
| KY-06 | Zach Dembo (D) vs. Ralph Alvarado (R) | Democratic | Lean R |
| ME-02 | Matthew Dunlap (D) vs. Paul LePage (R) | Democratic | Lean R |
| MN-01 | Jake Johnson (D) vs. Brad Finstad (R) | Democratic | Lean R |
| NV-01 | Dina Titus (D) vs. Carrie Buck (R) | Republican | Likely D |
| NV-02 | Teresa Benitez-Thompson (D) vs. David Flippo (R) | Democratic | Likely R |
| NY-21 | Blake Gendebien (D) vs. Anthony Constantino (R) | Democratic | Lean R |
| SC-01 | Nancy Lacore (D) vs. Jenny Costa Honeycutt (R) | Democratic | Lean R |
| TN-05 | Chaz Molder (D) vs. Charlie Hatcher (R) | Democratic | Solid R |
| TN-09 | Justin Pearson (D) vs. Brent Taylor (R) | Democratic | Solid R |
| TX-23 | Katy Padilla Stout (D) vs. Brandon Herrera (R) | Democratic | Likely R |
| TX-35 | Johnny Garcia (D) vs. Carlos De La Cruz (R) | Democratic | Lean R |
| VA-05 | Tom Perriello (D) vs. John McGuire (R) | Democratic | Likely R |
| VA-06 | Beth Macy (D) vs. Ben Cline (R) | Democratic | Solid R |

## Spot check against fec.gov

Eleven `D_vs_R` races (five competitive, five safe, and NY-21, where the Republican nominee has $0) were compared with each candidate's FEC totals for the 2026 cycle (OpenFEC `/candidate/{id}/totals/`, the same data as the candidate's fec.gov page). Our money is not total receipts, so the table compares like with like: individuals net of refunds, plus PAC and party money net of committee refunds.

| Group | Race | Candidate | Individuals, net of refunds | PAC and party, net of refunds | FEC external | Our file | Difference | Note |
|---|---|---|---|---|---|---|---|---|
| Competitive | AZ-06 | JoAnna Mendoza (D) | $9,218,435.25 | $803,481.09 | $10,021,916.34 | $10,021,916.34 | $0.00 | matches |
| Competitive | AZ-06 | Juan Ciscomani (R) | $2,881,815.32 | $2,023,578.74 | $4,905,394.06 | $4,905,394.06 | $0.00 | matches |
| Competitive | MI-07 | William Lawrence (D) | $3,791,451.93 | $299,850.94 | $4,091,302.87 | $4,091,302.87 | $0.00 | matches |
| Competitive | MI-07 | Tom Barrett (R) | $4,498,317.96 | $1,794,007.89 | $6,292,325.85 | $6,292,325.85 | $0.00 | matches |
| Competitive | ME-02 | Matthew Dunlap (D) | $2,705,276.41 | $212,586.92 | $2,917,863.33 | $2,917,863.33 | $0.00 | matches |
| Competitive | ME-02 | Paul LePage (R) | $1,675,159.57 | $613,812.26 | $2,288,971.83 | $2,288,971.83 | $0.00 | matches |
| Competitive | NV-01 | Dina Titus (D) | $933,201.22 | $1,000,807.97 | $1,934,009.19 | $1,934,009.19 | $0.00 | matches |
| Competitive | NV-01 | Carrie Buck (R) | $1,764,699.60 | $223,250.00 | $1,987,949.60 | $1,987,949.60 | $0.00 | matches |
| Competitive | FL-13 | Leela Gray (D) | $2,464,608.65 | $308,156.08 | $2,772,764.73 | $2,772,764.73 | $0.00 | matches |
| Competitive | FL-13 | Anna Paulina Luna (R) | $2,725,148.07 | $217,500.00 | $2,942,648.07 | $2,942,648.07 | $0.00 | matches |
| Safe | CT-04 | Jim Himes (D) | $541,644.56 | $1,010,500.00 | $1,552,144.56 | $1,552,144.56 | $0.00 | matches |
| Safe | CT-04 | Michael Goldstein (R) | $34,216.32 | $0.00 | $34,216.32 | $34,216.32 | $0.00 | matches |
| Safe | TN-08 | Heidi Kuhn (D) | $107,844.98 | $4,399.00 | $112,243.98 | $112,243.98 | $0.00 | matches |
| Safe | TN-08 | David Kustoff (R) | $1,210,212.15 | $1,169,850.00 | $2,380,062.15 | $2,380,062.15 | $0.00 | matches |
| Safe | NC-09 | Richard Ojeda (D) | $2,860,047.39 | $34,345.75 | $2,894,393.14 | $2,894,393.14 | $0.00 | matches |
| Safe | NC-09 | Richard Hudson (R) | $1,401,676.72 | $1,987,897.28 | $3,389,574.00 | $3,389,574.00 | $0.00 | matches |
| Safe | GA-12 | Ceretta Smith (D) | $40,939.80 | $5,000.00 | $45,939.80 | $45,939.80 | $0.00 | matches |
| Safe | GA-12 | Rick Allen (R) | $625,820.55 | $637,850.00 | $1,263,670.55 | $1,263,670.55 | $0.00 | matches |
| Safe | TX-16 | Veronica Escobar (D) | $553,309.64 | $501,108.43 | $1,054,418.07 | $1,054,418.07 | $0.00 | matches |
| Safe | TX-16 | Adam Bauman (R) | $1,600.00 | $0.00 | $1,600.00 | $1,600.00 | $0.00 | matches |
| Extra | NY-21 | Blake Gendebien (D) | $7,150,959.36 | $207,800.00 | $7,358,759.36 | $7,359,009.36 | $250.00 | gap equals the $250.00 of party committee refunds, which the bulk file's committee refunds field leaves out |
| Extra | NY-21 | Anthony Constantino (R) | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 | matches |

21 of 22 nominees match the fec.gov figure within $1. The one exception is the NY-21 Democrat, whose file figure is $250 above fec.gov. The gap is exactly the $250 of refunds to party committees that fec.gov subtracts and the bulk file's committee refunds field does not, so the file slightly overstates her external money. It does not affect the race. These are the same 22 nominees that were checked against the earlier 2026-10-23 snapshot, where five Democrats (AZ-06, MI-07, TN-08, NC-09, NY-21) were short by $15,010 to $479,798 because their Pre-General reports had not yet reached the bulk file.

## Nominees whose latest report is still before Oct 14

22 funded Democrat-versus-Republican nominees have a latest report that ends before Oct 14 in the 2026-10-24 snapshot. fec.gov shows the same coverage end date for each of them, so the snapshot is not behind for these nominees: they have not filed a later report. Each one's opponent has a later report and more money, and checking the API totals did not change any money leader.

| Race | Nominee | Latest coverage in snapshot | Money in file |
|---|---|---|---|
| CA-08 | Rudy Recile (R) | 2026-09-30 | $10,798.00 |
| CT-03 | Chris Lancia (R) | 2026-06-30 | $13,648.55 |
| DE-00 | Joseph Arminio (R) | 2026-09-30 | $7,431.76 |
| FL-18 | Curtis Gibson (D) | 2026-09-30 | $4,037.00 |
| FL-28 | Phil Ehr (D) | 2026-09-30 | $154,839.54 |
| GA-08 | Kelly Esti (D) | 2026-09-30 | $20,962.90 |
| KY-03 | Maria Rodriquez (R) | 2026-09-30 | $75,078.70 |
| MA-08 | Robert Burke (R) | 2026-09-30 | $25.00 |
| MO-04 | Jordan Herrera (D) | 2026-07-15 | $32,830.32 |
| MO-07 | Missi Hesketh (D) | 2026-07-15 | $50,539.85 |
| MS-04 | Jeffrey Hulum III (D) | 2026-09-30 | $54,378.68 |
| NC-14 | Lakesha Womack (D) | 2026-09-30 | $49,544.01 |
| NE-03 | Becky Stille (D) | 2026-09-30 | $33,290.61 |
| NY-10 | Jennifer Moore (R) | 2026-09-30 | $2,693.46 |
| OH-05 | Brian Shaver (D) | 2026-09-30 | $24,133.91 |
| OK-02 | Brandon Wade (D) | 2026-09-30 | $6,547.79 |
| RI-01 | Kellie Keenan (R) | 2026-09-30 | $7,310.44 |
| SC-02 | Zyon Khalifa (D) | 2026-09-30 | $29,039.07 |
| TX-06 | Danny Minton (D) | 2026-09-30 | $130,079.86 |
| TX-36 | Rhonda Hart (D) | 2026-09-30 | $24,315.62 |
| UT-03 | Kent Udell (D) | 2026-09-30 | $91,265.11 |
| WI-05 | Andrew Beck (D) | 2026-06-30 | $12,987.26 |

## Note added 2026-10-24, after the tag (the CSV is unchanged)

The `cook_rating` column mixes two sources, and the CSV does not say which a row uses. Seats that the Wikipedia Cook ratings table does not list get Solid D or Solid R inferred from PVI (`races.rating_source = 'inferred'` in the database). Counts, from the database:

| Among | Cook's own rating | Inferred from PVI |
|---|---|---|
| 410 `D_vs_R` races | 136 | 274 |
| 389 races where both rules made a call | 115 | 274 |
| 20 races where money and Cook name different parties | 18 | 2 |

The two disagreements with an inferred rating are GA-14 and VA-06 (both inferred Solid R). Read the comparison of the two rules with that in mind: most of the 389 comparisons use a PVI-based rating, not Cook's own call.
