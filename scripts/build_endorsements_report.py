"""Build the charts and the numbers file for the endorsements report.

Reads the sourced endorsements and primary dates in data/manual/, the
candidates and their fundraising from the database, and the frozen general
election predictions (for the list of November nominees). Writes everything
that `reports/endorsements.md` relies on:

    reports/figures/endorsements_win_rates.png
    reports/figures/endorsements_baseline.png
    reports/figures/endorsements_favorites.png
    reports/figures/endorsements_super_pacs.png
    reports/figures/endorsements_numbers.json

The prose in the report is written by hand. Every number in it should match
`endorsements_numbers.json`, and tests/test_endorsements_report_numbers.py
checks that each string under `cited` appears in the report as written.

Run from the repo root:
    python scripts/build_endorsements_report.py
"""

import json
import re
import sys
from pathlib import Path

import pandas as pd

# Let this script import from src/ and from the other reports' helpers
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_billionaire_report import load_nominees, percent  # noqa: E402
from build_tech_money_report import (  # noqa: E402
    FIGURES_DIR,
    GRAY,
    HATCHED,
    SOLID,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    VIOLET,
    add_legend,
    add_note,
    new_figure,
    open_read_only,
    round_floats,
    save,
    style_axes,
)
from src.analysis.endorsements import (  # noqa: E402
    NOT_ON_PRIMARY_BALLOT,
    backing_outcomes,
    backing_rates_by_party,
    baseline_rates,
    classify_primary,
    endorsement_outcomes,
    endorsement_win_rates,
    excluded_counts,
    favorite_check,
    load_primary_dates,
    super_pac_backing,
)
from src.config import DB_PATH, PROJECT_ROOT  # noqa: E402
from src.endorsements_match import SIDE_PARTY  # noqa: E402
from src.manual import load_endorsements, load_endorsers  # noqa: E402

REPORT_PATH = PROJECT_ROOT / "reports" / "endorsements.md"
NUMBERS_PATH = FIGURES_DIR / "endorsements_numbers.json"
# This file's own name, so the tests can scan it for em dashes
BUILDER_PATH_NAME = Path(__file__).name

# The day the endorsement lists were read. Primaries after it are pending.
AS_OF = "2026-10-27"
# The outside spending snapshot used for super PAC backing, the same one the
# billionaire section uses
SPENDING_DATE = "2026-10-24"
# A super PAC is listed by name when it backed at least this many decided
# candidates in contested primaries
TOP_PAC_MIN = 8
PARTY_LABELS = {"REP": "Republicans", "DEM": "Democrats"}
# The contested-primary proxy's hand check (see classify_primary): of 15
# random races checked against Wikipedia, 11 could be judged and 9 agreed
PROXY_CHECK = {"checked": 15, "judged": 11, "agreed": 9}

# Contested strata in chart order, with their labels
STRATA = [("incumbent", "Incumbent"), ("open_seat", "Open seat"), ("challenger", "Challenger"),
          ("all_contested", "All contested")]
# Strata where the all-candidates baseline is a fair comparison. The
# incumbent baseline is not: the database cannot tell a member who lost a
# primary from one who retired or ran for Senate or governor, so every
# departure reads as a loss. The pooled contested row includes incumbents.
BASELINE_STRATA = [("open_seat", "Open seat"), ("challenger", "Challenger")]


def source_says(source_outcome):
    """Turn Ballotpedia's outcome text into won, lost, withdrew, or "" when it gives none."""
    if not source_outcome:
        return ""
    if source_outcome == NOT_ON_PRIMARY_BALLOT:
        return "withdrew"
    # "Not on the ballot general" means the candidate won the primary and left later
    if source_outcome.startswith("Won") or source_outcome == "Not on the ballot general":
        return "won"
    return "lost"


def source_check(outcomes, endorsements):
    """Compare each scored outcome with the source's own result, where it gives one.

    Ballotpedia records a result for every Trump endorsement, which is an
    independent check on the nominee-based scoring.

    Returns
    -------
    dict
        compared, agreed, and the rows that disagree.
    """
    sources = pd.DataFrame(endorsements)[["endorser", "candidate_id", "source_outcome"]]
    frame = outcomes.merge(sources, on=["endorser", "candidate_id"])
    frame = frame[(frame["source_outcome"] != "") & (frame["outcome"] != "pending")]
    said = frame["source_outcome"].map(source_says)
    disagree = frame[said != frame["outcome"]]
    return {
        "compared": int(len(frame)),
        "agreed": int((said == frame["outcome"]).sum()),
        "disagree": disagree[["endorser", "race_id", "name", "outcome", "source_outcome"]].to_dict("records"),
    }


def nominee_rates(outcomes):
    """Win rates with withdrawals counted as not becoming the nominee.

    The all-candidates baseline cannot see who withdrew before the primary,
    so it counts them as not nominated. Scoring the endorsed side the same
    way keeps the comparison like for like.
    """
    return endorsement_win_rates(outcomes.assign(outcome=outcomes["outcome"].replace("withdrew", "lost")))


def slug(endorser):
    """A short key for an endorser, such as "club_for_growth_pac"."""
    return re.sub(r"[^a-z0-9]+", "_", endorser.lower()).strip("_")


def endorser_summary(outcomes, rates, as_nominee, excluded, endorser):
    """Counts, rates, and the favorite check for one endorser."""
    mine = outcomes[outcomes["endorser"] == endorser]

    def records(frame):
        return frame[frame["endorser"] == endorser].drop(columns="endorser").to_dict("records")

    skipped = excluded[excluded["endorser"] == endorser].drop(columns="endorser")
    return {
        "endorsements": int(len(mine)),
        "timing": mine["timing"].value_counts().to_dict(),
        "outcome": mine["outcome"].value_counts().to_dict(),
        "excluded": {k: int(v) for k, v in skipped.iloc[0].items()} if len(skipped) else {},
        "rates": records(rates),
        "nominee_rates": records(as_nominee),
        "favorite": favorite_check(mine),
    }


def collect(conn):
    """Run the whole analysis and return the numbers and the tables behind the charts.

    Parameters
    ----------
    conn : sqlite3.Connection
        Read-only connection to the project database.

    Returns
    -------
    tuple of (dict, dict)
        The numbers (JSON-ready, including a `cited` dict of the exact
        strings the report quotes) and the DataFrames the charts draw.
    """
    endorsers = load_endorsers()
    endorsements = load_endorsements()
    primary_dates = load_primary_dates()
    nominee_ids, nominees = load_nominees()
    fec_date = conn.execute("SELECT MAX(pulled_at) FROM candidate_totals").fetchone()[0][:10]

    # Every candidate, so a last-name match can be checked against the nominee's own filing
    classified_all = classify_primary(conn)
    outcomes = endorsement_outcomes(endorsements, primary_dates, classified_all, nominee_ids, nominees, AS_OF)
    rates = endorsement_win_rates(outcomes)
    as_nominee = nominee_rates(outcomes)
    excluded = excluded_counts(outcomes)
    # The baseline leaves out every endorsed candidate, so it is the group they are compared with
    endorsed_ids = {row["candidate_id"] for row in endorsements}
    baseline = baseline_rates(classified_all, primary_dates, nominee_ids, nominees, AS_OF, exclude_ids=endorsed_ids)

    side = {row["endorser"]: row["side"] for row in endorsers}
    numbers = {
        "data_dates": {"endorsement_lists": AS_OF, "fec_totals": fec_date},
        "endorsers": {
            row["endorser"]: {"side": row["side"], "list_kind": row["list_kind"],
                              **endorser_summary(outcomes, rates, as_nominee, excluded, row["endorser"])}
            for row in endorsers
        },
        "baseline": baseline.to_dict("records"),
        "source_check": source_check(outcomes, endorsements),
        "contested_proxy": PROXY_CHECK,
        "hedged": outcomes[outcomes["hedged"]][["endorser", "race_id", "name", "timing", "outcome"]].to_dict("records"),
        "withdrew": outcomes[outcomes["outcome"] == "withdrew"][["endorser", "race_id", "name"]].to_dict("records"),
        "lost": outcomes[(outcomes["outcome"] == "lost") & (outcomes["timing"] == "before") & ~outcomes["hedged"]][
            ["endorser", "race_id", "name", "status", "contested", "top_fundraiser"]].to_dict("records"),
        "review": outcomes[outcomes["outcome"] == "review"][["endorser", "race_id", "name"]].to_dict("records"),
    }
    numbers["super_pacs"], pac_frames = super_pac_numbers(conn, classified_all, primary_dates, nominee_ids, nominees)
    numbers["cited"] = cited_strings(numbers)
    frames = {"rates": rates, "nominee_rates": as_nominee, "baseline": baseline, "side": side,
              "outcomes": outcomes, "fec_date": fec_date, **pac_frames}
    return round_floats(numbers), frames


def super_pac_numbers(conn, classified_all, primary_dates, nominee_ids, nominees):
    """Score super PAC primary spending as a form of endorsement.

    Returns
    -------
    tuple of (dict, dict)
        The numbers for the JSON, and the frames the super PAC chart and
        the favorites chart draw.
    """
    backing, no_id = super_pac_backing(conn, SPENDING_DATE)
    known = set(classified_all["candidate_id"])
    outcomes = backing_outcomes(backing, classified_all, primary_dates, nominee_ids, nominees, AS_OF)
    by_party = backing_rates_by_party(outcomes)
    # Compared with funded candidates no super PAC spent $10,000 to support
    baseline = baseline_rates(classified_all, primary_dates, nominee_ids, nominees, AS_OF,
                              exclude_ids=set(outcomes["candidate_id"]))
    by_pac = endorsement_win_rates(outcomes)
    by_pac = by_pac[by_pac["stratum"] == "all_contested"].assign(decided=lambda f: f["won"] + f["lost"])
    top = by_pac[by_pac["decided"] >= TOP_PAC_MIN].sort_values(["decided", "endorser"], ascending=[False, True])
    numbers = {
        "spending_date": SPENDING_DATE,
        "pacs": int(backing["committee_id"].nunique()),
        "candidates": int(backing["candidate_id"].nunique()),
        "pairs": int(len(backing)),
        "no_candidate_id": no_id,
        "not_in_candidates": int((~backing["candidate_id"].isin(known)).sum()),
        "hedged": int(outcomes["hedged"].sum()),
        "pending": int((outcomes["outcome"] == "pending").sum()),
        "rates": by_party.to_dict("records"),
        "baseline": baseline.to_dict("records"),
        "favorite": favorite_check(outcomes.drop_duplicates("candidate_id")),
        "top_pacs": top[["endorser", "won", "lost", "rate", "low", "high"]].to_dict("records"),
    }
    return numbers, {"pac_rates": by_party, "pac_baseline": baseline, "pac_outcomes": outcomes}


def rate_text(row):
    """A rate with its counts, as the report writes it: "94% (76 of 81)"."""
    return f"{percent(row['rate'])} ({row['won']} of {row['won'] + row['lost']})"


def cited_strings(numbers):
    """The exact text the report uses for each headline number.

    Parameters
    ----------
    numbers : dict
        The numbers from `collect`, before `cited` is added.

    Returns
    -------
    dict
        Name to the string the prose must contain.
    """
    cited = {}
    for endorser, summary in numbers["endorsers"].items():
        if not summary["endorsements"]:
            continue  # an endorser whose list is not built yet has nothing to cite
        key = slug(endorser)
        cited[f"{key}_endorsements"] = str(summary["endorsements"])
        for row in summary["rates"]:
            if row["rate"] is not None:
                cited[f"{key}_{row['stratum']}"] = rate_text(row)
        for row in summary["nominee_rates"]:
            if row["stratum"] in dict(BASELINE_STRATA) and row["rate"] is not None:
                cited[f"{key}_{row['stratum']}_as_nominee"] = rate_text(row)
        for reason in ("withdrew", "after", "hedged", "pending"):
            if summary["excluded"].get(reason):
                cited[f"{key}_{reason}"] = str(summary["excluded"][reason])
        favorite = summary["favorite"]
        if favorite["n"]:
            cited[f"{key}_top_share"] = percent(favorite["share_top_fundraiser"])
            for group in ("if_top", "if_not_top"):
                if favorite[f"win_rate_{group}"] is not None:
                    cited[f"{key}_win_{group}"] = percent(favorite[f"win_rate_{group}"])
    for row in numbers["baseline"]:
        if row["stratum"] in dict(BASELINE_STRATA) and row["rate"] is not None:
            cited[f"baseline_{row['party'].lower()}_{row['stratum']}"] = rate_text(row)
    pacs = numbers["super_pacs"]
    for key in ("pacs", "candidates", "pairs"):
        cited[f"super_pac_{key}"] = str(pacs[key])
    for row in pacs["rates"]:
        if row["stratum"] in ("all_contested", *dict(BASELINE_STRATA)) and row["rate"] is not None:
            cited[f"super_pac_{row['party'].lower()}_{row['stratum']}"] = rate_text(row)
    for row in pacs["baseline"]:
        if row["stratum"] in dict(BASELINE_STRATA) and row["rate"] is not None:
            cited[f"super_pac_baseline_{row['party'].lower()}_{row['stratum']}"] = rate_text(row)
    favorite = pacs["favorite"]
    cited["super_pac_top_share"] = percent(favorite["share_top_fundraiser"])
    cited["super_pac_win_if_top"] = percent(favorite["win_rate_if_top"])
    cited["super_pac_win_if_not_top"] = percent(favorite["win_rate_if_not_top"])
    for row in pacs["top_pacs"]:
        cited[f"super_pac_top_{slug(row['endorser'])}"] = f"{row['won']} of {row['won'] + row['lost']}"
    check = numbers["source_check"]
    cited["source_agreed"] = f"{check['agreed']} of {check['compared']}"
    proxy = numbers["contested_proxy"]
    cited["proxy_agreed"] = f"{proxy['agreed']} of {proxy['judged']}"
    return cited


def interval_rows(ax, rows, color, offset=0.0):
    """Draw a dot and its 95% interval for each (position, rate row) pair."""
    for pos, row in rows:
        ax.plot([row["low"], row["high"]], [pos + offset] * 2, color=color, linewidth=2, solid_capstyle="round")
        ax.plot(row["rate"], pos + offset, "o", color=color, markersize=8, markeredgecolor="white", markeredgewidth=2)


def percent_axis(ax, n_rows):
    """A 0 to 100 percent x axis with room on the right for the count labels."""
    ax.set_xlim(0, 1.32)
    ax.set_ylim(-0.7, n_rows - 0.3)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    style_axes(ax)


def plot_win_rates(frames):
    """Each endorser's primary win rate by stratum, with its 95% interval."""
    rates, side = frames["rates"], frames["side"]
    rows = []
    for endorser in side:
        for stratum, label in STRATA:
            match = rates[(rates["endorser"] == endorser) & (rates["stratum"] == stratum)]
            if len(match) and match.iloc[0]["rate"] is not None:
                rows.append((f"{endorser}: {label.lower()}", match.iloc[0]))

    height = max(4.2, 2.0 + 0.42 * len(rows))
    fig, ax = new_figure("Endorsed candidates who won contested House primaries", frames["fec_date"], height)
    fig.subplots_adjust(left=0.33, top=1 - 1.0 / height, bottom=0.6 / height)
    positions = list(range(len(rows)))[::-1]
    interval_rows(ax, [(pos, row) for pos, (_, row) in zip(positions, rows)], VIOLET)
    for pos, (_, row) in zip(positions, rows):
        ax.text(1.03, pos, rate_text(row), va="center", fontsize=10.5, color=TEXT_PRIMARY)
    ax.set_yticks(positions, [label for label, _ in rows], fontsize=10.5, color=TEXT_PRIMARY)
    percent_axis(ax, len(rows))
    add_note(fig, f"Endorsed before the primary (lists as of {AS_OF}). Lines are 95% intervals. "
                  "Contested: 2+ same-party candidates raised $10,000.")
    save(fig, "endorsements_win_rates.png")


def plot_baseline(frames):
    """Endorsed candidates against funded same-party candidates who were not endorsed."""
    as_nominee, baseline, side = frames["nominee_rates"], frames["baseline"], frames["side"]
    base = {(row["party"], row["stratum"]): row for _, row in baseline.iterrows()}
    rows = []
    for endorser in side:
        for stratum, label in BASELINE_STRATA:
            match = as_nominee[(as_nominee["endorser"] == endorser) & (as_nominee["stratum"] == stratum)]
            other = base.get((SIDE_PARTY[side[endorser]], stratum))
            if len(match) and match.iloc[0]["rate"] is not None and other is not None:
                rows.append((f"{endorser}: {label.lower()}", match.iloc[0], other))

    categories = [("Endorsed before the primary", VIOLET, SOLID),
                  ("Funded same-party candidates not endorsed", GRAY, SOLID)]
    height = max(4.2, 2.2 + 0.6 * len(rows))
    fig, ax = new_figure("Endorsed candidates against funded candidates who were not endorsed", frames["fec_date"], height)
    fig.subplots_adjust(left=0.33, top=1 - 1.25 / height, bottom=0.6 / height)
    add_legend(fig, categories, height)
    positions = list(range(len(rows)))[::-1]
    interval_rows(ax, [(pos, row) for pos, (_, row, _) in zip(positions, rows)], VIOLET, offset=0.15)
    interval_rows(ax, [(pos, other) for pos, (_, _, other) in zip(positions, rows)], GRAY, offset=-0.15)
    for pos, (_, row, other) in zip(positions, rows):
        ax.text(1.03, pos + 0.15, rate_text(row), va="center", fontsize=10.5, color=TEXT_PRIMARY)
        ax.text(1.03, pos - 0.15, rate_text(other), va="center", fontsize=10.5, color=TEXT_SECONDARY)
    ax.set_yticks(positions, [label for label, _, _ in rows], fontsize=10.5, color=TEXT_PRIMARY)
    percent_axis(ax, len(rows))
    add_note(fig, "Share who became the nominee, contested primaries. Withdrawals count as not nominated on both sides.")
    save(fig, "endorsements_baseline.png")


def plot_super_pacs(frames):
    """Candidates super PACs spent to support, against funded candidates with no such support."""
    rates, baseline = frames["pac_rates"], frames["pac_baseline"]
    base = {(row["party"], row["stratum"]): row for _, row in baseline.iterrows()}
    rows = []
    for party, party_label in PARTY_LABELS.items():
        for stratum, label in BASELINE_STRATA:
            match = rates[(rates["party"] == party) & (rates["stratum"] == stratum)]
            if len(match) and match.iloc[0]["rate"] is not None:
                rows.append((f"Backing {party_label}: {label.lower()}", match.iloc[0], base.get((party, stratum))))

    categories = [("Super PAC spent $10,000+ to support them", VIOLET, SOLID),
                  ("Funded same-party candidates with no such support", GRAY, SOLID)]
    height = max(4.2, 2.2 + 0.6 * len(rows))
    fig, ax = new_figure("Super PAC-backed candidates who became the nominee, contested primaries",
                         frames["fec_date"], height)
    fig.subplots_adjust(left=0.33, top=1 - 1.25 / height, bottom=0.6 / height)
    add_legend(fig, categories, height)
    positions = list(range(len(rows)))[::-1]
    interval_rows(ax, [(pos, row) for pos, (_, row, _) in zip(positions, rows)], VIOLET, offset=0.15)
    interval_rows(ax, [(pos, other) for pos, (_, _, other) in zip(positions, rows) if other is not None], GRAY,
                  offset=-0.15)
    for pos, (_, row, other) in zip(positions, rows):
        ax.text(1.03, pos + 0.15, rate_text(row), va="center", fontsize=10.5, color=TEXT_PRIMARY)
        if other is not None:
            ax.text(1.03, pos - 0.15, rate_text(other), va="center", fontsize=10.5, color=TEXT_SECONDARY)
    ax.set_yticks(positions, [label for label, _, _ in rows], fontsize=10.5, color=TEXT_PRIMARY)
    percent_axis(ax, len(rows))
    add_note(fig, f"Primary and runoff independent expenditures as of {SPENDING_DATE}. Lines are 95% intervals.")
    save(fig, "endorsements_super_pacs.png")


def plot_favorites(frames):
    """Win rate of endorsed contested candidates, split by whether they led their party in money."""
    outcomes, side = frames["outcomes"], frames["side"]
    rows = []
    for endorser in side:
        check = favorite_check(outcomes[outcomes["endorser"] == endorser])
        if check["n"]:
            rows.append((endorser, check))
    # Super PAC backing, pooled, each candidate once
    pac_check = favorite_check(frames["pac_outcomes"].drop_duplicates("candidate_id"))
    if pac_check["n"]:
        rows.append(("Super PAC backing", pac_check))

    categories = [("Top fundraiser of their party in the race", VIOLET, SOLID),
                  ("Not the top fundraiser", VIOLET, HATCHED)]
    height = max(3.8, 2.0 + 0.9 * len(rows))
    fig, ax = new_figure("Endorsed candidates' win rate, by whether they already led in money", frames["fec_date"], height)
    fig.subplots_adjust(left=0.24, top=1 - 1.25 / height, bottom=0.6 / height)
    add_legend(fig, categories, height)
    positions = [2 * i for i in range(len(rows))][::-1]
    for pos, (endorser, check) in zip(positions, rows):
        n_top = round(check["share_top_fundraiser"] * check["n"])
        bars = [(pos + 0.4, check["win_rate_if_top"], n_top, SOLID),
                (pos - 0.4, check["win_rate_if_not_top"], check["n"] - n_top, HATCHED)]
        for y, rate, count, fill in bars:
            if rate is None:
                continue
            ax.barh(y, rate, height=0.7, color=VIOLET if fill == SOLID else "white", edgecolor=VIOLET,
                    hatch="////" if fill == HATCHED else None, linewidth=1.2)
            ax.text(rate, y, f"  {percent(rate)} ({round(rate * count)} of {count})", va="center",
                    fontsize=10.5, color=TEXT_PRIMARY)
    ax.set_yticks(positions, [endorser for endorser, _ in rows], fontsize=11, color=TEXT_PRIMARY)
    ax.set_xlim(0, 1.25)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    style_axes(ax)
    add_note(fig, "Contested primaries only, endorsements made before the primary. Money is external contributions.")
    save(fig, "endorsements_favorites.png")


def build(conn=None):
    """Compute the numbers without writing any files, for the tests.

    Parameters
    ----------
    conn : sqlite3.Connection, optional
        Defaults to a read-only connection to the project database.

    Returns
    -------
    tuple of (dict, dict)
        As `collect`.
    """
    return collect(conn or open_read_only(DB_PATH))


def main():
    """Build every chart and the numbers file."""
    conn = open_read_only(DB_PATH)
    numbers, frames = collect(conn)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    plot_win_rates(frames)
    plot_baseline(frames)
    plot_super_pacs(frames)
    plot_favorites(frames)
    NUMBERS_PATH.write_text(json.dumps(numbers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {NUMBERS_PATH.relative_to(PROJECT_ROOT)}")
    conn.close()


if __name__ == "__main__":
    main()
