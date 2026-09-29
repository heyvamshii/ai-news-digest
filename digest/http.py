"""Polite HTTP: one shared session, robots.txt checks and a small delay."""

import time
from functools import lru_cache
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from config import POLITE_DELAY_SECONDS, REQUEST_TIMEOUT, USER_AGENT

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


class FetchError(Exception):
    """Raised when a page could not be downloaded."""


@lru_cache(maxsize=64)
def _robots_for(origin: str) -> RobotFileParser | None:
    parser = RobotFileParser()
    try:
        response = _session.get(f"{origin}/robots.txt", timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        return None                     # no robots.txt reachable -> treat as allowed
    if response.status_code >= 400:
        return None
    parser.parse(response.text.splitlines())
    return parser


def is_allowed(url: str) -> bool:
    """Respect the site's robots.txt before scraping a page."""
    parts = urlsplit(url)
    parser = _robots_for(f"{parts.scheme}://{parts.netloc}")
    return parser is None or parser.can_fetch(USER_AGENT, url)


def get(url: str, *, params: dict | None = None, check_robots: bool = False) -> requests.Response:
    if check_robots and not is_allowed(url):
        raise FetchError(f"robots.txt disallows {url}")
    try:
        response = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FetchError(f"{url}: {exc}") from exc
    return response


def polite_pause() -> None:
    time.sleep(POLITE_DELAY_SECONDS)
