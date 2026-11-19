"""A small, polite client for the MediaWiki Action API (English Wikipedia).

Usage:
    from wikipedia_client import WikipediaClient

    with WikipediaClient(user_agent="MyApp/1.0 (me@example.com)") as client:
        for member in client.category_members("Category:Infectious diseases"):
            print(member["title"])

What it handles for you:
    - One shared HTTP session with your User-Agent.
    - format=json, formatversion=2 and maxlag on every request.
    - Retries on HTTP 429/5xx, network errors and "maxlag" errors, using the
      server's Retry-After header if present, else waiting 1, 2, 4, 8, 16s.
    - Following `continue` tokens so you get every result, not just the first page.
    - Strictly one request at a time, with a short pause after each one.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Any

import requests

log = logging.getLogger(__name__)

DEFAULT_API_URL = "https://en.wikipedia.org/w/api.php"
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_PAGES_PER_REQUEST = 20  # the API returns intro extracts for at most 20 pages at once


class WikipediaAPIError(RuntimeError):
    """The API returned an error, or kept failing after all retries."""


class WikipediaClient:
    def __init__(
        self,
        user_agent: str,
        api_url: str = DEFAULT_API_URL,
        sleep_between: float = 0.2,
        max_retries: int = 5,
        timeout: float = 30,
        maxlag: int = 5,
    ) -> None:
        self.api_url = api_url
        self.sleep_between = sleep_between
        self.max_retries = max_retries
        self.timeout = timeout
        self.base_params = {"format": "json", "formatversion": "2", "maxlag": str(maxlag)}
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent

    # ---- lifecycle: lets you write `with WikipediaClient(...) as client:` ----

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> WikipediaClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ---- low-level requests ----

    def get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Make one API call, retrying temporary failures. Returns the JSON response."""
        full_params = {**self.base_params, **params}
        reason = ""
        for attempt in range(self.max_retries + 1):
            resp: requests.Response | None = None
            try:
                resp = self.session.get(self.api_url, params=full_params, timeout=self.timeout)
                data, reason = self._check_response(resp)
                if data is not None:
                    return data
            except (requests.ConnectionError, requests.Timeout) as exc:
                reason = f"network error: {exc}"
            finally:
                time.sleep(self.sleep_between)

            if attempt == self.max_retries:
                break
            wait = _retry_after_seconds(resp)
            if wait is None:
                wait = 2**attempt  # 1, 2, 4, 8, 16
            log.warning(
                "Request failed (%s). Retry %d/%d in %.0fs",
                reason, attempt + 1, self.max_retries, wait,
            )
            time.sleep(wait)

        raise WikipediaAPIError(f"Giving up after {self.max_retries} retries. Last error: {reason}")

    def query_all(self, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yield every response, following `continue` tokens until there are none."""
        cont: dict[str, Any] = {}
        while True:
            data = self.get({**params, **cont})
            yield data
            if "continue" not in data:
                return
            cont = data["continue"]

    @staticmethod
    def _check_response(resp: requests.Response) -> tuple[dict[str, Any] | None, str]:
        """Return (data, "") on success, or (None, reason) if the request should be retried.

        Raises for errors that retrying will not fix.
        """
        if resp.status_code in RETRY_STATUS:
            return None, f"HTTP {resp.status_code}"
        resp.raise_for_status()
        data = resp.json()
        error = data.get("error")
        if error is None:
            return data, ""
        if error.get("code") == "maxlag":
            return None, f"maxlag ({error.get('info', '')})"
        raise WikipediaAPIError(f"API error {error.get('code')}: {error.get('info')}")

    # ---- Wikipedia queries ----

    def category_members(self, category: str) -> Iterator[dict[str, Any]]:
        """Yield the articles (ns=0) and subcategories (ns=14) in a category.

        Each item looks like {"pageid": 8072, "ns": 0, "title": "Disease"}.
        """
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmlimit": "max",
            "cmtype": "page|subcat",
            "cmnamespace": "0|14",
        }
        for data in self.query_all(params):
            yield from data.get("query", {}).get("categorymembers", [])

    def fetch_pages(self, page_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Fetch intro text, URL, size and last-edit time for up to 20 pages.

        Returns {page_id: page_data}. Pages that no longer exist are left out.
        """
        if len(page_ids) > MAX_PAGES_PER_REQUEST:
            raise ValueError(f"At most {MAX_PAGES_PER_REQUEST} page IDs per call, got {len(page_ids)}")
        params = {
            "action": "query",
            "pageids": "|".join(str(pid) for pid in page_ids),
            "prop": "extracts|info|revisions",
            "exintro": "1",
            "explaintext": "1",
            "exlimit": str(MAX_PAGES_PER_REQUEST),
            "inprop": "url",
            "rvprop": "timestamp",
        }
        merged: dict[int, dict[str, Any]] = {}
        for data in self.query_all(params):
            for page in data.get("query", {}).get("pages", []):
                if page.get("missing") or "pageid" not in page:
                    continue  # deleted since we found it
                _merge_page(merged.setdefault(page["pageid"], {}), page)
        return merged


def _merge_page(target: dict[str, Any], page: dict[str, Any]) -> None:
    """Merge one continuation response's page data into what we already have.

    A later response must not wipe a value (e.g. an extract) we already received.
    """
    for key, value in page.items():
        if value or key not in target:
            target[key] = value


def _retry_after_seconds(resp: requests.Response | None) -> float | None:
    """Read the Retry-After header (seconds or an HTTP date). None if absent/invalid."""
    if resp is None:
        return None
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
