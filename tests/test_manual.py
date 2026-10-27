"""Tests for src/manual.py."""

import pytest

from src.manual import load_pac_industries

HEADER = "committee_id,industry,source_url\n"


def write_csv(tmp_path, body):
    path = tmp_path / "pac_industries.csv"
    path.write_text(HEADER + body)
    return path


def test_loads_valid_rows(tmp_path):
    path = write_csv(tmp_path, "C001,crypto,https://a.example\nC002, AI ,https://b.example\n")
    rows = load_pac_industries(path)
    assert rows == [
        {"committee_id": "C001", "industry": "crypto", "source_url": "https://a.example"},
        {"committee_id": "C002", "industry": "AI", "source_url": "https://b.example"},
    ]


def test_header_only_file_returns_empty_list(tmp_path):
    assert load_pac_industries(write_csv(tmp_path, "")) == []


def test_row_without_source_raises(tmp_path):
    with pytest.raises(ValueError, match="C001"):
        load_pac_industries(write_csv(tmp_path, "C001,crypto,\n"))


def test_duplicate_committee_raises(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        load_pac_industries(write_csv(tmp_path, "C001,crypto,https://a\nC001,AI,https://b\n"))
