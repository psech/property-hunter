"""Polite page fetching: httpx for server-rendered sites, headless Chromium for JS-rendered ones."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 property-hunter/0.1 (+https://github.com/psech/property-hunter)"
)
DEBUG_DIR = Path("debug")


class FetchError(RuntimeError):
    pass


class Fetcher:
    def __init__(self, delay_s: float = 1.5):
        self.delay_s = delay_s
        self.http = httpx.Client(
            timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-AU,en;q=0.9"}
        )
        self._robots: dict[str, RobotFileParser] = {}
        self._last: dict[str, float] = {}
        self._playwright = None
        self._browser = None

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self.http.close()

    def allowed(self, url: str) -> bool:
        host = urlparse(url).netloc
        if host not in self._robots:
            parser = RobotFileParser()
            try:
                r = self.http.get(f"{urlparse(url).scheme}://{host}/robots.txt")
                parser.parse(r.text.splitlines() if r.status_code == 200 else [])
            except httpx.HTTPError:
                parser.parse([])
            self._robots[host] = parser
        return self._robots[host].can_fetch(USER_AGENT, url)

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        wait = self.delay_s - (time.monotonic() - self._last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    def get(self, url: str, method: str = "httpx", wait_for: str | None = None) -> str:
        if not self.allowed(url):
            raise FetchError(f"robots.txt disallows {url}")
        self._throttle(url)
        if method == "playwright":
            return self._get_browser(url, wait_for)
        try:
            r = self.http.get(url)
            r.raise_for_status()
            return r.text
        except httpx.HTTPError as exc:
            raise FetchError(f"{url}: {exc}") from exc

    def get_json(self, url: str, params: dict | None = None) -> object:
        if not self.allowed(url):
            raise FetchError(f"robots.txt disallows {url}")
        self._throttle(url)
        try:
            r = self.http.get(url, params=params, headers={"Accept": "application/json"})
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FetchError(f"{url}: {exc}") from exc

    def _get_browser(self, url: str, wait_for: str | None) -> str:
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch()
        page = self._browser.new_page(user_agent=USER_AGENT, locale="en-AU")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=20_000)
            else:
                page.wait_for_load_state("networkidle", timeout=20_000)
            return page.content()
        except Exception as exc:
            save_debug(url, page.content() if not page.is_closed() else "", page)
            raise FetchError(f"{url}: {exc}") from exc
        finally:
            page.close()


def save_debug(url: str, html: str, page=None) -> None:
    """Keeps the evidence when a page can't be parsed; the workflow uploads debug/ as an artifact."""
    DEBUG_DIR.mkdir(exist_ok=True)
    stem = re.sub(r"[^\w]+", "_", urlparse(url).netloc + urlparse(url).path).strip("_")[:120]
    (DEBUG_DIR / f"{stem}.html").write_text(html or "")
    if page is not None:
        try:
            page.screenshot(path=str(DEBUG_DIR / f"{stem}.png"), full_page=True)
        except Exception:  # best effort only
            pass


def links(html: str, base_url: str, selector: str) -> list[str]:
    from selectolax.lexbor import LexborHTMLParser as HTMLParser

    seen: dict[str, None] = {}
    for node in HTMLParser(html).css(selector):
        if href := node.attributes.get("href"):
            seen.setdefault(urljoin(base_url, href).split("#")[0], None)
    return list(seen)
