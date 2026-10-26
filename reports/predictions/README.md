# 2026 House general election predictions, simple version

This folder holds the first of two sets of pre-election predictions for the 2026 U.S. House general elections. Each race gets two plain rules and no model: which nominee has raised more outside money (the **money leader**), and which party the Cook Political Report rates ahead (the **Cook favorite**). The file puts them side by side so a reader can see where they agree and where they do not. It is committed before election day so it can be scored against results afterward.

File: [`2026-general-simple.csv`](2026-general-simple.csv). Built by [`scripts/build_simple_predictions.py`](../../scripts/build_simple_predictions.py).

The second set, a model trained on the 2022 and 2024 House generals, is described in [Model predictions](#model-predictions) at the end of this file.

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

## Model predictions

File: [`2026-general-model.csv`](2026-general-model.csv), with every number behind this section in [`model-evaluation.json`](model-evaluation.json). Both are built by [`scripts/build_model_predictions.py`](../../scripts/build_model_predictions.py) from committed code and the local database, and are tagged `pre-election-model`. Like the simple file, they are never edited after the tag.

The model is a logistic regression ([`src/predict/model.py`](../../src/predict/model.py)) that gives the probability that the Democrat wins a Democrat versus Republican race from three inputs:

- **Money share:** the Democrat's share of the two major nominees' external money.
- **Incumbency:** +1 when the Democrat is the sitting member, -1 when the Republican is, 0 for an open seat (or two members running against each other).
- **PVI:** the district's Cook PVI with Democratic leans positive (D+5 is 5, R+5 is -5).

Each input is standardized before fitting, and scikit-learn's default settings are used with no tuning.

### Training data

House generals in 2022 and 2024, one row per race with exactly one Democratic and one Republican nominee.

- **Results:** 2022 from the FEC's official "Federal Elections 2022" publication. The FEC had not published a 2024 edition, so 2024 comes from the per-state tables of Wikipedia's 2024 House elections page at a pinned revision from after certification (ID 1267103610).
- **Money:** each campaign's cycle-to-date external money (individuals net of refunds, plus PAC and party money net of committee refunds, never the candidate's own money) on its latest report ending on or before the pre-general cutoff, from the OpenFEC reports API. End-of-cycle totals are not used, because money raised after election day would leak the result into the input.
- **PVI and Cook ratings:** each cycle's pinned Wikipedia revision from just before election day.
- **Incumbency:** 2022 from the incumbent marker in the FEC results. 2024 from the Member column of the Wikipedia page, matched to nominees by last name and first initial.

| | 2022 | 2024 |
|---|---|---|
| Democrat versus Republican races | 395 | 392 |
| Left out: a major nominee has no money record | 37 | 49 |
| Left out: a third-party candidate outraised a major nominee | 8 | 5 |
| Used for training | 350 | 338 |
| Two members running against each other (incumbency set to 0) | 2 (FL-02, TX-34) | 0 |

Every excluded race is listed with names and money in the JSON under `exclusions`.

### How well it did on races it had not seen

Each cycle was held out in turn: fit on 2022 and scored on 2024, then the reverse. The money rule and the Cook favorite need no training and are scored on the same races. Abstentions (a Cook Toss Up, an exact 50% money share) lower coverage but are not counted as misses. "Pooled" combines both held-out cycles.

**All races (pooled, 688):**

| Predictor | Races called | Coverage | Accuracy |
|---|---|---|---|
| Model | 688 | 100% | 96.4% (Brier score 0.027) |
| Model without money (incumbency and PVI only) | 688 | 100% | 95.9% (Brier score 0.031) |
| Money rule | 688 | 100% | 92.4% |
| Cook favorite | 631 | 91.7% | 99.7% |
| Cook favorite, seats Cook actually listed | 174 of 231 | 75.3% | 98.9% |

By held-out cycle, the model's accuracy was 97.0% on 2024 (338 races) and 95.7% on 2022 (350 races).

Overall accuracy mostly counts safe seats, so the races that matter are the competitive ones: those Cook rated Toss Up, Lean, or Likely in that cycle.

**Competitive races (pooled, 154), with bootstrap 95% intervals:**

| Predictor | Races called | Coverage | Accuracy |
|---|---|---|---|
| Model | 154 | 100% | 83.8% [77.9%, 89.6%] (Brier score 0.119) |
| Model without money | 154 | 100% | 81.8% (Brier score 0.131) |
| Money rule | 154 | 100% | 73.4% [66.2%, 80.5%] |
| Cook favorite | 97 | 63.0% | 97.9% [94.8%, 100.0%] |

By held-out cycle, the model's competitive accuracy was 85.1% on 2024 (67 races) and 82.8% on 2022 (87 races).

Cook calls fewer races, so the fairest comparison uses the 97 competitive races where all three made a call (every one rated Lean or Likely, since Cook abstains on Toss Ups). There the model was right on 93.8%, the money rule on 79.4%, and Cook on 97.9%. A paired bootstrap resamples those same races for every predictor in each draw (1,000 draws, fixed seed) and gives intervals for the differences:

| Difference on the shared 97 races | Estimate | 95% interval |
|---|---|---|
| Model minus money rule | +14.4 points | [+6.2, +23.7] |
| Model minus Cook | -4.1 points | [-9.3, 0.0] |

Only the first interval excludes 0, so the model's edge over the money rule is the one difference this sample supports. The gap between the model and Cook reaches 0 at the upper end, so it is not treated as a clear difference.

**Calibration (pooled, all races).** When the model says 70%, the Democrat should win about 70% of the time.

| Predicted probability | Races | Average prediction | Democrats actually won |
|---|---|---|---|
| 0.0 to 0.2 | 329 | 0.019 | 0.006 |
| 0.2 to 0.4 | 18 | 0.275 | 0.389 |
| 0.4 to 0.6 | 14 | 0.477 | 0.500 |
| 0.6 to 0.8 | 17 | 0.710 | 0.824 |
| 0.8 to 1.0 | 310 | 0.971 | 0.974 |

The middle bins hold under 20 races each, so their gaps are noisy. Per-cycle and competitive-only tables are in the JSON.

### What the coefficients say

Fit on all 688 training races, in log-odds of a Democratic win:

| Input | Coefficient | Per standard deviation |
|---|---|---|
| Intercept | -2.31 | -0.32 |
| Money share (0 to 1) | 4.21 | 1.67 |
| Incumbency (+1 D, -1 R) | 1.23 | 1.13 |
| PVI (per point) | 0.253 | 3.67 |

In plain words:

- All three point toward the Democrat as expected: more money share, a Democratic incumbent, and a bluer district each raise the Democrat's chances.
- **PVI matters most.** One standard deviation of PVI moves the log-odds about twice as much as one standard deviation of money share. Each PVI point multiplies the Democrat's odds by about 1.29.
- **Incumbency** multiplies the odds by about 3.4 for the incumbent's party, compared with an open seat.
- **Money share** multiplies the odds by about 1.52 for every 10 points of share. In an open seat with an EVEN PVI, going from 45% to 55% of the money moves the Democrat's chance from 39.8% to 50.2%, about 10 points. At the training medians (open seat, R+1) the same change moves it from 33.9% to 43.9%.
- Adding money to a model that already knows incumbency and PVI lowered the held-out Brier score on competitive races from 0.131 to 0.119.

### This is prediction, not cause

Money flows to candidates who were already likely to win: donors back strong candidates and incumbents, and strong candidates raise more. A positive money coefficient says that money share carries information about the result beyond incumbency and PVI. It does not say that spending moved votes, and the model cannot tell how much it would.

### The 2026 predictions

The model is fit on all 688 training races and applied to every 2026 race in the simple file that is `D_vs_R`, has `confirmed` nominees, and has no third-party candidate outraising a major nominee. That is 400 races: the 410 `D_vs_R` races minus 10 where a third party outraised a major nominee (AK-00, CO-01, CO-06, FL-18, IL-04, MT-02, NE-03, NY-07, NY-15, VA-03).

- **Money** is the same 2026-10-24 snapshot as the simple file.
- **PVI** is the 2026 Cook PVI from the `races` table, converted the same way as in training.
- **Incumbency** is read from the Member column of the pinned 2026 nominees page (revision 1381568365) and matched to nominees by last name and first initial, the same rule used for 2024. One match was corrected by hand: TX-22 Republican nominee Trever Nehls is the twin brother of the retiring member Troy Nehls, and the name rule cannot tell them apart, so he is not counted as the incumbent. Result: 164 Democratic incumbents, 168 Republican incumbents, 68 open seats, and no races with two members.

**Columns:**

| Column | Meaning |
|---|---|
| `race_id` | State and district, such as `WI-03`. |
| `dem_name`, `rep_name` | The Democratic and Republican nominees. |
| `dem_money_share` | The Democrat's share of the two nominees' external money. |
| `incumbency` | +1 Democratic incumbent, -1 Republican incumbent, 0 otherwise. |
| `dem_pvi` | Cook PVI with Democratic leans positive. |
| `dem_win_probability` | The model's probability that the Democrat wins. |
| `money_leader_party`, `cook_favorite_party` | Copied from the simple file for comparison. |
| `money_record_missing` | `True` when a major nominee has no FEC match or no money row in the snapshot (counted as $0). Training left such races out, so these predictions go beyond what the model saw. |

**Checks run before committing:**

- No probability is exactly 0 or 1. The range is 0.000008 to 0.999998.
- Seats rated Solid R (162) all get a Democratic probability of 0.20 or less. Seats rated Solid D (160) all get 0.67 or more, and all but CA-01 get 0.88 or more. CA-01 (0.67) is a D+7 seat where the Republican, James Gallagher, is the sitting member.
- All three coefficients are positive.
- 38 races have `money_record_missing = True`. In every one the missing nominee is the underdog in a Solid seat (36 Republicans in Solid D seats and 2 Democrats, OH-02 and TX-12, in Solid R seats), and the predictions sit at the expected extreme.
- The model calls the Democrat in 191 of 400 races. The probabilities add up to 193.4 expected Democratic seats among these 400.

**How the model's calls compare with Cook:**

| Cook rating | Model calls Democrat | Model calls Republican |
|---|---|---|
| Solid D | 160 | 0 |
| Likely D | 17 | 0 |
| Lean D | 7 | 5 |
| Toss Up | 6 | 15 |
| Lean R | 0 | 13 |
| Likely R | 1 | 14 |
| Solid R | 0 | 162 |

**Races where the model and Cook name different parties (6):**

| Race | Nominees | Model's Democratic probability | Cook rating |
|---|---|---|---|
| FL-09 | Darren Soto (D) vs. Dan Green (R) | 0.66 | Likely R |
| IA-01 | Christina Bohannan (D) vs. Mariannette Miller-Meeks (R) | 0.10 | Lean D |
| IA-03 | Sarah Trone Garriott (D) vs. Zach Nunn (R) | 0.24 | Lean D |
| NJ-07 | Rebecca Bennett (D) vs. Thomas Kean Jr. (R) | 0.32 | Lean D |
| PA-07 | Bob Brooks (D) vs. Ryan Mackenzie (R) | 0.22 | Lean D |
| PA-10 | Janelle Stelson (D) vs. Scott Perry (R) | 0.15 | Lean D |

In each of these the model sides with the incumbent's party. Cook does not call Toss Ups, so they are not in this table, but the model's 21 Toss Up calls follow the same pattern: in every Toss Up with an incumbent, the model favors the incumbent's party.

**Races where the model and the money rule name different parties (38):**

| Race | Nominees | Model's Democratic probability | Money leader | Cook rating |
|---|---|---|---|---|
| AL-02 | Shomari Figures (D) vs. Rhett Marques (R) | 0.39 | Democratic | Likely R |
| AZ-06 | JoAnna Mendoza (D) vs. Juan Ciscomani (R) | 0.33 | Democratic | Toss Up |
| CA-22 | Randy Villegas (D) vs. David Valadao (R) | 0.28 | Democratic | Toss Up |
| CO-04 | Eileen Laubacher (D) vs. Lauren Boebert (R) | 0.13 | Democratic | Solid R |
| CO-05 | Jessica Killin (D) vs. Jeff Crank (R) | 0.12 | Democratic | Lean R |
| CO-08 | Manny Rutinel (D) vs. Gabe Evans (R) | 0.30 | Democratic | Toss Up |
| FL-07 | Bale Dalton (D) vs. Ryan Elijah (R) | 0.43 | Democratic | Likely R |
| FL-27 | Eliott Rodriguez (D) vs. María Elvira Salazar (R) | 0.06 | Democratic | Lean R |
| GA-14 | Shawn Harris (D) vs. Clay Fuller (R) | 0.01 | Democratic | Solid R |
| IA-01 | Christina Bohannan (D) vs. Mariannette Miller-Meeks (R) | 0.10 | Democratic | Lean D |
| IA-02 | Lindsay James (D) vs. Joe Mitchell (R) | 0.31 | Democratic | Toss Up |
| IA-03 | Sarah Trone Garriott (D) vs. Zach Nunn (R) | 0.24 | Democratic | Lean D |
| KY-06 | Zach Dembo (D) vs. Ralph Alvarado (R) | 0.17 | Democratic | Lean R |
| ME-02 | Matthew Dunlap (D) vs. Paul LePage (R) | 0.28 | Democratic | Lean R |
| MI-04 | Sean McCann (D) vs. Bill Huizenga (R) | 0.11 | Democratic | Toss Up |
| MI-10 | Christina Hines (D) vs. Mike Bouchard Jr. (R) | 0.39 | Democratic | Toss Up |
| MN-01 | Jake Johnson (D) vs. Brad Finstad (R) | 0.07 | Democratic | Lean R |
| MT-01 | Sam Forstag (D) vs. Aaron Flint (R) | 0.27 | Democratic | Toss Up |
| NJ-07 | Rebecca Bennett (D) vs. Thomas Kean Jr. (R) | 0.32 | Democratic | Lean D |
| NV-01 | Dina Titus (D) vs. Carrie Buck (R) | 0.82 | Republican | Likely D |
| NV-02 | Teresa Benitez-Thompson (D) vs. David Flippo (R) | 0.13 | Democratic | Likely R |
| NY-17 | Cait Conley (D) vs. Mike Lawler (R) | 0.33 | Democratic | Toss Up |
| NY-21 | Blake Gendebien (D) vs. Anthony Constantino (R) | 0.35 | Democratic | Lean R |
| OH-07 | Brian Poindexter (D) vs. Max Miller (R) | 0.12 | Democratic | Toss Up |
| PA-07 | Bob Brooks (D) vs. Ryan Mackenzie (R) | 0.22 | Democratic | Lean D |
| PA-08 | Paige Cognetti (D) vs. Rob Bresnahan (R) | 0.13 | Democratic | Toss Up |
| PA-10 | Janelle Stelson (D) vs. Scott Perry (R) | 0.15 | Democratic | Lean D |
| SC-01 | Nancy Lacore (D) vs. Jenny Costa Honeycutt (R) | 0.38 | Democratic | Lean R |
| TN-05 | Chaz Molder (D) vs. Charlie Hatcher (R) | 0.12 | Democratic | Solid R |
| TN-09 | Justin Pearson (D) vs. Brent Taylor (R) | 0.20 | Democratic | Solid R |
| TX-15 | Bobby Pulido (D) vs. Monica De La Cruz (R) | 0.04 | Democratic | Toss Up |
| TX-23 | Katy Padilla Stout (D) vs. Brandon Herrera (R) | 0.33 | Democratic | Likely R |
| TX-35 | Johnny Garcia (D) vs. Carlos De La Cruz (R) | 0.28 | Democratic | Lean R |
| VA-01 | Shannon Taylor (D) vs. Rob Wittman (R) | 0.12 | Democratic | Toss Up |
| VA-02 | Elaine Luria (D) vs. Jen Kiggans (R) | 0.23 | Democratic | Toss Up |
| VA-05 | Tom Perriello (D) vs. John McGuire (R) | 0.09 | Democratic | Likely R |
| VA-06 | Beth Macy (D) vs. Ben Cline (R) | 0.02 | Democratic | Solid R |
| WI-03 | Rebecca Cooke (D) vs. Derrick Van Orden (R) | 0.17 | Democratic | Toss Up |

In 37 of the 38, Democrats lead on money and the model still favors the Republican, usually because the Republican is the incumbent, the district leans Republican, or both.

**Incumbency compared with the simple file.** The simple file's `incumbent_party` came from the FEC's incumbent flag, while the model uses the Member column of the nominees page, as training did for 2024. They differ in 11 races, in every case because the FEC flag marks no incumbent while the page lists the nominee as the sitting member (several won special elections or moved districts after redistricting):

| Race | Incumbent on the nominees page |
|---|---|
| CA-01 | James Gallagher (R) |
| CA-31 | Gil Cisneros (D) |
| FL-01 | Jimmy Patronis (R) |
| FL-06 | Randy Fine (R) |
| IN-03 | Marlin Stutzman (R) |
| MD-04 | Glenn Ivey (D) |
| NY-04 | Laura Gillen (D) |
| TX-03 | Keith Self (R) |
| TX-18 | Christian Menefee (D) |
| TX-37 | Greg Casar (D) |
| VA-05 | John McGuire (R) |

### Known limitations

- **No term for the national mood.** The model learns from two cycles and has no input for the national environment of a given year. Its intercept reflects 2022 and 2024, so if 2026 favors one party more than those years did, the model will not see it. This may explain why it sides with Republican incumbents in Lean D seats where Cook does not.
- **Money windows differ slightly.** Training money is cycle-to-date, and FEC cycles restart the day after the previous general election, so 2022 and 2024 money includes the November and December after the prior election. The 2026 bulk file starts on Jan 1, 2025, so 2026 money leaves out November and December 2024. Both nominees in a race are measured the same way, so the effect on money share should be small.
- **2024 results come from Wikipedia**, at a pinned revision from after certification, not from an official FEC publication.
- **Cook's coverage includes PVI-inferred Solid seats.** Seats the Wikipedia Cook table does not list are rated Solid D or Solid R from PVI, in training and in 2026. Inferred Solid ratings are almost always right, which lifts Cook's overall accuracy. The competitive comparisons use only Cook's own ratings.
- **The bootstrap pools both cycles.** Intervals resample races from 2022 and 2024 together and treat races as independent. Races in the same year share a national mood, so the true uncertainty is probably wider than shown.
- **Races outside the training rules.** The 38 races with `money_record_missing = True` count the missing nominee as $0, a case training never included.
