"""
LinkedIn Session Manager.

Logs in once using Playwright, saves browser storage state (cookies +
localStorage) to linkedin_state.json, and reuses it for up to 12 hours.

Usage:
    from linkedin_session import LinkedInSession, ensure_session

    # Login / refresh if needed
    ok = ensure_session(email, password)

    # Use in scraper
    with LinkedInSession() as session:
        html = session.fetch("https://www.linkedin.com/jobs/search/?keywords=...")
"""
import json
import os
import random
import time

_DIR = os.path.dirname(os.path.abspath(__file__))
_STATE_FILE = os.path.join(_DIR, "linkedin_state.json")
_SESSION_MAX_AGE = 12 * 3600  # 12 hours


def _state_is_fresh() -> bool:
    if not os.path.exists(_STATE_FILE):
        return False
    return (time.time() - os.path.getmtime(_STATE_FILE)) < _SESSION_MAX_AGE


def ensure_session(email: str, password: str) -> bool:
    """
    Make sure a valid LinkedIn session exists.
    Logs in fresh if state file is missing or expired.
    Returns True if session is ready.
    """
    if not email or not password:
        return False
    if _state_is_fresh():
        print("  [LinkedIn] Reusing saved session (< 12h old).")
        return True
    return _login_and_save(email, password)


def _login_and_save(email: str, password: str) -> bool:
    """Login to LinkedIn with Playwright, save storage state. Returns True on success."""
    from playwright.sync_api import sync_playwright

    print("  [LinkedIn] Logging in as " + email + " ...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = ctx.new_page()

        try:
            page.goto(
                "https://www.linkedin.com/login",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            time.sleep(random.uniform(1.5, 3.0))

            page.fill("#username", email)
            time.sleep(random.uniform(0.8, 1.8))
            page.fill("#password", password)
            time.sleep(random.uniform(0.5, 1.2))
            page.click('button[type="submit"]')

            # Wait for redirect away from /login
            page.wait_for_function(
                "!window.location.href.includes('/login')",
                timeout=30000,
            )
            time.sleep(random.uniform(2.0, 3.5))

            current = page.url
            if "checkpoint" in current or "challenge" in current:
                print("  [LinkedIn] ⚠ Checkpoint / 2FA detected.")
                print("  Solve it manually in a real browser, then paste the")
                print("  session cookies into linkedin_state.json, or try again.")
                browser.close()
                return False

            # Save full browser state (cookies + localStorage)
            ctx.storage_state(path=_STATE_FILE)
            print("  [LinkedIn] Logged in. State saved to linkedin_state.json")
            return True

        except Exception as e:
            print("  [LinkedIn] Login failed: " + str(e)[:100])
            return False
        finally:
            browser.close()


def clear_session():
    """Delete saved session — forces re-login on next run."""
    if os.path.exists(_STATE_FILE):
        os.remove(_STATE_FILE)
        print("  [LinkedIn] Session cleared.")
    else:
        print("  [LinkedIn] No session file found.")


# ---------------------------------------------------------------------------
# Session context manager — keeps ONE browser open for the entire scraper run
# ---------------------------------------------------------------------------

class LinkedInSession:
    """
    Context manager that holds an open Playwright browser/page with the
    saved LinkedIn session. All fetch() calls share this single page.

    with LinkedInSession() as session:
        html = session.fetch(url)
    """

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().__enter__()
        self._browser = self._pw.chromium.launch(
            headless=self._headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        self._ctx = self._browser.new_context(
            storage_state=_STATE_FILE,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/New_York",
        )
        self._page = self._ctx.new_page()

        # Block heavy assets to speed up scraping
        self._page.route(
            "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,mp3}",
            lambda route: route.abort(),
        )
        return self

    def fetch(self, url: str, wait_ms: int = 2500) -> str:
        """
        Navigate to url, wait for JS rendering, return page HTML.
        Detects session expiry (redirect to /login).
        """
        _JOB_CARD_SELECTORS = [
            "li.jobs-search-results__list-item",
            "li[data-occludable-job-id]",
            "li.scaffold-layout__list-item",
            "div.base-card",
            "div.job-search-card",
        ]
        try:
            # domcontentloaded is correct — networkidle always times out on
            # LinkedIn because it never stops making background requests.
            self._page.goto(url, wait_until="domcontentloaded", timeout=20000)

            current = self._page.url
            if "/login" in current or "/authwall" in current:
                print("  [LinkedIn] ⚠ Session expired — delete linkedin_state.json and re-run.")
                return ""

            # Try to wait for job cards. If none appear within 5s (no results
            # for this query), just fall through and return whatever is loaded.
            cards_found = False
            for sel in _JOB_CARD_SELECTORS:
                try:
                    self._page.wait_for_selector(sel, timeout=5000)
                    cards_found = True
                    break
                except Exception:
                    continue

            if not cards_found:
                time.sleep(wait_ms / 1000.0)

            # Scroll to trigger lazy-loaded cards
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            time.sleep(random.uniform(0.5, 1.2))

            return self._page.content()
        except Exception as e:
            print("  [LinkedIn] fetch error: " + str(e)[:80])
            return ""

    def is_ready(self) -> bool:
        return self._page is not None

    def __exit__(self, *args):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.__exit__(None, None, None)
        except Exception:
            pass


if __name__ == "__main__":
    from config import LINKEDIN_EMAIL, LINKEDIN_PASS
    ok = ensure_session(LINKEDIN_EMAIL, LINKEDIN_PASS)
    if ok:
        print("Session ready. Testing a fetch...")
        with LinkedInSession() as s:
            html = s.fetch("https://www.linkedin.com/feed/")
            print("Feed page length: " + str(len(html)) + " chars")
    else:
        print("Session setup failed.")
