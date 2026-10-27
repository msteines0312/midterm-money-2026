"""Tests for src/analysis/billionaires.py, using a small hand-built database."""

import math

import pandas as pd
import pytest

from src.analysis.billionaires import (
    all_office_expenditures,
    billionaire_backed,
    concentration,
    could_not_test,
    household_giving,
    house_share,
    lean,
    primary_outcomes,
    primary_support,
    reconcile,
    win_rates,
)
from src.db import connect, create_schema, upsert_rows

CYCLE = 2026


def contribution(sub_id, committee_id, name, amount, memo_code=None, entity_type="IND", cycle=CYCLE):
    """One donor_contributions row with the fields the analysis reads."""
    return {
        "sub_id": sub_id,
        "cycle": cycle,
        "committee_id": committee_id,
        "contributor_name": name,
        "entity_type": entity_type,
        "amount": amount,
        "receipt_date": "2026-06-01",
        "memo_code": memo_code,
        "pulled_at": "2026-10-26",
    }


def totals_row(committee_id, receipts, pulled_at="2026-10-26"):
    """One pac_totals row."""
    return {
        "committee_id": committee_id,
        "cycle": CYCLE,
        "receipts": receipts,
        "independent_expenditures": 0.0,
        "coverage_end_date": "2026-09-30",
        "pulled_at": pulled_at,
    }


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    create_schema(connection)
    yield connection
    connection.close()


def load(conn, contributions=(), totals=()):
    upsert_rows(conn, "donor_contributions", list(contributions))
    upsert_rows(conn, "pac_totals", list(totals))


ADELSON = {
    "person": "Miriam Adelson",
    "household_members": ["Miriam Adelson"],
    "contributor_name_variants": ["ADELSON, MIRIAM", "ADELSON, MIRIAM DR."],
}


def person_total(giving, person, committee_id):
    """The `total` for one person and committee, or 0 if they have no row."""
    match = giving[(giving["person"] == person) & (giving["committee_id"] == committee_id)]
    return match["total"].sum()


def test_variants_merge_to_one_person(conn):
    """Two spellings of one name are one donor, not two."""
    load(
        conn,
        [
            contribution("1", "PAC1", "ADELSON, MIRIAM", 1_000_000),
            contribution("2", "PAC1", "ADELSON, MIRIAM DR.", 500_000),
        ],
    )
    giving = household_giving(conn, [ADELSON], [])
    assert len(giving) == 1
    assert giving.iloc[0]["direct"] == 1_500_000


def test_same_surname_different_people_stay_separate(conn):
    """A shared surname alone never merges two people."""
    ann = {"person": "Ann Smith", "household_members": ["Ann Smith"], "contributor_name_variants": ["SMITH, ANN"]}
    bob = {"person": "Bob Smith", "household_members": ["Bob Smith"], "contributor_name_variants": ["SMITH, BOB"]}
    load(
        conn,
        [
            contribution("1", "PAC1", "SMITH, ANN", 2_000_000),
            contribution("2", "PAC1", "SMITH, BOB", 3_000_000),
            # Not on any list, so it must not be pulled in by the surname
            contribution("3", "PAC1", "SMITH, CAROL", 9_000_000),
        ],
    )
    giving = household_giving(conn, [ann, bob], [])
    assert person_total(giving, "Ann Smith", "PAC1") == 2_000_000
    assert person_total(giving, "Bob Smith", "PAC1") == 3_000_000
    assert set(giving["person"]) == {"Ann Smith", "Bob Smith"}


def test_one_spelling_for_two_people_is_rejected(conn):
    """A name listed under two people would be counted twice, so fail loudly."""
    other = {"person": "Other Person", "household_members": ["Other Person"], "contributor_name_variants": ["ADELSON, MIRIAM"]}
    with pytest.raises(ValueError, match="ADELSON, MIRIAM"):
        household_giving(conn, [ADELSON, other], [])


def test_entity_money_attributed(conn):
    """Money from a sourced entity counts for the person, scaled by their share."""
    firm = {"person": "Marc Andreessen", "household_members": ["Marc Andreessen"], "contributor_name_variants": []}
    entities = [
        {"entity_name": "A16Z CAPITAL MANAGEMENT LLC", "person": "Marc Andreessen", "share": 0.5},
        {"entity_name": "A16Z CAPITAL MANAGEMENT LLC", "person": "Ben Horowitz", "share": 0.5},
    ]
    load(conn, [contribution("1", "PAC1", "A16Z CAPITAL MANAGEMENT LLC", 4_000_000, entity_type="ORG")])
    giving = household_giving(conn, [firm], entities)
    row = giving.iloc[0]
    assert row["person"] == "Marc Andreessen"
    assert row["direct"] == 0
    assert row["via_entities"] == 2_000_000
    assert row["total"] == 2_000_000


def test_entity_for_unlisted_person_is_ignored(conn):
    """Only listed billionaires get rows, even if an entity names someone else."""
    entities = [{"entity_name": "FIRM LLC", "person": "Ben Horowitz", "share": 0.5}]
    load(conn, [contribution("1", "PAC1", "FIRM LLC", 1_000_000, entity_type="ORG")])
    assert household_giving(conn, [ADELSON], entities).empty


def test_memo_excluded(conn):
    """Memo rows repeat money already counted elsewhere, so they never add."""
    load(
        conn,
        [
            contribution("1", "PAC1", "ADELSON, MIRIAM", 1_000_000),
            contribution("2", "PAC1", "ADELSON, MIRIAM", 1_000_000, memo_code="X"),
        ],
    )
    assert household_giving(conn, [ADELSON], []).iloc[0]["total"] == 1_000_000


def test_refund_nets(conn):
    """A negative amount reduces the total instead of being dropped."""
    load(
        conn,
        [
            contribution("1", "PAC1", "ADELSON, MIRIAM", 1_000_000),
            contribution("2", "PAC1", "ADELSON, MIRIAM", -250_000),
        ],
    )
    assert household_giving(conn, [ADELSON], []).iloc[0]["total"] == 750_000


def test_other_cycles_are_ignored(conn):
    load(conn, [contribution("1", "PAC1", "ADELSON, MIRIAM", 1_000_000, cycle=2024)])
    assert household_giving(conn, [ADELSON], []).empty


def concentration_for(conn, receipts, *amounts):
    """Share of one PAC's receipts given by each of Ann Smith (first amount) and Bob Smith (second)."""
    ann = {"person": "Ann Smith", "household_members": ["Ann Smith"], "contributor_name_variants": ["SMITH, ANN"]}
    bob = {"person": "Bob Smith", "household_members": ["Bob Smith"], "contributor_name_variants": ["SMITH, BOB"]}
    names = ["SMITH, ANN", "SMITH, BOB"]
    load(
        conn,
        [contribution(str(i), "PAC1", names[i], amount) for i, amount in enumerate(amounts)],
        [totals_row("PAC1", receipts)],
    )
    return concentration(household_giving(conn, [ann, bob], []), conn)


def test_concentration_is_total_over_receipts(conn):
    result = concentration_for(conn, 10_000_000, 2_500_000)
    assert list(result.columns) == ["committee_id", "person", "share"]
    assert result.iloc[0]["share"] == pytest.approx(0.25)


def test_concentration_is_nan_without_receipts(conn):
    """A PAC with no committee totals keeps its row but has no share."""
    load(conn, [contribution("1", "PAC1", "ADELSON, MIRIAM", 1_000_000)])
    result = concentration(household_giving(conn, [ADELSON], []), conn)
    assert math.isnan(result.iloc[0]["share"])


def test_concentration_uses_latest_totals(conn):
    load(
        conn,
        [contribution("1", "PAC1", "ADELSON, MIRIAM", 1_000_000)],
        [totals_row("PAC1", 100_000_000, "2026-10-01"), totals_row("PAC1", 2_000_000, "2026-10-26")],
    )
    result = concentration(household_giving(conn, [ADELSON], []), conn)
    assert result.iloc[0]["share"] == pytest.approx(0.5)


def reconcile_frame(committee_id="PAC1", reconciled=True):
    return pd.DataFrame(
        [{"committee_id": committee_id, "itemized": 0.0, "receipts": 0.0, "diff_pct": 0.0, "reconciled": reconciled}]
    )


def share_frame(*shares):
    return pd.DataFrame(
        [{"committee_id": "PAC1", "person": f"Donor {i}", "share": share} for i, share in enumerate(shares)]
    )


def test_share_at_threshold_is_backed():
    """Exactly half counts. The rule is 'at least 50%'."""
    result = billionaire_backed(share_frame(0.5), reconcile_frame())
    assert result.iloc[0]["status"] == "backed"


def test_share_just_under_threshold_is_not_backed():
    result = billionaire_backed(share_frame(0.4999), reconcile_frame())
    assert result.iloc[0]["status"] == "near"


def test_unreconciled_never_backed():
    """A big share on numbers that don't add up is reported, not classified."""
    result = billionaire_backed(share_frame(0.9), reconcile_frame(reconciled=False))
    assert result.iloc[0]["status"] == "unreconciled"


def test_two_donors_at_30_percent_not_backed():
    """There is no joint threshold, so two 30% donors leave the PAC unlabeled."""
    assert billionaire_backed(share_frame(0.3, 0.3), reconcile_frame()).empty


def test_near_band_flagged():
    result = billionaire_backed(share_frame(0.35, 0.45), reconcile_frame())
    assert list(result["status"]) == ["near", "near"]


def test_missing_reconcile_row_is_not_backed():
    """A PAC that was never reconciled can't be called backed."""
    result = billionaire_backed(share_frame(0.8), reconcile_frame(committee_id="OTHER"))
    assert result.iloc[0]["status"] == "unreconciled"


def test_reconcile_flags_gap(conn):
    load(
        conn,
        [
            contribution("1", "GOOD", "SMITH, ANN", 9_800_000),
            contribution("2", "GAPPY", "SMITH, ANN", 5_000_000),
            # A memo row must not count toward what was itemized
            contribution("3", "GOOD", "SMITH, ANN", 5_000_000, memo_code="X"),
        ],
        [totals_row("GOOD", 10_000_000), totals_row("GAPPY", 20_000_000)],
    )
    result = reconcile(conn, ["GOOD", "GAPPY"]).set_index("committee_id")
    assert result.loc["GOOD", "itemized"] == 9_800_000
    assert result.loc["GOOD", "diff_pct"] == pytest.approx(-0.02)
    assert bool(result.loc["GOOD", "reconciled"])
    assert result.loc["GAPPY", "diff_pct"] == pytest.approx(-0.75)
    assert not bool(result.loc["GAPPY", "reconciled"])


def test_reconcile_without_totals_is_not_reconciled(conn):
    load(conn, [contribution("1", "PAC1", "SMITH, ANN", 1_000_000)])
    row = reconcile(conn, ["PAC1"]).iloc[0]
    assert math.isnan(row["diff_pct"])
    assert not bool(row["reconciled"])


# ---- House share and lean ----

SPENDING_DATE = "2026-10-24"


def spending(committee_id, candidate_key, party, support_oppose, total, election_type="G"):
    """One outside_spending row, with the columns the analysis reads."""
    return {
        "committee_id": committee_id,
        "candidate_key": candidate_key,
        "candidate_id": candidate_key,
        "candidate_name": candidate_key,
        "party": party,
        "race_id": "XX-01",
        "election_type": election_type,
        "support_oppose": support_oppose,
        "pulled_at": SPENDING_DATE,
        "total": total,
        "count": 1,
    }


def super_pac(committee_id="PAC1", committee_type="O"):
    return {"committee_id": committee_id, "name": committee_id, "committee_type": committee_type, "designation": "U"}


def one_donor_conn(conn, gift, receipts, spending_rows, committees=None):
    """Ann Smith gives `gift` to PAC1, which reports `receipts` and the given House spending."""
    load(
        conn,
        [contribution("1", "PAC1", "SMITH, ANN", gift)],
        [totals_row("PAC1", receipts)],
    )
    upsert_rows(conn, "committees", committees or [super_pac()])
    upsert_rows(conn, "outside_spending", spending_rows)
    return household_giving(conn, [ANN], [])


ANN = {"person": "Ann Smith", "household_members": ["Ann Smith"], "contributor_name_variants": ["SMITH, ANN"]}


def test_house_share_proportional(conn):
    """A quarter of the PAC's money means a quarter of its spending is hers."""
    rows = [spending("PAC1", "H1", "DEM", "S", 3_000_000), spending("PAC1", "H2", "REP", "O", 1_000_000)]
    giving = one_donor_conn(conn, 2_500_000, 10_000_000, rows)
    result = house_share(giving, conn, all_office_ie={"PAC1": 8_000_000}).iloc[0]
    assert result["total_giving"] == 2_500_000
    assert result["house_dollars"] == pytest.approx(1_000_000)
    assert result["house_pct"] == pytest.approx(0.4)
    assert result["other_or_unspent"] == pytest.approx(500_000)


def test_other_or_unspent_nonnegative_when_pac_underspent(conn):
    """Money the PAC has not spent yet shows up as 'other or unspent', never below zero."""
    rows = [spending("PAC1", "H1", "DEM", "S", 100_000)]
    giving = one_donor_conn(conn, 5_000_000, 5_000_000, rows)
    result = house_share(giving, conn, all_office_ie={"PAC1": 100_000}).iloc[0]
    assert result["other_or_unspent"] == pytest.approx(4_900_000)


def test_spending_beyond_receipts_is_capped(conn):
    """Spending above reported receipts (later money) can't be credited to the donor."""
    rows = [spending("PAC1", "H1", "DEM", "S", 10_000_000)]
    giving = one_donor_conn(conn, 5_000_000, 10_000_000, rows)
    result = house_share(giving, conn, all_office_ie={"PAC1": 20_000_000}).iloc[0]
    assert result["other_or_unspent"] == pytest.approx(0)
    assert result["house_dollars"] == pytest.approx(2_500_000)


def test_house_share_ignores_non_super_pacs(conn):
    """Spending by a committee that isn't a super PAC or hybrid never counts."""
    rows = [spending("PAC1", "H1", "DEM", "S", 1_000_000)]
    giving = one_donor_conn(conn, 1_000_000, 1_000_000, rows, committees=[super_pac(committee_type="Y")])
    assert house_share(giving, conn, all_office_ie={"PAC1": 1_000_000}).iloc[0]["house_dollars"] == 0


def test_lean_counts_oppose_as_helping_other_party(conn):
    """Opposing a Republican helps Democrats. Independents help neither side."""
    rows = [
        spending("PAC1", "H1", "DEM", "S", 1_000_000),
        spending("PAC1", "H2", "REP", "O", 1_000_000),
        spending("PAC1", "H3", "REP", "S", 1_000_000),
        spending("PAC1", "H4", "IND", "S", 5_000_000),
    ]
    giving = one_donor_conn(conn, 8_000_000, 8_000_000, rows)
    result = lean(giving, conn, all_office_ie={"PAC1": 8_000_000}).iloc[0]
    assert result["dem_helping"] == pytest.approx(2_000_000)
    assert result["rep_helping"] == pytest.approx(1_000_000)
    assert result["dem_share"] == pytest.approx(2 / 3)


def test_lean_nan_without_house_spending(conn):
    giving = one_donor_conn(conn, 1_000_000, 1_000_000, [])
    result = lean(giving, conn, all_office_ie={"PAC1": 0}).iloc[0]
    assert result["dem_helping"] == 0 and result["rep_helping"] == 0
    assert math.isnan(result["dem_share"])


def test_all_office_expenditures_uses_latest_filing(tmp_path):
    """An amended filing replaces the one it amends, and all offices are summed."""
    header = "cand_id,cand_name,spe_id,spe_nam,ele_type,can_office_state,can_office_dis,can_office,cand_pty_aff,exp_amo,exp_date,agg_amo,sup_opp,pur,pay,file_num,amndt_ind,tran_id,image_num,receipt_dat,fec_election_yr,prev_file_num,dissem_dt\n"
    row = '"{}","X","PAC1","P","G","TX","01","{}","","{}","","","S","","","{}","N","{}","","","2026","{}",""\n'
    text = (
        header
        + row.format("H1", "H", "1000", "10", "T1", "")
        + row.format("S1", "S", "2000", "11", "T2", "")
        # Amends filing 10, so the 1000 above no longer counts
        + row.format("H1", "H", "1500", "12", "T1", "10")
    )
    path = tmp_path / "ie.csv"
    path.write_text(text, encoding="latin-1")
    assert all_office_expenditures(SPENDING_DATE, path=path, check_date=False) == {"PAC1": 3500.0}


# ---- Primary outcomes ----

BACKED = pd.DataFrame({"committee_id": ["PAC1"], "person": ["Ann Smith"]})


def primary_row(candidate_key, total, support_oppose="S", committee_id="PAC1", election_type="P", race_id="TX-01", candidate_id="USE_KEY", name=None):
    """A primary outside_spending row. The candidate ID defaults to the key."""
    row = spending(committee_id, candidate_key, "REP", support_oppose, total, election_type=election_type)
    row["race_id"] = race_id
    row["candidate_id"] = candidate_key if candidate_id == "USE_KEY" else candidate_id
    row["candidate_name"] = name or candidate_key
    return row


def support_for(conn, rows, committees=None, backed=BACKED):
    upsert_rows(conn, "committees", committees or [super_pac("PAC1"), super_pac("PAC2")])
    upsert_rows(conn, "outside_spending", rows)
    return primary_support(conn, backed)


NOMINEES = [{"race_id": "TX-01", "name": "John Smith", "party": "Republican"}]


def test_min_spend_threshold(conn):
    support = support_for(conn, [primary_row("H1", 9_999), primary_row("H2", 10_000)])
    assert list(support["candidate_key"]) == ["H2"]


def test_primary_support_only_counts_primaries_for_backed_pacs(conn):
    rows = [
        primary_row("H1", 50_000, election_type="G"),
        primary_row("H2", 50_000, committee_id="PAC2"),
        primary_row("H3", 50_000, election_type="R"),
    ]
    assert list(support_for(conn, rows)["candidate_key"]) == ["H3"]


def test_win_by_candidate_id(conn):
    support = support_for(conn, [primary_row("H1", 50_000)])
    result = primary_outcomes(support, {"H1"}, NOMINEES).iloc[0]
    assert result["outcome"] == "won" and result["matched_by"] == "id"


def test_win_by_name_fallback(conn):
    """A filing with no candidate ID still matches the race's nominee by last name."""
    row = primary_row("TX-01|SMITH", 50_000, candidate_id=None, name="SMITH, JOHN")
    result = primary_outcomes(support_for(conn, [row]), set(), NOMINEES).iloc[0]
    assert result["outcome"] == "won" and result["matched_by"] == "name"


def test_lost_when_not_the_nominee(conn):
    support = support_for(conn, [primary_row("H9", 50_000, name="JONES, BOB")])
    assert primary_outcomes(support, {"H1"}, NOMINEES).iloc[0]["outcome"] == "lost"


def test_unmatched_goes_to_review(conn):
    """No ID and no name match is never counted as a loss."""
    row = primary_row("TX-01|JONES", 50_000, candidate_id=None, name="JONES, BOB")
    assert primary_outcomes(support_for(conn, [row]), set(), NOMINEES).iloc[0]["outcome"] == "review"


def test_race_without_known_nominees_goes_to_review(conn):
    """If we don't know who the race's nominees are, a missing ID proves nothing."""
    support = support_for(conn, [primary_row("H9", 50_000, race_id="OH-05")])
    assert primary_outcomes(support, {"H1"}, NOMINEES).iloc[0]["outcome"] == "review"


def test_top_two_advance_counts_as_win(conn):
    """In a top-two primary both Republicans advance, and both are wins."""
    nominees = [
        {"race_id": "CA-22", "name": "Ann Lee", "party": "Republican"},
        {"race_id": "CA-22", "name": "Bo Park", "party": "Republican"},
    ]
    rows = [primary_row("H1", 50_000, race_id="CA-22"), primary_row("H2", 50_000, race_id="CA-22")]
    outcomes = primary_outcomes(support_for(conn, rows), {"H1", "H2"}, nominees)
    assert list(outcomes["outcome"]) == ["won", "won"]


def test_opposed_reported_separately(conn):
    """Opposing a candidate who then lost is what the PAC wanted. It is not a win."""
    rows = [
        primary_row("H1", 50_000),
        primary_row("H8", 50_000, support_oppose="O", name="LOSER, LEE"),
        primary_row("H7", 50_000, support_oppose="O", name="WINNER, WES"),
    ]
    outcomes = primary_outcomes(support_for(conn, rows), {"H1", "H7"}, NOMINEES)
    opposed = outcomes[outcomes["support_oppose"] == "O"].set_index("candidate_key")
    assert opposed.loc["H8", "outcome_for_pac"] == "wanted"
    assert opposed.loc["H7", "outcome_for_pac"] == "unwanted"
    assert opposed["outcome"].isna().all()
    rates = win_rates(outcomes)
    assert rates["pooled"]["won"] == 1 and rates["pooled"]["lost"] == 0


def test_distinct_candidate_counted_once_per_race(conn):
    """Two PACs backing one candidate is one candidate in the pooled rate."""
    backed = pd.DataFrame({"committee_id": ["PAC1", "PAC2"], "person": ["Ann Smith", "Bob Jones"]})
    rows = [
        primary_row("H1", 50_000),
        primary_row("H1", 50_000, committee_id="PAC2"),
        primary_row("H9", 50_000, committee_id="PAC2", name="JONES, BOB"),
    ]
    outcomes = primary_outcomes(support_for(conn, rows, backed=backed), {"H1"}, NOMINEES)
    rates = win_rates(outcomes)
    assert rates["pooled"] == {"won": 1, "lost": 1, "review": 0, "rate": 0.5}
    assert rates["by_pac"]["PAC1"]["won"] == 1 and rates["by_pac"]["PAC2"]["won"] == 1
    assert rates["by_pac"]["PAC2"]["rate"] == 0.5


def test_win_rate_is_none_without_decided_candidates():
    rates = win_rates(pd.DataFrame({
        "committee_id": ["PAC1"], "race_id": ["TX-01"], "candidate_key": ["H1"], "candidate_id": ["H1"],
        "support_oppose": ["S"], "outcome": ["review"], "outcome_for_pac": [None],
    }))
    assert rates["pooled"] == {"won": 0, "lost": 0, "review": 1, "rate": None}



# ---- PACs whose gap could hide a billionaire-backed PAC ----


def gap_frames(share, diff_pct, reconciled, receipts=10_000_000):
    """One donor's share of a PAC, and the PAC's reconcile row."""
    shares = pd.DataFrame([{"committee_id": "PAC1", "person": "Ann Smith", "share": share}])
    recon = pd.DataFrame([{"committee_id": "PAC1", "itemized": 0.0, "receipts": receipts,
                           "diff_pct": diff_pct, "reconciled": reconciled}])
    return shares, recon


def test_big_gap_could_hide_a_backed_pac():
    """30% seen plus a 25% unexplained gap could be 55%, so the PAC can't be ruled out."""
    result = could_not_test(*gap_frames(0.30, -0.25, False))
    assert result.iloc[0]["upper_bound"] == pytest.approx(0.55)


def test_small_gap_cannot_change_the_answer():
    """30% plus a 5% gap tops out at 35%, well under half."""
    assert could_not_test(*gap_frames(0.30, -0.05, False)).empty


def test_reconciled_pac_is_never_listed():
    assert could_not_test(*gap_frames(0.30, -0.04, True)).empty


def test_overshoot_has_no_missing_money():
    """Itemized rows above the reported total leave nothing unexplained to add."""
    assert could_not_test(*gap_frames(0.30, 0.20, False)).empty


def test_pac_already_over_threshold_is_not_listed_here():
    """A PAC at 60% that fails to reconcile already shows as unreconciled."""
    assert could_not_test(*gap_frames(0.60, -0.25, False)).empty
