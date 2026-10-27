"""Tests for src/manual.py."""

import pytest

from src.manual import (
    load_billionaires,
    load_donor_entities,
    load_nominee_matches,
    load_org_donors_reviewed,
    load_pac_industries,
)

HEADER = "committee_id,network,industry,source_url\n"


def write_csv(tmp_path, body):
    path = tmp_path / "pac_industries.csv"
    path.write_text(HEADER + body)
    return path


def test_loads_valid_rows(tmp_path):
    path = write_csv(
        tmp_path,
        "C001,Fairshake,crypto,https://a.example\nC002, Public First , ai_safety ,https://b.example\n",
    )
    rows = load_pac_industries(path)
    assert rows == [
        {"committee_id": "C001", "network": "Fairshake", "industry": "crypto", "source_url": "https://a.example"},
        {"committee_id": "C002", "network": "Public First", "industry": "ai_safety", "source_url": "https://b.example"},
    ]


def test_header_only_file_returns_empty_list(tmp_path):
    assert load_pac_industries(write_csv(tmp_path, "")) == []


def test_row_without_source_raises(tmp_path):
    with pytest.raises(ValueError, match="C001"):
        load_pac_industries(write_csv(tmp_path, "C001,Fairshake,crypto,\n"))


def test_duplicate_committee_raises(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        load_pac_industries(
            write_csv(tmp_path, "C001,Fairshake,crypto,https://a\nC001,Fairshake,crypto,https://b\n")
        )


def test_unknown_industry_rejected(tmp_path):
    with pytest.raises(ValueError, match="tech"):
        load_pac_industries(write_csv(tmp_path, "C001,Fairshake,tech,https://a\n"))


def test_missing_network_rejected(tmp_path):
    with pytest.raises(ValueError, match="network"):
        load_pac_industries(write_csv(tmp_path, "C001, ,crypto,https://a\n"))


def test_real_label_file_loads():
    """The committed CSV must pass the same checks as the test files."""
    rows = load_pac_industries()
    assert {row["industry"] for row in rows} <= {"crypto", "ai_industry", "ai_safety"}


def test_nominee_matches_need_a_note(tmp_path):
    path = tmp_path / "nominee_matches.csv"
    path.write_text("race_id,name,candidate_id,note\nTX-01,Ann Smith,H1,\n")
    with pytest.raises(ValueError, match="note"):
        load_nominee_matches(path)


def test_nominee_matches_load(tmp_path):
    path = tmp_path / "nominee_matches.csv"
    path.write_text("race_id,name,candidate_id,note\nTX-01,Ann Smith,H1,Checked on fec.gov\n")
    assert load_nominee_matches(path) == [
        {"race_id": "TX-01", "name": "Ann Smith", "candidate_id": "H1", "note": "Checked on fec.gov"}
    ]


def test_real_nominee_matches_file_loads():
    load_nominee_matches()


BILLIONAIRE_HEADER = "person,household_members,contributor_name_variants,forbes_url,note\n"
ENTITY_HEADER = "entity_name,person,source_url,evidence_type,note\n"
REVIEWED_HEADER = "entity_name,total,category,attributed_to,source_url,note\n"


def write_named_csv(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_billionaire_requires_forbes_url(tmp_path):
    path = write_named_csv(
        tmp_path, "billionaires.csv", BILLIONAIRE_HEADER + 'Ann Smith,Ann Smith,"SMITH, ANN",,note\n'
    )
    with pytest.raises(ValueError, match="forbes_url"):
        load_billionaires(path)


def test_variants_split(tmp_path):
    path = write_named_csv(
        tmp_path,
        "billionaires.csv",
        BILLIONAIRE_HEADER
        + 'Ann Smith,Ann Smith; Bob Smith,"SMITH, ANN;SMITH, ANN B.; SMITH, BOB",https://forbes.example,ok\n',
    )
    [row] = load_billionaires(path)
    assert row["household_members"] == ["Ann Smith", "Bob Smith"]
    assert row["contributor_name_variants"] == ["SMITH, ANN", "SMITH, ANN B.", "SMITH, BOB"]
    assert row["forbes_url"] == "https://forbes.example"


def test_entity_only_billionaire_may_have_no_variants(tmp_path):
    """Someone who gives only through an LLC has no personal FEC spelling."""
    path = write_named_csv(
        tmp_path, "billionaires.csv", BILLIONAIRE_HEADER + "Ann Smith,,,https://forbes.example,via LLC\n"
    )
    [row] = load_billionaires(path)
    assert row["contributor_name_variants"] == []
    assert row["household_members"] == ["Ann Smith"]


def test_entity_requires_source(tmp_path):
    path = write_named_csv(tmp_path, "donor_entities.csv", ENTITY_HEADER + "ACME LLC,Ann Smith,,news,x\n")
    with pytest.raises(ValueError, match="source_url"):
        load_donor_entities(path)


def test_entity_evidence_type_validated(tmp_path):
    path = write_named_csv(
        tmp_path, "donor_entities.csv", ENTITY_HEADER + "ACME LLC,Ann Smith,https://a,rumor,x\n"
    )
    with pytest.raises(ValueError, match="rumor"):
        load_donor_entities(path)


def test_entity_loads(tmp_path):
    path = write_named_csv(
        tmp_path, "donor_entities.csv", ENTITY_HEADER + "ACME LLC , Ann Smith,https://a,fec_filing,x\n"
    )
    assert load_donor_entities(path) == [
        {
            "entity_name": "ACME LLC",
            "person": "Ann Smith",
            "source_url": "https://a",
            "evidence_type": "fec_filing",
            "note": "x",
            # No share column means the whole entity belongs to the person
            "share": 1.0,
        }
    ]


SHARED_HEADER = "entity_name,person,source_url,evidence_type,share,note\n"


def test_entity_share_parsed(tmp_path):
    body = "FIRM LLC,Ann Smith,https://a,fec_filing,0.5,x\nFIRM LLC,Bob Jones,https://a,fec_filing,0.5,x\n"
    rows = load_donor_entities(write_named_csv(tmp_path, "donor_entities.csv", SHARED_HEADER + body))
    assert [row["share"] for row in rows] == [0.5, 0.5]


def test_entity_share_out_of_range_rejected(tmp_path):
    body = "FIRM LLC,Ann Smith,https://a,fec_filing,1.5,x\n"
    with pytest.raises(ValueError, match="share"):
        load_donor_entities(write_named_csv(tmp_path, "donor_entities.csv", SHARED_HEADER + body))


def test_entity_shares_cannot_exceed_whole(tmp_path):
    body = "FIRM LLC,Ann Smith,https://a,fec_filing,0.6,x\nFIRM LLC,Bob Jones,https://a,fec_filing,0.6,x\n"
    with pytest.raises(ValueError, match="FIRM LLC"):
        load_donor_entities(write_named_csv(tmp_path, "donor_entities.csv", SHARED_HEADER + body))


def test_reviewed_org_category_validated(tmp_path):
    path = write_named_csv(
        tmp_path, "org_donors_reviewed.csv", REVIEWED_HEADER + "ACME INC,2000000,mystery,,,x\n"
    )
    with pytest.raises(ValueError, match="mystery"):
        load_org_donors_reviewed(path)


def test_reviewed_attributed_row_needs_person_and_source(tmp_path):
    no_person = REVIEWED_HEADER + "ACME LLC,2000000,attributed,,https://a,x\n"
    with pytest.raises(ValueError, match="attributed_to"):
        load_org_donors_reviewed(write_named_csv(tmp_path, "a.csv", no_person))
    no_source = REVIEWED_HEADER + "ACME LLC,2000000,attributed,Ann Smith,,x\n"
    with pytest.raises(ValueError, match="source_url"):
        load_org_donors_reviewed(write_named_csv(tmp_path, "b.csv", no_source))


def test_reviewed_other_categories_need_a_note(tmp_path):
    path = write_named_csv(tmp_path, "org_donors_reviewed.csv", REVIEWED_HEADER + "LOCAL 1,2000000,union,,,\n")
    with pytest.raises(ValueError, match="note"):
        load_org_donors_reviewed(path)


def test_reviewed_total_is_a_number(tmp_path):
    path = write_named_csv(
        tmp_path, "org_donors_reviewed.csv", REVIEWED_HEADER + "LOCAL 1,2000000.5,union,,,Union site\n"
    )
    [row] = load_org_donors_reviewed(path)
    assert row["total"] == 2000000.5


def test_real_billionaire_files_load():
    """The committed research CSVs pass the same checks and agree with each other."""
    people = {row["person"] for row in load_billionaires()}
    entities = load_donor_entities()
    assert {row["person"] for row in entities} <= people
    reviewed = load_org_donors_reviewed()
    attributed = {row["entity_name"] for row in reviewed if row["category"] == "attributed"}
    # Every organization marked attributed in the review is also an entity row
    assert attributed <= {row["entity_name"] for row in entities}
