"""Tests for src/fec/history.py, run on real 2024 reports and ccl24 lines.

The fixtures hold every version of every 2024-cycle report for eight
committees picked for these tests (see HISTORY_SAMPLE_COMMITTEES in
scripts/save_fixtures.py). A fake client serves them the way the real API
does: it filters by report_type, committee_type, and min_receipt_date, but
not by amendment status, so the loader's own amendment handling is tested.
"""

import json
from pathlib import Path

import pytest

from src.fec.history import (
    campaign_money,
    supplemental_money,
    latest_versions,
    pre_general_money,
    principal_committees,
    report_external,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPORTS = [
    rec
    for name in ("reports_12g_sample.json", "reports_ye_sample.json")
    for rec in json.loads((FIXTURES / name).read_text())["results"]
]
CCL = (FIXTURES / "ccl_sample.txt").read_text(encoding="latin-1")


def report(file_number):
    """Return the fixture report with this FEC file number."""
    return next(rec for rec in REPORTS if rec["file_number"] == file_number)


class FixtureClient:
    """Serves the saved reports like /reports/house-senate/ and records each query."""

    def __init__(self):
        self.calls = []

    def iter_results(self, path, params=None, max_pages=None):
        self.calls.append((path, dict(params)))
        types = params["report_type"]
        types = [types] if isinstance(types, str) else types
        # The API also filters by committee when asked (the supplemental path)
        committees = params.get("committee_id")
        return [
            rec for rec in REPORTS
            if rec["report_type"] in types
            and rec["committee_type"] == params["committee_type"]
            and rec["receipt_date"] >= params["min_receipt_date"]
            and (committees is None or rec["committee_id"] in committees)
        ]


@pytest.fixture
def run(capsys):
    """Run the loader once on the fixtures. Returns rows by candidate, the client, and printed output."""
    client = FixtureClient()
    rows = pre_general_money(client, 2024, CCL)
    return {row["candidate_id"]: row for row in rows}, client, capsys.readouterr().out


def test_principal_committees_drops_duplicate_links():
    committees = principal_committees(CCL)
    # ccl24 links C00830661 to H4RI01141 twice (one row per election year)
    assert committees["H4RI01141"] == ["C00830661"]
    assert committees["H2NV04045"] == ["C00582320", "C00654095"]


def test_report_external_matches_fields():
    # C00507368's amended 12G: 479,505.16 individuals - 3,300 refunds
    # + 1,211,525 PACs + 1,000 party, no committee refunds
    assert report_external(report(1851396)) == pytest.approx(1_688_730.16)


def test_chosen_report_ytd_is_cycle_to_date(run):
    # For House committees the "_ytd" fields are Form 3 Column B, "election
    # cycle-to-date", which restarts after each general election rather than
    # on Jan 1. Beatty's YE 2023 (183,877.74 from individuals) is already
    # inside her 12G's 479,505.16, so adding the YE would count 2023 twice.
    assert report(1769782)["total_individual_contributions_ytd"] == "183877.74"
    rows, _, _ = run
    row = rows["H2OH03125"]
    # Matches net contributions in Column B of the filed 12G (file 1851396)
    assert row["external_contributions"] == pytest.approx(1_688_730.16)
    assert row["coverage_end_date"] == "2024-10-16"
    assert rows["H4RI01141"]["external_contributions"] == pytest.approx(20_820)
    assert rows["H4RI01141"]["candidate_self_funding"] == pytest.approx(3_579.07)


def test_most_recent_amendment_only(run):
    # The original 12G (file 1832874) and its December amendment (1851396)
    # differ by $1,000. Only the amendment counts.
    latest = latest_versions([report(1832874), report(1851396)])
    assert [rec["file_number"] for rec in latest] == [1851396]
    rows, client, _ = run
    assert rows["H2OH03125"]["external_contributions"] == pytest.approx(1_688_730.16)
    # The server-side filter is requested too, even though the fake ignores it
    assert client.calls[0][1]["is_amended"] == "false"


def test_multiple_principal_committees_summed(run):
    rows, _, _ = run
    # H2NV04045 has two principal committees. Both reported $0 on their Q3,
    # so the real sample checks both are found; the sum is checked below.
    assert rows["H2NV04045"]["committee_id"] == "C00582320,C00654095"
    assert rows["H2NV04045"]["external_contributions"] == 0
    # No real 2022 or 2024 candidate has money in two separate principal
    # committees, so two real reports from different campaigns check the sum
    total = campaign_money([report(1882790), report(1847702)])
    assert total["external_contributions"] == pytest.approx(34_110.14 + 20_820)
    assert total["candidate_self_funding"] == pytest.approx(1_000 + 3_579.07)


def test_falls_back_to_latest_report_before_cutoff(run):
    rows, _, _ = run
    # C00859140's 12G covers Oct 1 to Oct 20, past the Oct 16 cutoff, so its
    # Q3 (29,960.14 + 300 PAC + 3,850 party, $1,000 candidate loan) is used
    row = rows["H4MO07156"]
    assert row["coverage_end_date"] == "2024-09-30"
    assert row["external_contributions"] == pytest.approx(34_110.14)
    assert row["candidate_self_funding"] == pytest.approx(1_000)


def test_no_qualifying_report_means_no_row(run):
    rows, _, _ = run
    # C00886770's only 2024 report is past the cutoff, so H4TX38045 is left out
    assert "H4TX38045" not in rows
    assert len(rows) == 7


def test_odd_coverage_12g_flagged(run):
    _, _, out = run
    # Cutoff is the most common 12G end date. Two 12Gs end after it:
    # C00859140 (Oct 20) and C00886770 (Aug 9 to Nov 5).
    assert "cutoff 2024-10-16" in out
    assert "2 reports excluded" in out
    assert "C00886770" in out


def test_query_filters_server_side(run):
    _, client, _ = run
    assert len(client.calls) == 1
    path, params = client.calls[0]
    assert path == "/reports/house-senate/"
    assert params["cycle"] == 2024
    assert params["min_receipt_date"] == "2024-01-01"
    # YE and 30G reports never count, so they are never requested
    assert "YE" not in params["report_type"] and "30G" not in params["report_type"]


def test_supplemental_money_matches_the_full_loader(run):
    rows, _, _ = run
    # The supplemental path is for candidates the ccl file leaves out. Given
    # a candidate's committees from the API, it must give the same row the
    # full loader gives, and ask only for those committees.
    client = FixtureClient()
    extra = supplemental_money(client, 2024, {"H4MO07156": ["C00859140"]}, cutoff="2024-10-16")
    assert extra == [rows["H4MO07156"]]
    assert client.calls[0][1]["committee_id"] == ["C00859140"]


def test_supplemental_money_skips_candidates_without_reports():
    # C00886770's only report ends after the cutoff, and a candidate with no
    # committee has nothing to look up
    extra = supplemental_money(FixtureClient(), 2024, {"H4TX38045": ["C00886770"], "H0XX00000": []}, cutoff="2024-10-16")
    assert extra == []
