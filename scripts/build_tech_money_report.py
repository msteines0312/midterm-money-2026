"""Build the charts and the numbers file for the tech money report.

Reads one outside spending snapshot from the database and writes everything
the written report in `reports/tech-money.md` relies on:

    reports/figures/network_party_buckets.png
    reports/figures/competitive_vs_safe.png
    reports/figures/primary_vs_general.png
    reports/figures/tech_money_numbers.json
    reports/figures/network_share.png   (only with --share-validated)

The prose in the report is written by hand. Every number in it should match
`tech_money_numbers.json`, so rerunning this script after a new pull shows
exactly which sentences need updating.

Run from the repo root:
    python scripts/build_tech_money_report.py --pulled-at 2026-10-23
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import matplotlib

# Write PNGs without opening a window, so the script also runs on a server
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

# Let this script import from src/ when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.tech_money import (  # noqa: E402
    NETWORK_SPENDING,
    competitiveness,
    network_share,
    network_totals,
    party_buckets,
    primary_vs_general,
    top_races,
)
from src.config import DB_PATH, PROJECT_ROOT  # noqa: E402

FIGURES_DIR = PROJECT_ROOT / "reports" / "figures"

# Colors. Blue and red are the same palette's light-mode steps, checked with a
# colorblind validator so neither party's color is louder than the other's.
# Gray is for spending that has no party.
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"
RED = "#e34948"
GRAY = "#8a8986"
VIOLET = "#6250d6"
ORANGE = "#eb6834"

# Support is a solid fill and opposition is a hatched, lighter fill of the
# same hue, so the two read apart in grayscale and for colorblind readers
# without relying on a red/green contrast.
SOLID = "solid"
HATCHED = "hatched"

PARTY_BUCKETS = [
    ("Supporting Democrats", BLUE, SOLID),
    ("Opposing Democrats", BLUE, HATCHED),
    ("Supporting Republicans", RED, SOLID),
    ("Opposing Republicans", RED, HATCHED),
    ("Other or unknown", GRAY, SOLID),
]
SEAT_TYPES = [
    ("Competitive", ORANGE, SOLID),
    ("Safe", ORANGE, HATCHED),
]
ELECTIONS = [
    ("Primary", VIOLET, SOLID),
    ("General", ORANGE, SOLID),
    ("Other", GRAY, SOLID),
]

# Labels shown under each network's name on the charts
INDUSTRY_LABELS = {"crypto": "crypto", "ai_industry": "AI industry", "ai_safety": "AI safety"}


def open_read_only(db_path):
    """Open the database read-only, so building the report can never change it.

    Parameters
    ----------
    db_path : pathlib.Path

    Returns
    -------
    sqlite3.Connection
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(f"{db_path} not found. Run python -m src.pipeline first.")
    return sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)


def millions(dollars):
    """Format dollars as a short label like "$52.9M"."""
    return f"${dollars / 1e6:.1f}M"


def wide_by_network(table, column, categories, networks):
    """Pivot a long (network, category, total) table into one row per network.

    Networks or categories with no rows get 0, so every chart has the same
    rows in the same order.

    Parameters
    ----------
    table : pandas.DataFrame
        Columns `network`, `column`, `total`.
    column : str
        Name of the category column, such as "bucket".
    categories : list of str
    networks : list of str
        Row order.

    Returns
    -------
    pandas.DataFrame
        Indexed by network, one column per category.
    """
    wide = table.pivot_table(index="network", columns=column, values="total", aggfunc="sum")
    return wide.reindex(index=networks, columns=categories).fillna(0.0)


def race_detail(conn, pulled_at, race_id):
    """Every network row in one race: who spent, for or against whom, and when.

    Parameters
    ----------
    conn : sqlite3.Connection
    pulled_at : str
    race_id : str

    Returns
    -------
    list of dict
        Keys `network`, `candidate_name`, `party`, `election_type`,
        `support_oppose`, `total`, largest first.
    """
    sql = f"""
        SELECT network, candidate_name, party, election_type, support_oppose,
               SUM(total) AS total
        FROM ({NETWORK_SPENDING})
        WHERE race_id = :race_id
        GROUP BY network, candidate_name, party, election_type, support_oppose
        ORDER BY total DESC
    """
    cursor = conn.execute(sql, {"pulled_at": pulled_at, "race_id": race_id})
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor]


def stage_totals(detail_rows):
    """Sum one race's network rows into Primary, General and Other."""
    stages = {"P": "Primary", "G": "General"}
    totals = {name: 0.0 for name, _, _ in ELECTIONS}
    for row in detail_rows:
        totals[stages.get(row["election_type"], "Other")] += row["total"]
    return totals


def collect_numbers(conn, pulled_at):
    """Gather every table the report needs and every number the prose cites.

    Parameters
    ----------
    conn : sqlite3.Connection
    pulled_at : str

    Returns
    -------
    tuple of (dict, dict)
        The JSON-ready numbers, and the wide DataFrames the charts are drawn
        from (keys "totals", "buckets", "seats", "elections").
    """
    totals = network_totals(conn, pulled_at)
    if totals.empty:
        raise ValueError(f"No network spending for {pulled_at}. Check the date.")
    networks = totals["network"].tolist()

    buckets = wide_by_network(party_buckets(conn, pulled_at), "bucket",
                              [name for name, _, _ in PARTY_BUCKETS], networks)
    seats = wide_by_network(competitiveness(conn, pulled_at), "seat_type",
                            [name for name, _, _ in SEAT_TYPES], networks)
    elections = wide_by_network(primary_vs_general(conn, pulled_at), "election",
                                [name for name, _, _ in ELECTIONS], networks)

    # top_races also returns all super PAC spending in each race. It is left
    # out on purpose: next to the network figure it reads as a share of all
    # outside spending, which the report does not show until validation passes.
    races = top_races(conn, pulled_at, n=10)[["race_id", "cook_rating", "network_total"]]

    numbers = {"pulled_at": pulled_at, "networks": {}}
    numbers["combined_total"] = float(totals["total"].sum())
    for row in totals.itertuples():
        net = row.network
        bucket_totals = buckets.loc[net]
        general_total = float(elections.loc[net, "General"])
        rated_general = float(seats.loc[net].sum())
        numbers["networks"][net] = {
            "industry": row.industry,
            "total": float(row.total),
            "n_candidates": int(row.n_candidates),
            "party_buckets": {name: float(v) for name, v in bucket_totals.items()},
            "supporting_total": float(bucket_totals[["Supporting Democrats", "Supporting Republicans"]].sum()
                                      + bucket_totals["Other or unknown"]),
            "opposing_total": float(bucket_totals[["Opposing Democrats", "Opposing Republicans"]].sum()),
            "elections": {name: float(v) for name, v in elections.loc[net].items()},
            "primary_pct_of_network_total": float(elections.loc[net, "Primary"] / row.total * 100),
            "general_seat_types": {name: float(v) for name, v in seats.loc[net].items()},
            # General money in a race with no Cook rating drops out of the
            # competitive versus safe split. Recorded so the report can say so.
            "general_without_rating": general_total - rated_general,
        }
    numbers["top_races"] = [
        {**race, "by_election": stage_totals(race_detail(conn, pulled_at, race["race_id"]))}
        for race in races.to_dict(orient="records")
    ]
    numbers["top_race_detail"] = race_detail(conn, pulled_at, races["race_id"].iloc[0])

    frames = {"totals": totals, "buckets": buckets, "seats": seats, "elections": elections}
    return numbers, frames


def round_floats(value):
    """Round every float in a nested structure to cents, for a readable JSON file."""
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, dict):
        return {key: round_floats(item) for key, item in value.items()}
    if isinstance(value, list):
        return [round_floats(item) for item in value]
    return value


def network_labels(totals):
    """Y-axis labels: the network name with its industry underneath."""
    return [f"{row.network}\n({INDUSTRY_LABELS.get(row.industry, row.industry)})"
            for row in totals.itertuples()]


def lighten(hex_color, amount):
    """Mix a color toward white. `amount` is the share of white, from 0 to 1."""
    rgb = matplotlib.colors.to_rgb(hex_color)
    return tuple(channel + (1 - channel) * amount for channel in rgb)


def segment_style(color, fill):
    """Bar keyword arguments for a solid or hatched segment."""
    if fill == HATCHED:
        return {"facecolor": lighten(color, 0.75), "edgecolor": color, "hatch": "///", "linewidth": 0}
    return {"facecolor": color, "linewidth": 0}


def legend_handles(categories):
    """Legend swatches that match the bar segments exactly."""
    return [Patch(label=name, **segment_style(color, fill)) for name, color, fill in categories]


def draw_stacked_bars(ax, wide, categories, labels):
    """Draw one horizontal stacked bar per network, largest network on top.

    Zero-dollar segments are skipped so they don't leave a sliver. Each
    segment gets a surface-colored outline, which acts as the small gap
    between neighbors instead of a dark border.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
    wide : pandas.DataFrame
        One row per network, one column per category, in dollars.
    categories : list of tuple
        (name, color, fill) for each column, in stacking order.
    labels : list of str
        Y-axis labels, in the same order as `wide`.
    """
    positions = range(len(wide))[::-1]  # first row at the top
    left = [0.0] * len(wide)
    for name, color, fill in categories:
        for i, (pos, value) in enumerate(zip(positions, wide[name])):
            if value <= 0:
                continue
            ax.barh(pos, value, left=left[i], height=0.55, **segment_style(color, fill))
            ax.barh(pos, value, left=left[i], height=0.55, fill=False, edgecolor=SURFACE, linewidth=2)
            left[i] += value

    # Total at the end of each bar, in text color rather than a series color
    for pos, total in zip(positions, left):
        ax.text(total, pos, f"  {millions(total)}", va="center", ha="left",
                fontsize=12, color=TEXT_PRIMARY, fontweight="bold")

    ax.set_yticks(list(positions), labels, fontsize=12, color=TEXT_PRIMARY)
    ax.set_xlim(0, max(left) * 1.18)  # room for the total labels
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"${x / 1e6:.0f}M"))
    style_axes(ax)


def style_axes(ax):
    """Recessive axes: hairline vertical grid, no box, muted tick labels."""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="x", colors=TEXT_SECONDARY, labelsize=11)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, linewidth=1)
    ax.set_axisbelow(True)


def new_figure(title, pulled_at, height=4.6):
    """A figure with a left-aligned title and the pull date as its subtitle."""
    fig, ax = plt.subplots(figsize=(10, height), facecolor=SURFACE)
    fig.subplots_adjust(left=0.2, right=0.97, top=0.72, bottom=0.17)
    fig.text(0.02, 0.95, title, fontsize=15, fontweight="bold", color=TEXT_PRIMARY, va="top")
    fig.text(0.02, 0.95 - 0.38 / height, f"FEC data as of {pulled_at}",
             fontsize=11.5, color=TEXT_SECONDARY, va="top")
    return fig, ax


def add_legend(fig, categories, height):
    """One legend row under the subtitle, so it never covers a bar."""
    fig.legend(handles=legend_handles(categories), loc="upper left", ncol=len(categories),
               bbox_to_anchor=(0.015, 0.95 - 0.68 / height), frameon=False,
               fontsize=11, handlelength=1.6, columnspacing=1.2, labelcolor=TEXT_PRIMARY)


def add_note(fig, text):
    """A small source or method note along the bottom edge."""
    fig.text(0.02, 0.02, text, fontsize=10, color=TEXT_SECONDARY, va="bottom")


def save(fig, name):
    """Write a figure to the figures folder and close it."""
    path = FIGURES_DIR / name
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    print(f"Wrote {path.relative_to(PROJECT_ROOT)}")


def plot_party_buckets(frames, pulled_at):
    """Each network's spending split by candidate party and by support or opposition."""
    height = 4.9
    fig, ax = new_figure("House spending by tech super PAC networks, by party and side", pulled_at, height)
    # Five legend entries don't fit one row at this width, so use three columns
    fig.legend(handles=legend_handles(PARTY_BUCKETS), loc="upper left", ncol=3,
               bbox_to_anchor=(0.015, 0.95 - 0.68 / height), frameon=False,
               fontsize=11, handlelength=1.6, columnspacing=1.2, labelcolor=TEXT_PRIMARY)
    fig.subplots_adjust(top=0.64)
    draw_stacked_bars(ax, frames["buckets"], PARTY_BUCKETS, network_labels(frames["totals"]))
    add_note(fig, "Independent expenditures in 2026 House races, all election stages combined. "
                  "Solid = supporting, hatched = opposing.")
    save(fig, "network_party_buckets.png")


def plot_competitive_vs_safe(frames, pulled_at):
    """General election spending in competitive versus safe seats."""
    height = 4.6
    fig, ax = new_figure("General election spending, competitive versus safe seats", pulled_at, height)
    add_legend(fig, SEAT_TYPES, height)
    draw_stacked_bars(ax, frames["seats"], SEAT_TYPES, network_labels(frames["totals"]))
    add_note(fig, "General election only. Competitive = Cook Toss Up, Lean or Likely. Safe = Solid. "
                  "Races with no Cook rating are left out.")
    save(fig, "competitive_vs_safe.png")


def plot_primary_vs_general(frames, pulled_at):
    """Spending by stage of the election."""
    height = 4.6
    fig, ax = new_figure("House spending by tech super PAC networks, by election", pulled_at, height)
    add_legend(fig, ELECTIONS, height)
    draw_stacked_bars(ax, frames["elections"], ELECTIONS, network_labels(frames["totals"]))
    add_note(fig, "Other = runoffs, special elections and filings coded as other.")
    save(fig, "primary_vs_general.png")


def plot_network_share(conn, pulled_at):
    """Each network's share of all super PAC spending. Only run after validation passes."""
    share = network_share(conn, pulled_at).sort_values("share_of_super_pac_spending")
    fig, ax = new_figure("Share of all House super PAC spending", pulled_at, 4.2)
    ax.barh(share["network"], share["share_of_super_pac_spending"] * 100, height=0.55, color=GRAY)
    for pos, pct in enumerate(share["share_of_super_pac_spending"] * 100):
        ax.text(pct, pos, f"  {pct:.1f}%", va="center", fontsize=12, color=TEXT_PRIMARY)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    style_axes(ax)
    save(fig, "network_share.png")
    return share


def parse_args():
    """Read the snapshot date and whether the share chart is allowed."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pulled-at", required=True, help="Snapshot date, YYYY-MM-DD")
    parser.add_argument("--share-validated", action="store_true",
                        help="Also write network_share.png. Only use once "
                             "scripts/check_outside_spending.py passes for this snapshot.")
    return parser.parse_args()


def main():
    """Build every chart and the numbers file for one snapshot."""
    args = parse_args()
    conn = open_read_only(DB_PATH)
    numbers, frames = collect_numbers(conn, args.pulled_at)

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    plot_party_buckets(frames, args.pulled_at)
    plot_competitive_vs_safe(frames, args.pulled_at)
    plot_primary_vs_general(frames, args.pulled_at)

    # The share needs every super PAC's spending to be right, not just the
    # networks', so it waits for the validation check to pass
    numbers["share_included"] = args.share_validated
    if args.share_validated:
        share = plot_network_share(conn, args.pulled_at)
        numbers["share_of_super_pac_spending"] = dict(
            zip(share["network"], share["share_of_super_pac_spending"].astype(float)))

    path = FIGURES_DIR / "tech_money_numbers.json"
    path.write_text(json.dumps(round_floats(numbers), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path.relative_to(PROJECT_ROOT)}")
    conn.close()


if __name__ == "__main__":
    main()
