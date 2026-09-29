import pytest
import requests

from digest import http

pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, status: int = 200, text: str = ""):
        self.status_code, self.text = status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


@pytest.fixture(autouse=True)
def fresh_robots_cache():
    http._robots_for.cache_clear()
    yield
    http._robots_for.cache_clear()


def _serve(monkeypatch, routes: dict):
    def fake_get(url, params=None, timeout=None):
        answer = routes.get(url, FakeResponse(200, "<html>page</html>"))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(http._session, "get", fake_get)


def test_robots_txt_rules_are_respected(monkeypatch):
    _serve(monkeypatch, {"https://site.com/robots.txt": FakeResponse(200, "User-agent: *\nDisallow: /private")})
    assert http.is_allowed("https://site.com/news/1")
    assert not http.is_allowed("https://site.com/private/2")
    with pytest.raises(http.FetchError, match="robots.txt disallows"):
        http.get("https://site.com/private/2", check_robots=True)


@pytest.mark.parametrize("robots", [FakeResponse(404), requests.ConnectionError("down")])
def test_missing_robots_txt_means_allowed(monkeypatch, robots):
    _serve(monkeypatch, {"https://site.com/robots.txt": robots})
    assert http.is_allowed("https://site.com/anything")


def test_get_returns_page_and_wraps_http_errors(monkeypatch):
    _serve(monkeypatch, {"https://site.com/broken": FakeResponse(500)})
    assert http.get("https://site.com/ok").text == "<html>page</html>"
    with pytest.raises(http.FetchError, match="500"):
        http.get("https://site.com/broken")


def test_polite_pause_waits(monkeypatch):
    waited = []
    monkeypatch.setattr(http.time, "sleep", waited.append)
    http.polite_pause()
    assert waited == [http.POLITE_DELAY_SECONDS]
