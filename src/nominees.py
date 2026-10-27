"""November House nominees, read from the 2026 elections page on Wikipedia.

The per-state tables (the same ones `ratings.parse_pvi_tables` reads) have a
"Candidates" column. Each nominee shows as "▌ Name (Party)", where the bar is
a colored party stripe. The next step matches these names to FEC candidates by
race and last name, so names are cleaned down to the name alone.
"""

import re

from bs4 import BeautifulSoup

from src.config import NOMINEES_PAGE
from src.ratings import (
    DISTRICT_LABEL,
    PVI_HEADER,
    _find_column,
    _rows,
    cell_text,
    download_page,
    label_to_race_id,
)

# The party stripe that starts every nominee
PARTY_BAR = "▌"
# Parenthetical notes that are not a party, e.g. "(incumbent)"
NOTE = re.compile(r"\s*\((?:incumbent|write-in|withdrew|withdrawn)[^)]*\)", re.IGNORECASE)
# "Name (Party)": the party is the last parenthetical, and names never contain one
NOMINEE = re.compile(r"^(?P<name>[^()]+?)\s*\((?P<party>[^()]+)\)$")
# Wording that marks a race as not settled. The pinned revision has no candidate
# cell with any of these (checked against all 435 races), so nothing is
# "unconfirmed" today. Markers expected from the page's conventions:
#   "runoff"       a runoff still to be held
#   "TBD"          a nominee still to be named
#   "withdr..."    "withdrew" or "withdrawn" next to a name
UNCONFIRMED = re.compile(r"runoff|\bTBD\b|withdr", re.IGNORECASE)


def _candidates_header_present(rows):
    """True when one of the two header rows has a column starting with "Candidates"."""
    return any(header.startswith("Candidates") for row in rows[:2] for header in row)


def split_nominees(cell):
    """Split a candidates cell into one text per nominee.

    Splitting on the party bar, not on `<li>` tags, because Wikipedia leaves
    some nominees outside the list markup (Tennessee 4 has one).

    Parameters
    ----------
    cell : bs4.element.Tag
        The "Candidates" table cell.

    Returns
    -------
    list of str
        e.g. ["Shomari Figures (Democratic)", "Rhett Marques (Republican)"].
    """
    parts = cell_text(cell).split(PARTY_BAR)
    return [part.strip() for part in parts if part.strip()]


def parse_nominee(text):
    """Turn "Shomari Figures (Democratic)" into a name and a party.

    Parameters
    ----------
    text : str
        One nominee, without the party bar.

    Returns
    -------
    tuple of (str, str)
        Name and party.

    Raises
    ------
    ValueError
        If the text isn't "Name (Party)", so a layout change fails loudly.
    """
    match = NOMINEE.match(NOTE.sub("", text).strip())
    if match is None:
        raise ValueError(f"Not a recognizable nominee: {text!r}")
    return match.group("name").strip(), match.group("party").strip()


def parse_nominees(html):
    """Read every nominee from the per-state tables on the elections page.

    Parameters
    ----------
    html : str
        Elections page HTML.

    Returns
    -------
    list of dict
        One dict per nominee with `race_id`, `name`, `party`, and `status`
        ("confirmed" or "unconfirmed").

    Raises
    ------
    ValueError
        If a district appears in two tables, or a nominee can't be read.
    """
    soup = BeautifulSoup(html, "html.parser")
    nominees = []
    seen_races = set()
    for table in soup.find_all("table", class_="wikitable"):
        rows = _rows(table)
        # PVI marks the per-state tables. The special-election and delegate
        # tables also have a Candidates column but are not November races.
        if _find_column(rows[:2], PVI_HEADER) is None or not _candidates_header_present(rows):
            continue
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if not cells or not DISTRICT_LABEL.match(cell_text(cells[0])):
                continue
            # Rowspans shift the middle columns around, but Candidates is
            # always the last cell of a district's first row.
            race = label_to_race_id(cell_text(cells[0]))
            if race in seen_races:
                raise ValueError(f"District listed twice: {race}")
            seen_races.add(race)
            status = "unconfirmed" if UNCONFIRMED.search(cell_text(cells[-1])) else "confirmed"
            for text in split_nominees(cells[-1]):
                name, party = parse_nominee(text)
                nominees.append({"race_id": race, "name": name, "party": party, "status": status})
    return nominees


def _member_name(cell):
    """A sitting member's name from the Member cell, or None for an empty seat.

    The hCard name is used when there is one, so a note such as "Redistricted
    from the 1st district" is left out. A new or vacant seat has no member.
    """
    card = cell.find(class_="fn")
    if card:
        return cell_text(card)
    text = cell_text(cell)
    return None if not text or text.startswith(("None", "Vacant")) else text


def parse_incumbents(html):
    """Read each district's sitting members from the per-state tables.

    This is the 2026 counterpart of the Member column that
    `history_results.wiki_districts` reads for 2024, so the model's incumbency
    input is built the same way in training and prediction.

    Parameters
    ----------
    html : str
        Elections page HTML.

    Returns
    -------
    dict of str to list of str
        race_id to the members listed for that district. Usually one name,
        two when redistricting put two members in one seat, and an empty list
        for a new seat.
    """
    soup = BeautifulSoup(html, "html.parser")
    incumbents = {}
    current = None
    for table in soup.find_all("table", class_="wikitable"):
        rows = _rows(table)
        # Same test as parse_nominees: PVI plus Candidates marks a state table
        if _find_column(rows[:2], PVI_HEADER) is None or not _candidates_header_present(rows):
            continue
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if not cells or row.find("th", colspan=True) or cell_text(cells[0]) in ("Location", ""):
                continue
            if DISTRICT_LABEL.match(cell_text(cells[0])):
                # District, PVI, then Member
                current = incumbents.setdefault(label_to_race_id(cell_text(cells[0])), [])
                cells = cells[2:]
            elif current is None:
                continue
            # A second member's continuation row starts with their Member cell
            name = _member_name(cells[0])
            if name:
                current.append(name)
    return incumbents


def load_nominees():
    """Download (if needed) the pinned page and parse its nominees.

    Returns
    -------
    list of dict
        Output of `parse_nominees`.
    """
    return parse_nominees(download_page(NOMINEES_PAGE).read_text(encoding="utf-8"))
