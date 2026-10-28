"""Parse endorsement list pages and match each name to an FEC candidate.

Each tracked endorser publishes its list in a different format, so there is
one small parser per format, all returning the same row shape. Matching then
ties each House row to a 2026 FEC candidate ID. Anything that does not match
cleanly goes to a review list instead of being guessed, because a wrong match
would credit an endorsement to someone else.
"""

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from src.predict.simple import _last_name_matches, _normalize
from src.states import STATE_CODES

# Endorser side to the party code in the candidates table
SIDE_PARTY = {"R": "REP", "D": "DEM"}
# FEC party codes that count as each party. Minnesota Democrats file as the
# Democratic-Farmer-Labor Party (DFL).
PARTY_CODES = {"REP": ("REP",), "DEM": ("DEM", "DFL")}

TRUTH_SOCIAL_POST = re.compile(r"truthsocial\.com/@realDonaldTrump/posts/(\d+)")


def truth_social_date(url):
    """Read the posting date from a Truth Social post URL.

    Truth Social runs on Mastodon, whose post IDs put the creation time (in
    milliseconds since 1970) in their top 48 bits. Shifting the ID right by
    16 bits recovers it, so the date comes from the cited post itself.

    Parameters
    ----------
    url : str

    Returns
    -------
    str
        The UTC date as YYYY-MM-DD, or "" if the URL is not a Truth Social post.
    """
    match = TRUTH_SOCIAL_POST.search(url or "")
    if not match:
        return ""
    milliseconds = int(match.group(1)) >> 16
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).date().isoformat()


def _row(name, office, state="", district="", date="", source_url="", **extra):
    """Build one parsed row in the shape every parser returns."""
    return {
        "name": name, "office": office, "state": state, "district": district,
        "date": date, "source_url": source_url, **extra,
    }


# "U.S. House Alabama District 1", "U.S. House Alaska At-large District", or
# either one followed by "(special)" for a special election
BALLOTPEDIA_OFFICE = re.compile(r"U\.S\. House (.+?) (?:District (\d+)|At-large District)( \(special\))?$")


def _parse_office(text):
    """Split a Ballotpedia office cell into state, district, and a special flag.

    Returns
    -------
    tuple of (str, str, bool)
        State code, two-digit district ("00" for at-large), and whether the
        race is a special election. State and district are "" if the text
        does not parse.
    """
    match = BALLOTPEDIA_OFFICE.match(text)
    if not match:
        return "", "", False
    state = STATE_CODES.get(match.group(1).upper(), "")
    district = f"{int(match.group(2)):02d}" if match.group(2) else "00"
    return state, district, bool(match.group(3))


def _parse_ballotpedia_trump(html):
    """Read Ballotpedia's 2026 U.S. House table of Trump endorsements.

    The page holds a table per office and year. Only the one titled
    "U.S. House endorsements by Donald Trump, 2026" is read, so every row is
    a House row. A row can cite two posts (one for the primary, one for the
    general), and the earliest post date is kept.
    """
    soup = BeautifulSoup(html, "html.parser")
    title = "U.S. House endorsements by Donald Trump, 2026"
    table = next((t for t in soup.find_all("table") if t.find("th") and t.find("th").get_text(" ", strip=True) == title), None)
    if table is None:
        return []

    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 5:
            continue  # the title and column header rows
        sources = [a["href"] for a in cells[0].find_all("a") if a.get_text(strip=True).lower().startswith("source")]
        dates = sorted(d for d in (truth_social_date(url) for url in sources) if d)
        earliest = next((url for url in sources if truth_social_date(url) == dates[0]), "") if dates else ""
        state, district, special = _parse_office(cells[2].get_text(" ", strip=True))
        rows.append(_row(
            name=cells[0].find("a").get_text(strip=True),
            office="house",
            state=state,
            district=district,
            date=dates[0] if dates else "",
            source_url=earliest or (sources[0] if sources else ""),
            all_dates=dates,
            special=special,
            status=cells[1].get_text(" ", strip=True),
            endorsement_type=cells[3].get_text(" ", strip=True),
            outcome=cells[4].get_text(" ", strip=True),
        ))
    return rows


# Club for Growth headings end in a code like (MI-07), (AK-AL), (GA-SEN),
# (TN-GOV), or (OH-AG). The part after the state names the office.
CFG_CODE = re.compile(r"\(\s*([A-Z]{2})-([A-Z0-9]+)\s*\)\s*$")


def _parse_club_for_growth(html):
    """Read the Club for Growth PAC endorsed-candidates page."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for heading in soup.find_all("h3"):
        code = CFG_CODE.search(heading.get_text(" ", strip=True))
        if not code:
            continue  # a section heading like "U.S. Senate"
        state, seat = code.groups()
        name = heading.get_text(" ", strip=True)[: code.start()].strip()
        if seat.isdigit() or seat == "AL":
            rows.append(_row(name, "house", state, "00" if seat == "AL" else f"{int(seat):02d}"))
        else:
            office = {"SEN": "senate", "GOV": "governor"}.get(seat, "other")
            rows.append(_row(name, office, state))
    return rows


def _parse_justice_democrats(html):
    """Read the Justice Democrats candidates page.

    Each card shows a name and a district such as "CA-07" or "IL-9". The
    page lists House candidates only. The section ("Upcoming Elections" or
    "Current Congressmembers") is kept for the notes.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    section = ""
    for heading in soup.find_all("h1", class_=["cand-card__sect-hed", "cand-card__hed"]):
        if "cand-card__sect-hed" in heading["class"]:
            section = heading.get_text(" ", strip=True)
            continue
        sub = heading.find_next("h2", class_="cand-card__sub")
        seat = re.match(r"([A-Z]{2})-(\d+|AL)$", sub.get_text(strip=True)) if sub else None
        if not seat:
            continue
        district = "00" if seat.group(2) == "AL" else f"{int(seat.group(2)):02d}"
        rows.append(_row(heading.get_text(" ", strip=True), "house", seat.group(1), district, section=section))
    return rows


PARSERS = {
    "ballotpedia_trump": _parse_ballotpedia_trump,
    "club_for_growth": _parse_club_for_growth,
    "justice_democrats": _parse_justice_democrats,
}


def parse_endorsement_list(html, list_format):
    """Parse one endorsement list page.

    Parameters
    ----------
    html : str
        The saved page.
    list_format : str
        A key of PARSERS naming the page's layout.

    Returns
    -------
    list of dict
        One dict per listed candidate with keys name, office ("house",
        "senate", "governor", or "other"), state, district (two digits, "00"
        for at-large), date (YYYY-MM-DD or ""), and source_url. Some formats
        add more keys, such as Ballotpedia's endorsement_type.
    """
    return PARSERS[list_format](html)


def listing_date(copies, present, primary_date):
    """Date an endorsement from the archived copies of an undated list.

    A list page changes over time: Club for Growth cleared its list for the
    2026 cycle in February 2025, dropped candidates who left for other
    races, and re-listed some after their primary. So the date is not the
    first copy that ever shows a name. It is the start of the unbroken run
    of copies that includes the last copy before the primary.

    Parameters
    ----------
    copies : list of str
        Every copy's date (YYYYMMDD), oldest first.
    present : collection of str
        The copies that list this candidate.
    primary_date : str or None
        The candidate's primary (YYYYMMDD), or None if unknown.

    Returns
    -------
    tuple of (str or None, str)
        The date and "listed", or (None, "removed") when the candidate was
        listed earlier but dropped from the list before the primary, which
        reads as a withdrawn endorsement. A candidate removed after the
        primary (a loser, for example) keeps their date.
    """
    before = [day for day in copies if primary_date is None or day <= primary_date]
    after = [day for day in copies if day not in before and day in present]
    if before and before[-1] in present:
        anchor = copies.index(before[-1])
    elif after:
        # Listed (again) only after the primary. Date it there, so the timing
        # rule leaves it out instead of crediting an old listing.
        anchor = copies.index(after[-1])
    else:
        return None, "removed"
    while anchor > 0 and copies[anchor - 1] in present:
        anchor -= 1
    return copies[anchor], "listed"


def house_only(rows):
    """Keep the House rows and count the rest.

    Returns
    -------
    tuple of (list of dict, int)
        The House rows, and how many Senate, governor, and other rows were dropped.
    """
    house = [row for row in rows if row["office"] == "house"]
    return house, len(rows) - len(house)


def _fec_first_name(fec_name):
    """First word after the comma in an FEC "LAST, FIRST MIDDLE" name."""
    words = _normalize(fec_name.split(",", 1)[1]) if "," in fec_name else []
    return words[0] if words else ""


def _override_for(row, race_id, overrides):
    """Find a hand-checked override for this row by race and last name.

    The overrides come from nominee_matches.csv, written for nominee names.
    Lists spell first names differently ("Marty" or "Martin", "Nick" or
    "Nicholas J."), so only the race and the last word of the name must agree.
    """
    last_word = _normalize(row["name"])[-1:]
    for override in overrides:
        if override["race_id"] == race_id and _normalize(override["name"])[-1:] == last_word:
            return override["candidate_id"]
    return None


def _redrawn_match(row, same_party):
    """Find a candidate whose district changed since the list was written.

    Several states redrew their maps for 2026, so a list can name a
    member's old district (Greg Casar, listed in TX-35, filed in TX-37).
    Only an exact first and last name match within the state counts, and
    only when exactly one candidate fits, so a namesake is never swapped in.

    Returns
    -------
    pandas.Series or None
        The candidate's row, or None when there is not exactly one match.
    """
    first_name = _normalize(row["name"])[:1]
    in_state = same_party[same_party["race_id"].str[:2] == row["state"]]
    fits = in_state[in_state["name"].map(
        lambda fec_name: _last_name_matches(row["name"], fec_name) and [_fec_first_name(fec_name)] == first_name)]
    return fits.iloc[0] if len(fits) == 1 else None


def match_candidates(rows, candidates, party, overrides=()):
    """Attach an FEC candidate ID and race to each endorsed House candidate.

    A row that already carries a candidate_id keeps it, and its race comes
    from the candidates table, which handles a candidate whose district
    changed. Otherwise the row needs exactly one candidate of the endorser's
    party in the same race whose FEC last name ends the listed name. When
    several share the last name, the first name decides (the Nehls twins).
    When that still leaves a tie or no match, a hand-checked override is
    used if one exists (the same person filed twice, or a reversed name).
    With no one of that last name in the race, an exact name match
    elsewhere in the state is used, for a district that was redrawn.
    "DFL" (Minnesota) counts as "DEM".

    Parameters
    ----------
    rows : list of dict
        House rows from `parse_endorsement_list`.
    candidates : pandas.DataFrame
        The candidates table.
    party : str
        "REP" or "DEM", the endorser's side.
    overrides : list of dict, optional
        Rows of `load_nominee_matches`, with race_id, name, and candidate_id.

    Returns
    -------
    tuple of (list of dict, list of dict)
        Matched rows with candidate_id, race_id, and fec_name added, and the
        rows left for review, each with a review_reason.
    """
    by_id = candidates.set_index("candidate_id")
    matched, review = [], []
    for row in rows:
        if row.get("candidate_id") in by_id.index:
            fec = by_id.loc[row["candidate_id"]]
            matched.append({**row, "race_id": fec["race_id"], "fec_name": fec["name"]})
            continue

        race_id = f"{row['state']}-{row['district']}"
        same_party = candidates[candidates["party"].isin(PARTY_CODES.get(party, (party,)))]
        in_race = same_party[same_party["race_id"] == race_id]
        hits = in_race[in_race["name"].map(lambda fec_name: _last_name_matches(row["name"], fec_name))]
        if len(hits) > 1:
            first_name = _normalize(row["name"])[0]
            same_first = hits[hits["name"].map(_fec_first_name) == first_name]
            hits = same_first if len(same_first) == 1 else hits
        override = _override_for(row, race_id, overrides) if len(hits) != 1 else None
        moved = _redrawn_match(row, same_party) if hits.empty and override is None else None
        if moved is not None:
            note = f"listed as {race_id}, FEC filing is in {moved['race_id']}"
            matched.append({**row, "candidate_id": moved["candidate_id"], "race_id": moved["race_id"],
                            "fec_name": moved["name"], "match_note": note})
        elif override in by_id.index:
            matched.append({**row, "candidate_id": override, "race_id": race_id, "fec_name": by_id.loc[override, "name"]})
        elif len(hits) == 1:
            hit = hits.iloc[0]
            matched.append({**row, "candidate_id": hit["candidate_id"], "race_id": race_id, "fec_name": hit["name"]})
        else:
            reason = "no candidate with that last name" if hits.empty else f"{len(hits)} candidates share that last name"
            review.append({**row, "race_id": race_id, "review_reason": f"{reason} in {race_id} ({party})"})
    return matched, review
