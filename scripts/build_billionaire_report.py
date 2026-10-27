"""Build the charts and the numbers file for the billionaire money report.

Reads donors, committee totals, and the outside spending snapshot from the
database, the sourced CSVs in data/manual/, and the frozen general election
predictions (for the list of November nominees). Writes everything that
`reports/billionaire-money.md` relies on:

    reports/figures/billionaire_giving.png
    reports/figures/billionaire_house_share.png
    reports/figures/billionaire_primary_win_rates.png
    reports/figures/billionaire_money_numbers.json

The prose in the report is written by hand. Every number in it should match
`billionaire_money_numbers.json`, and tests/test_billionaire_report_numbers.py
checks that each string under `cited` appears in the report as written.

Run from the repo root:
    python scripts/build_billionaire_report.py
"""

import csv
import json
import sys
import textwrap
from pathlib import Path

import pandas as pd

# Let this script import from src/ and from the tech report's chart helpers
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_tech_money_report import (  # noqa: E402
    AQUA,
    FIGURES_DIR,
    GRID,
    SOLID,
    HATCHED,
    TEXT_PRIMARY,
    VIOLET,
    add_legend,
    add_note,
    draw_stacked_bars,
    millions,
    new_figure,
    open_read_only,
    round_floats,
    save,
    style_axes,
)
from src.analysis.billionaires import (  # noqa: E402
    all_office_expenditures,
    billionaire_backed,
    concentration,
    could_not_test,
    house_share,
    household_giving,
    lean,
    primary_outcomes,
    primary_support,
    reconcile,
    win_rates,
)
from src.config import DB_PATH, PROJECT_ROOT  # noqa: E402
from src.manual import load_billionaires, load_donor_entities, load_org_donors_reviewed  # noqa: E402

REPORT_PATH = PROJECT_ROOT / "reports" / "billionaire-money.md"
NUMBERS_PATH = FIGURES_DIR / "billionaire_money_numbers.json"
# This file's own name, so the tests can scan it for em dashes
BUILDER_PATH_NAME = Path(__file__).name
PREDICTIONS_PATH = PROJECT_ROOT / "reports" / "predictions" / "2026-general-simple.csv"

# Spending snapshot the House numbers use, and the day donors and committee
# totals were pulled. Both are stamped on every chart.
SPENDING_DATE = "2026-10-24"
DONOR_DATE = "2026-10-26"
# How many billionaires the person charts show
TOP_PEOPLE = 15
# A PAC at or above this share from one person is "near" backed from 35%
NEAR_FLOOR = 0.35


def money(dollars):
    """Format dollars as a short label such as "$1.17B", "$52.9M", or "$850K"."""
    if abs(dollars) >= 1e9:
        return f"${dollars / 1e9:.2f}B"
    if abs(dollars) >= 1e6:
        return millions(dollars)
    return f"${dollars / 1e3:,.0f}K"


def percent(fraction):
    """Format a 0 to 1 fraction as a whole percent such as "42%"."""
    return f"{fraction * 100:.0f}%"


def load_nominees(path=PREDICTIONS_PATH):
    """Read the November nominees from the frozen general election predictions.

    Parameters
    ----------
    path : pathlib.Path, optional

    Returns
    -------
    tuple of (set of str, list of dict)
        The nominees' FEC candidate IDs, and one dict per nominee with
        `race_id` and `name` for matching when a filing has no ID.
    """
    ids, nominees = set(), []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for side in ("dem", "rep"):
                if row[f"{side}_name"]:
                    nominees.append({"race_id": row["race_id"], "name": row[f"{side}_name"], "party": side})
                if row[f"{side}_candidate_id"]:
                    ids.add(row[f"{side}_candidate_id"])
    return ids, nominees


def committee_names(conn):
    """Committee ID to name, from the committees table."""
    return dict(conn.execute("SELECT committee_id, name FROM committees"))


def lean_bucket(dem_share):
    """Which side of 50 percent a billionaire's House spending leaned."""
    if pd.isna(dem_share):
        return "no House spending"
    if dem_share > 0.5:
        return "leaned Democratic"
    if dem_share < 0.5:
        return "leaned Republican"
    return "even"


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
    names = committee_names(conn)
    billionaires, entities = load_billionaires(), load_donor_entities()
    giving = household_giving(conn, billionaires, entities)
    all_ie = all_office_expenditures(SPENDING_DATE)

    shares = concentration(giving, conn)
    candidates = shares[shares["share"] >= 0.2]["committee_id"].unique()
    reconciled = reconcile(conn, sorted(candidates))
    labeled = billionaire_backed(shares, reconciled)
    backed = labeled[labeled["status"] == "backed"]

    by_person = (
        giving.groupby("person", as_index=False)[["direct", "via_entities", "total"]].sum()
        .merge(house_share(giving, conn, SPENDING_DATE, all_ie), on="person")
        .merge(lean(giving, conn, SPENDING_DATE, all_ie), on="person")
        .sort_values("total", ascending=False)
        .reset_index(drop=True)
    )
    by_person["lean"] = by_person["dem_share"].map(lean_bucket)

    nominee_ids, nominees = load_nominees()
    support = primary_support(conn, backed, SPENDING_DATE)
    outcomes = primary_outcomes(support, nominee_ids, nominees)
    rates = win_rates(outcomes)

    labeled = labeled.assign(pac=labeled["committee_id"].map(names))
    labeled = labeled.merge(reconciled[["committee_id", "diff_pct", "receipts"]], on="committee_id", how="left")
    review = outcomes[(outcomes["outcome"] == "review") | (outcomes["outcome_for_pac"] == "review")]
    by_name = outcomes[outcomes["matched_by"] == "name"]

    untested = could_not_test(shares, reconciled).assign(pac=lambda frame: frame["committee_id"].map(names))
    # Money from organizations the review could not tie to a person, by category
    reviewed = pd.DataFrame(load_org_donors_reviewed())
    unattributed = reviewed[reviewed["category"] != "attributed"].groupby("category")["total"].sum()
    lean_money = by_person.groupby("lean")["total"].sum().to_dict()
    top = by_person.head(TOP_PEOPLE)
    numbers = {
        "data_dates": {"donors": DONOR_DATE, "spending": SPENDING_DATE},
        "giving": {
            "households": int(len(by_person)),
            "total": float(by_person["total"].sum()),
            "direct": float(by_person["direct"].sum()),
            "via_entities": float(by_person["via_entities"].sum()),
            "top": top[["person", "total", "direct", "via_entities", "house_dollars", "house_pct",
                        "other_or_unspent", "dem_helping", "rep_helping", "dem_share", "lean"]]
            .to_dict("records"),
        },
        # The one backed PAC with a large donor and no independent expenditures at all
        "democracy_pac_ie": float(conn.execute(
            "SELECT independent_expenditures FROM pac_totals WHERE committee_id = 'C00693382' "
            "ORDER BY pulled_at DESC LIMIT 1").fetchone()[0] or 0.0),
        "house": {
            "dollars": float(by_person["house_dollars"].sum()),
            "pct_of_giving": float(by_person["house_dollars"].sum() / by_person["total"].sum()),
        },
        "lean_money": {key: float(value) for key, value in lean_money.items()},
        "unattributed_org_money": {key: float(value) for key, value in unattributed.items()},
        # Every PAC where any donor holds 20% or more was reconciled against its totals
        "reconciliation": {"tested": int(len(reconciled)), "reconciled": int(reconciled["reconciled"].sum())},
        "pacs": {
            # Counted by PAC, not by pair. Two donors can each hold exactly half of one PAC.
            "counts": labeled.groupby("status")["committee_id"].nunique().to_dict(),
            "backed_donors": int((labeled["status"] == "backed").sum()),
            "could_not_test": untested[["pac", "committee_id", "person", "share", "shortfall", "upper_bound"]].to_dict("records"),
            "list": labeled.sort_values(["status", "share"], ascending=[True, False])[
                ["pac", "committee_id", "person", "share", "status", "diff_pct", "receipts"]
            ].to_dict("records"),
        },
        "primary": {
            **rates,
            "review": review[["committee_id", "race_id", "candidate_name", "support_oppose", "total"]].to_dict("records"),
            "matched_by_name": by_name[["race_id", "candidate_name", "outcome"]].to_dict("records"),
        },
    }
    numbers["cited"] = cited_strings(numbers)
    frames = {"top": top, "rates": rates, "names": names}
    return round_floats(numbers), frames


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
    giving, house, pooled = numbers["giving"], numbers["house"], numbers["primary"]["pooled"]
    counts = numbers["pacs"]["counts"]
    cited = {
        "households": str(giving["households"]),
        "total_giving": money(giving["total"]),
        "direct_giving": money(giving["direct"]),
        "entity_giving": money(giving["via_entities"]),
        "house_dollars": money(house["dollars"]),
        "house_pct": percent(house["pct_of_giving"]),
        "backed_count": str(counts.get("backed", 0)),
        "near_count": str(counts.get("near", 0)),
        "unreconciled_count": str(counts.get("unreconciled", 0)),
        "could_not_test_count": str(len(numbers["pacs"]["could_not_test"])),
        "other_nonprofit_money": money(numbers["unattributed_org_money"]["other_nonprofit"]),
        "party_nonprofit_money": money(numbers["unattributed_org_money"]["party_aligned_nonprofit"]),
        "pacs_tested": str(numbers["reconciliation"]["tested"]),
        "pacs_reconciled": str(numbers["reconciliation"]["reconciled"]),
        "primary_won": str(pooled["won"]),
        "primary_lost": str(pooled["lost"]),
        "primary_review": str(pooled["review"]),
    }
    if pooled["rate"] is not None:
        cited["primary_rate"] = percent(pooled["rate"])
    for row in giving["top"][:5]:
        cited[f"top_{row['person']}"] = f"{row['person']} ({money(row['total'])}"
    return cited


def plot_giving(frames):
    """Super PAC giving by billionaire, split into own-name and through-entity money."""
    top = frames["top"]
    categories = [("Own name", VIOLET, SOLID), ("Through a sourced organization", VIOLET, HATCHED)]
    wide = top.set_index("person")[["direct", "via_entities"]].rename(
        columns={"direct": "Own name", "via_entities": "Through a sourced organization"})
    # Refunds can make a net figure negative. Bars start at zero.
    wide = wide.clip(lower=0.0)
    height = 6.6
    fig, ax = new_figure(f"Super PAC giving by the {len(top)} biggest billionaire donors, 2026 cycle", DONOR_DATE, height)
    fig.subplots_adjust(top=0.78, left=0.24)
    add_legend(fig, categories, height)
    draw_stacked_bars(ax, wide, categories, list(wide.index))
    add_note(fig, "Net of refunds. Organization money counts only where a public source ties it to the person.")
    save(fig, "billionaire_giving.png")


def plot_house_share(frames):
    """How much of each donor's giving is estimated to have reached House races."""
    top = frames["top"]
    other = "Everything else (other offices, transfers, or unspent)"
    categories = [("House races (estimate)", AQUA, SOLID), (other, AQUA, HATCHED)]
    # The second segment is whatever is not House spending, so the two segments
    # add up to the donor's total giving shown in the giving chart
    wide = pd.DataFrame({
        "House races (estimate)": top["house_dollars"].to_numpy(),
        other: (top["total"] - top["house_dollars"]).to_numpy(),
    }, index=top["person"]).clip(lower=0.0)
    height = 6.6
    fig, ax = new_figure("Estimated share of each donor's giving that reached House races", SPENDING_DATE, height)
    fig.subplots_adjust(top=0.78, left=0.24)
    add_legend(fig, categories, height)
    draw_stacked_bars(ax, wide, categories, list(wide.index))
    add_note(fig, "Each PAC's House spending is split in proportion to each donor's share of its receipts.")
    save(fig, "billionaire_house_share.png")


def plot_primary_rates(frames, names):
    """Primary win rate per billionaire-backed PAC, with the counts behind each rate."""
    rates = frames["rates"]
    rows = [("All backed PACs combined", rates["pooled"])]
    # Title case and wrapped, because PAC names are long and uppercase in the data
    rows += [(textwrap.fill(names.get(pac, pac).title().replace(" Pac", " PAC").replace(" For ", " for "), 26), counts) for pac, counts in rates["by_pac"].items()]
    rows = [(label, counts) for label, counts in rows if counts["rate"] is not None]
    height = max(3.6, 1.7 + 0.5 * len(rows))
    fig, ax = new_figure("Primary candidates backed by billionaire-funded PACs who became nominees", SPENDING_DATE, height)
    fig.subplots_adjust(left=0.27, top=0.76)
    positions = range(len(rows))[::-1]
    for pos, (label, counts) in zip(positions, rows):
        ax.barh(pos, counts["rate"], height=0.5, color=AQUA, linewidth=0)
        ax.text(counts["rate"], pos, f"  {percent(counts['rate'])}  ({counts['won']} of {counts['won'] + counts['lost']})",
                va="center", fontsize=11.5, color=TEXT_PRIMARY, fontweight="bold")
    ax.set_yticks(list(positions), [label for label, _ in rows], fontsize=11, color=TEXT_PRIMARY)
    ax.set_xlim(0, 1.25)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    ax.axvline(0.5, color=GRID, linewidth=1)
    style_axes(ax)
    add_note(fig, "Candidates the PAC spent $10,000 or more on in the primary. PACs tend to back likely winners.")
    save(fig, "billionaire_primary_win_rates.png")


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
    plot_giving(frames)
    plot_house_share(frames)
    plot_primary_rates(frames, frames["names"])
    NUMBERS_PATH.write_text(json.dumps(numbers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {NUMBERS_PATH.relative_to(PROJECT_ROOT)}")
    conn.close()


if __name__ == "__main__":
    main()
