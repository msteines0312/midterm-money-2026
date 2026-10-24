"""Tests for src/manual.py."""

import pytest

from src.manual import load_nominee_matches, load_pac_industries

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
