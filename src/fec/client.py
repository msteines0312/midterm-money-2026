"""A small client for the OpenFEC API.

Handles the three things every request needs: the API key, page-by-page
pagination, and staying inside the rate limit. The session and sleep
function can be swapped out, which is how the tests run without the network.
"""

import time

import requests

from src.config import FEC_BASE_URL


class FecApiError(Exception):
    """Raised when the FEC API returns an error we can't recover from."""


class FecClient:
    """Fetch JSON from OpenFEC with retries and pagination.

    Parameters
    ----------
    api_key : str
        Key from api.data.gov.
    session : requests.Session, optional
        Anything with a `get(url, params, timeout)` method. Defaults to a new session.
    sleep : callable, optional
        Called with a number of seconds to wait. Defaults to `time.sleep`.
    max_retries : int, optional
        How many times to retry a rate-limited (HTTP 429) request.
    cooldown_seconds : int, optional
        Pause after a response says no requests remain in the current window.
    """

    def __init__(self, api_key, session=None, sleep=time.sleep, max_retries=5, cooldown_seconds=60):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.sleep = sleep
        self.max_retries = max_retries
        self.cooldown_seconds = cooldown_seconds
        # Every HTTP request sent, retries included, so a pull can report its cost
        self.request_count = 0

    def get(self, path, params=None):
        """Request one endpoint and return the parsed JSON.

        Parameters
        ----------
        path : str
            Endpoint path, e.g. "/candidates/".
        params : dict, optional
            Query parameters. The API key is added automatically.

        Returns
        -------
        dict
            The response body.

        Raises
        ------
        FecApiError
            On any non-200 status other than a retryable 429, or when
            retries run out.
        """
        params = {**(params or {}), "api_key": self.api_key}
        for attempt in range(1, self.max_retries + 2):
            response = self.session.get(FEC_BASE_URL + path, params=params, timeout=30)
            self.request_count += 1

            # A 429 means "too many requests, try later", so waiting fixes it.
            # Anything else (a 403 bad key, a 400 bad parameter) fails the same
            # way every time, so retrying would only burn through the limit.
            if response.status_code == 429:
                if attempt > self.max_retries:
                    break
                self.sleep(min(2 ** attempt, 60))
                continue
            if response.status_code != 200:
                raise FecApiError(f"{path} returned {response.status_code}: {response.text[:200]}")

            # The API reports how many requests are left in the current window.
            # Pausing at zero avoids a 429 on the next call.
            if response.headers.get("X-RateLimit-Remaining") == "0":
                self.sleep(self.cooldown_seconds)
            return response.json()

        raise FecApiError(f"{path} was still rate limited after {self.max_retries} retries")

    def iter_results(self, path, params=None, max_pages=None):
        """Yield every result from a paginated endpoint.

        Parameters
        ----------
        path : str
            Endpoint path.
        params : dict, optional
            Query parameters.
        max_pages : int, optional
            Stop after this many pages. Useful for a quick sample pull.

        Yields
        ------
        dict
            One record from the endpoint's `results` list.
        """
        page = 1
        while True:
            body = self.get(path, {**(params or {}), "page": page, "per_page": 100})
            yield from body.get("results", [])
            total_pages = body.get("pagination", {}).get("pages", 1)
            if page >= total_pages or (max_pages and page >= max_pages):
                return
            page += 1
