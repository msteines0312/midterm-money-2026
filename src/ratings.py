"""Cook Political Report ratings and PVI for 2026 House districts, read from Wikipedia.

Same method as midterm-polling-messaging/src/polling/ratings.py, with one
difference: in 2026 the data lives on two pages.

- The ratings page lists only seats that at least one forecaster considers
  competitive (about 139). It gives Cook's rating for each.
- The main elections page has a table per state with every district's Cook PVI.

A seat missing from the ratings page is safe by that page's own definition,
so it gets "Solid D" or "Solid R" from the sign of its PVI and is marked
`rating_source = "inferred"`. PVI comes from the 2026 page, not older sources,
because several states (including Texas and California) redrew their maps.
"""

import re
import urllib.request

import pandas as pd
from bs4 import BeautifulSoup

from src.config import COOK_RATINGS_PAGE, PVI_PAGE, WIKIPEDIA_DIR
from src.fec.transform import race_id
from src.states import STATE_CODES

USER_AGENT = "midterm-money-research/0.1 (portfolio project)"

# "Alabama 2" or "Alaska at-large"
DISTRICT_LABEL = re.compile(r"^(.+) (at-large|\d+)$")
# "R+7", "D+29", or "EVEN"
PVI_VALUE = re.compile(r"^([DR]\+\d+|EVEN)$")
# Matches "2026 PVI" in the state tables. Missouri's column says "2025 PVI"
# because its new map was struck down in September 2026, so the old lines
# (and their 2025 PVI) are what's on the ballot. The redistricting summary
# table's "New 2026 PVI" column doesn't match, which keeps it out.
PVI_HEADER = re.compile(r"^20\d\d PVI")


def cell_text(cell):
    """Clean text from a table cell: no footnote markers, no non-breaking spaces."""
    text = cell.get_text(" ", strip=True).replace("\xa0", " ")
    return re.sub(r"\[[^\]]*\]", "", text).strip()


def normalize_rating(raw):
    """Map a Wikipedia rating cell onto Cook's own labels.

    Parameters
    ----------
    raw : str
        Rating as shown on Wikipedia, e.g. "Lean D (flip)", "Safe R", "Tossup".

    Returns
    -------
    str
        Cook's wording, e.g. "Lean D", "Solid R", "Toss Up".
    """
    # "(flip)" only says the favored party differs from the incumbent's
    rating = raw.replace("(flip)", "").strip()
    rating = rating.replace("Safe", "Solid")
    return "Toss Up" if rating == "Tossup" else rating


def label_to_race_id(label):
    """Convert a Wikipedia district label to a race_id.

    Parameters
    ----------
    label : str
        e.g. "Arizona 2" or "Alaska at-large".

    Returns
    -------
    str
        e.g. "AZ-02" or "AK-00".

    Raises
    ------
    ValueError
        If the label isn't a district or names an unknown state.
    """
    match = DISTRICT_LABEL.match(label)
    state = STATE_CODES.get(match.group(1).upper()) if match else None
    if state is None:
        raise ValueError(f"Not a recognizable district label: {label!r}")
    district = "00" if match.group(2) == "at-large" else match.group(2)
    return race_id(state, district)


def _rows(table):
    return [[cell_text(c) for c in row.find_all(["th", "td"])] for row in table.find_all("tr")]


def _find_column(header_rows, pattern):
    """Return (header row position, column index) of the first header matching pattern."""
    for pos, headers in enumerate(header_rows):
        for col, header in enumerate(headers):
            if pattern.match(header):
                return pos, col
    return None


def parse_cook_ratings(html):
    """Read Cook's rating for each seat listed on the ratings page.

    Parameters
    ----------
    html : str
        Ratings page HTML.

    Returns
    -------
    pandas.DataFrame
        Columns `race_id` and `cook_rating`.
    """
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table", class_="wikitable"):
        rows = _rows(table)
        # The header is two rows deep, so check the first two
        found = _find_column(rows[:2], re.compile(r"^Cook"))
        if found is None:
            continue
        header_pos, cook_col = found
        records = [
            {"race_id": label_to_race_id(cells[0]), "cook_rating": normalize_rating(cells[cook_col])}
            for cells in rows[header_pos + 1:]
            if len(cells) > cook_col and DISTRICT_LABEL.match(cells[0])
        ]
        return pd.DataFrame(records)
    raise ValueError("No table with a Cook column found")


def parse_pvi_tables(html, required_header=None):
    """Read every district's PVI from the per-state tables on the elections page.

    Parameters
    ----------
    html : str
        Elections page HTML.
    required_header : str, optional
        Only read tables that also have a header starting with this text.
        Past pages need it: the 2024 page's crossover-seat summary tables
        repeat a PVI column, and one lists NY-19 with its
        pre-redraw value. Passing "Candidates" keeps just the per-state tables.

    Returns
    -------
    pandas.DataFrame
        Columns `race_id` and `cook_pvi`, one row per district.
    """
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for table in soup.find_all("table", class_="wikitable"):
        rows = _rows(table)
        found = _find_column(rows[:2], PVI_HEADER)
        if found is None:
            continue
        if required_header and _find_column(rows[:2], re.compile("^" + re.escape(required_header))) is None:
            continue
        header_pos, pvi_col = found
        for cells in rows[header_pos + 1:]:
            # When a district has two incumbents, the second one gets a
            # continuation row with no district label or PVI. Requiring both
            # skips those rows.
            if (
                len(cells) > pvi_col
                and DISTRICT_LABEL.match(cells[0])
                and PVI_VALUE.match(cells[pvi_col])
            ):
                records.append({"race_id": label_to_race_id(cells[0]), "cook_pvi": cells[pvi_col]})

    # Summary tables near the top of the page (such as crossover seats)
    # repeat some districts. Identical repeats are dropped; a disagreement
    # means the page is inconsistent, so stop rather than pick one.
    pvi = pd.DataFrame(records).drop_duplicates()
    conflicts = sorted(pvi.loc[pvi["race_id"].duplicated(), "race_id"])
    if conflicts:
        raise ValueError(f"Districts with conflicting PVI values: {conflicts}")
    return pvi.reset_index(drop=True)


def _inferred_rating(pvi):
    """Solid rating for a seat no forecaster lists as competitive."""
    if pvi.startswith("D+"):
        return "Solid D"
    if pvi.startswith("R+"):
        return "Solid R"
    return None  # an EVEN seat that nobody rates would be strange, so don't guess


def build_races(pvi, ratings):
    """Combine PVI for every district with Cook ratings for the listed seats.

    Parameters
    ----------
    pvi : pandas.DataFrame
        Output of `parse_pvi_tables`.
    ratings : pandas.DataFrame
        Output of `parse_cook_ratings`.

    Returns
    -------
    list of dict
        Rows for the `races` table.

    Raises
    ------
    ValueError
        If a rated seat has no PVI row, which would mean the two pages
        disagree and the join would silently drop a competitive race.
    """
    missing = sorted(set(ratings["race_id"]) - set(pvi["race_id"]))
    if missing:
        raise ValueError(f"Rated seats with no PVI: {missing}")

    listed = dict(zip(ratings["race_id"], ratings["cook_rating"]))
    races = []
    for rid, cook_pvi in zip(pvi["race_id"], pvi["cook_pvi"]):
        state, district = rid.split("-")
        races.append({
            "race_id": rid,
            "state": state,
            "district": district,
            "cook_rating": listed.get(rid, _inferred_rating(cook_pvi)),
            "cook_pvi": cook_pvi,
            "rating_source": "cook" if rid in listed else "inferred",
        })
    return races


def download_page(page):
    """Save one pinned Wikipedia revision to data/raw/wikipedia/, if not already saved.

    Parameters
    ----------
    page : tuple of (str, int)
        Page title and revision ID.

    Returns
    -------
    pathlib.Path
        Location of the saved HTML.
    """
    title, revision = page
    path = WIKIPEDIA_DIR / f"{title}_{revision}.html"
    if not path.exists():
        WIKIPEDIA_DIR.mkdir(parents=True, exist_ok=True)
        url = f"https://en.wikipedia.org/w/index.php?title={title}&oldid={revision}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())
    return path


def load_races():
    """Download (if needed) and combine both pages into `races` rows.

    Returns
    -------
    list of dict
    """
    ratings_html = download_page(COOK_RATINGS_PAGE).read_text(encoding="utf-8")
    pvi_html = download_page(PVI_PAGE).read_text(encoding="utf-8")
    return build_races(parse_pvi_tables(pvi_html), parse_cook_ratings(ratings_html))
