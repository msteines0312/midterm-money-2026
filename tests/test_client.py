"""Tests for src/fec/client.py.

A fake session stands in for requests so the tests never touch the real
API, and `sleep` is swapped for a list append so they never actually wait.
"""

import pytest

from src.fec.client import FecApiError, FecClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code, self._payload = status_code, payload or {}
        self.headers, self.text = headers or {}, "error body"

    def json(self):
        return self._payload


class FakeSession:
    """Returns queued responses in order and records each request's params."""

    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)


def page(n, pages, items):
    return FakeResponse(payload={"results": items, "pagination": {"page": n, "pages": pages}})


def make_client(responses, **kwargs):
    sleeps = []
    session = FakeSession(responses)
    client = FecClient("KEY", session=session, sleep=sleeps.append, **kwargs)
    return client, session, sleeps


def test_get_sends_api_key():
    client, session, _ = make_client([FakeResponse(payload={"results": []})])
    client.get("/candidates/")
    url, params = session.calls[0]
    assert params["api_key"] == "KEY"
    assert url.endswith("/candidates/")


def test_iter_results_follows_every_page():
    client, session, _ = make_client([page(1, 3, [1, 2]), page(2, 3, [3, 4]), page(3, 3, [5, 6])])
    assert list(client.iter_results("/candidates/")) == [1, 2, 3, 4, 5, 6]
    assert [c[1]["page"] for c in session.calls] == [1, 2, 3]


def test_iter_results_respects_max_pages():
    client, session, _ = make_client([page(1, 3, [1, 2])])
    assert list(client.iter_results("/candidates/", max_pages=1)) == [1, 2]
    assert len(session.calls) == 1


def test_retries_429_on_same_page():
    client, session, sleeps = make_client([page(1, 2, ["a"]), FakeResponse(429), page(2, 2, ["b"])])
    assert list(client.iter_results("/candidates/")) == ["a", "b"]
    assert [c[1]["page"] for c in session.calls] == [1, 2, 2]
    assert sleeps == [2]


def test_gives_up_after_max_retries():
    client, _, _ = make_client([FakeResponse(429)] * 6, max_retries=5)
    with pytest.raises(FecApiError):
        client.get("/candidates/")


def test_403_raises_without_retry():
    client, session, _ = make_client([FakeResponse(403)])
    with pytest.raises(FecApiError, match="403"):
        client.get("/candidates/")
    assert len(session.calls) == 1


def test_cools_down_when_remaining_hits_zero():
    response = FakeResponse(payload={"results": []}, headers={"X-RateLimit-Remaining": "0"})
    client, _, sleeps = make_client([response], cooldown_seconds=60)
    client.get("/candidates/")
    assert sleeps == [60]


def test_request_count_includes_retries():
    client, _, _ = make_client([FakeResponse(status_code=429), page(1, 2, [1]), page(2, 2, [2])])
    list(client.iter_results("/reports/house-senate/"))
    assert client.request_count == 3


def keyset_page(items, last_indexes):
    """A Schedule A style response: results plus the cursor for the next page."""
    return FakeResponse(payload={"results": items, "pagination": {"last_indexes": last_indexes}})


def test_iter_keyset_follows_last_indexes():
    cursor = {"last_index": "99", "last_contribution_receipt_amount": "500.00"}
    client, session, _ = make_client([
        keyset_page([1, 2], cursor),
        keyset_page([3], {"last_index": "50", "last_contribution_receipt_amount": "100.00"}),
        keyset_page([], None),
    ])
    assert list(client.iter_keyset("/schedules/schedule_a/", {"min_amount": 250000})) == [1, 2, 3]
    first, second, third = (call[1] for call in session.calls)
    # The first request has no cursor, the next ones carry the previous response's
    assert "last_index" not in first
    assert second["last_index"] == "99" and second["last_contribution_receipt_amount"] == "500.00"
    assert third["last_index"] == "50"
    # Original filters ride along on every request
    assert all(call["min_amount"] == 250000 for call in (first, second, third))


def test_iter_keyset_stops_when_last_indexes_missing():
    client, session, _ = make_client([keyset_page([1, 2], None)])
    assert list(client.iter_keyset("/schedules/schedule_a/")) == [1, 2]
    assert len(session.calls) == 1


def test_iter_keyset_respects_max_pages():
    client, session, _ = make_client([keyset_page([1], {"last_index": "9"})])
    assert list(client.iter_keyset("/schedules/schedule_a/", max_pages=1)) == [1]
    assert len(session.calls) == 1
