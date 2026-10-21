"""Tests for src/config.py."""

import pytest

from src.config import load_api_key


def test_load_api_key_reads_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("FEC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("FEC_API_KEY=abc123\n")
    assert load_api_key(env) == "abc123"


def test_load_api_key_missing_explains_how_to_fix(tmp_path, monkeypatch):
    monkeypatch.delenv("FEC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="api.data.gov"):
        load_api_key(tmp_path / ".env")
