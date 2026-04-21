import asyncio
import random
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright, BrowserContext

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


class Scraper(ABC):
    source: str = ""

    @asynccontextmanager
    async def _browser(self):
        """Yield a Playwright BrowserContext with realistic browser headers."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
                ignore_default_args=["--enable-automation"],
            )
            ctx = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="he-IL",
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={
                    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )
            # Hide the headless fingerprint from JS-based bot detectors
            await ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            try:
                yield ctx
            finally:
                await browser.close()

    async def _get_html(self, ctx: BrowserContext, url: str) -> str:
        """Navigate to url and return the fully-rendered page HTML."""
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            return await page.content()
        finally:
            await page.close()

    def fetch(self) -> list[dict]:
        """Synchronous entry point — wraps the async implementation."""
        return asyncio.run(self._fetch())

    @abstractmethod
    async def _fetch(self) -> list[dict]:
        """Async implementation; override in each scraper.

        Return normalized dicts with keys:
            url, price, rooms, size_m2, neighborhood, raw_text, source
        """

    def polite_sleep(self) -> None:
        time.sleep(random.uniform(30, 90))
