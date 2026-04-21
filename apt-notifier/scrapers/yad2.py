import asyncio
import json
import logging
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext
from .base import Scraper

logger = logging.getLogger(__name__)

_HOME_URL   = "https://www.yad2.co.il/"
_SEARCH_URL = "https://www.yad2.co.il/realestate/rent?city=5000"
_BASE_LISTING_URL = "https://www.yad2.co.il/item/"

# Selectors for rendered feed cards; tried in order
_FEED_SELECTORS = [
    '[data-testid="feed-item"]',
    '.feed_item',
    '[class*="feeditem"]',
    '[class*="feed-item"]',
]


class Yad2Scraper(Scraper):
    source = "yad2"

    async def _fetch(self) -> list[dict]:
        async with self._browser() as ctx:
            return await self._fetch_page(ctx)

    async def _fetch_page(self, ctx: BrowserContext) -> list[dict]:
        page = await ctx.new_page()
        try:
            # Simulate human navigation: homepage → search (not a direct deep link)
            logger.info("Yad2: visiting homepage first")
            await page.goto(_HOME_URL, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(3)

            logger.info("Yad2: navigating to search page")
            await page.goto(_SEARCH_URL, wait_until="networkidle", timeout=45_000)

            # Wait for at least one feed card to appear
            found_selector = None
            for sel in _FEED_SELECTORS:
                try:
                    await page.wait_for_selector(sel, timeout=15_000)
                    found_selector = sel
                    logger.info("Yad2: feed selector matched: %s", sel)
                    break
                except Exception:
                    continue

            if not found_selector:
                logger.warning("Yad2: no feed selector matched within 15s")

            html = await page.content()
            title = await page.title()
            logger.info("Yad2 page title: %s", title)
            logger.info("Yad2 page content (first 500 chars):\n%s", html[:500])

        except Exception as exc:
            logger.error("Yad2 page navigation failed: %s", exc)
            return []
        finally:
            await page.close()

        return self._parse_html(html)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_html(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        # Primary: __NEXT_DATA__ (server-rendered, present regardless of JS state)
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script and script.string:
            try:
                next_data = json.loads(script.string)
                logger.debug(
                    "Yad2 __NEXT_DATA__ (first 2000 chars): %s",
                    json.dumps(next_data, ensure_ascii=False)[:2000],
                )
                feed_items = _extract_feed_items(next_data)
                logger.info("Yad2 __NEXT_DATA__: %d feed items", len(feed_items))
                for item in feed_items:
                    if item.get("type") == "ad":
                        norm = self._normalize(item)
                        if norm:
                            results.append(norm)
                if results:
                    return results
            except Exception as exc:
                logger.warning("Yad2 __NEXT_DATA__ parse failed: %s", exc)

        # Fallback: rendered card elements (only present after JS executes)
        for card in soup.select(
            '[data-testid="feed-item"], .feed_item, [class*="feeditem"], [class*="feed-item"]'
        ):
            try:
                link_tag = card.select_one("a[href]")
                href = (link_tag["href"] if link_tag else "") or ""
                if not href.startswith("http"):
                    href = "https://www.yad2.co.il" + href
                if not href:
                    continue

                price = None
                price_tag = card.select_one("[class*='price']")
                if price_tag:
                    try:
                        price = int("".join(filter(str.isdigit, price_tag.get_text())))
                    except ValueError:
                        pass

                results.append({
                    "url": href,
                    "price": price,
                    "rooms": None,
                    "size_m2": None,
                    "neighborhood": "",
                    "raw_text": card.get_text(" ", strip=True),
                    "source": self.source,
                })
            except Exception:
                continue

        return results

    def _normalize(self, item: dict) -> dict | None:
        token = item.get("id") or item.get("orderId")
        if not token:
            return None
        url = _BASE_LISTING_URL + str(token)

        price_raw = item.get("price")
        try:
            price = int(str(price_raw).replace(",", "").replace("₪", "").strip())
        except (TypeError, ValueError):
            price = None

        rooms_raw = item.get("rooms")
        try:
            rooms = float(rooms_raw)
        except (TypeError, ValueError):
            rooms = None

        size_raw = item.get("square_meters") or item.get("squareMeter")
        try:
            size_m2 = int(size_raw)
        except (TypeError, ValueError):
            size_m2 = None

        neighborhood = (
            item.get("neighborhood")
            or item.get("area_name")
            or item.get("city_area")
            or ""
        )

        raw_parts = [
            item.get("title", ""),
            item.get("subtitle", ""),
            item.get("info_bar_text", ""),
            item.get("row_1", ""),
            item.get("row_2", ""),
            item.get("row_3", ""),
        ]
        raw_text = " | ".join(p for p in raw_parts if p)

        return {
            "url": url,
            "price": price,
            "rooms": rooms,
            "size_m2": size_m2,
            "neighborhood": neighborhood,
            "raw_text": raw_text,
            "source": self.source,
        }


# ------------------------------------------------------------------
# __NEXT_DATA__ extraction helpers (module-level, shared with tests)
# ------------------------------------------------------------------

def _extract_feed_items(next_data: dict) -> list:
    """Try every known dehydratedState shape; recurse as last resort."""
    dehydrated = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("dehydratedState", {})
    )
    if not isinstance(dehydrated, dict):
        return _recursive_find_list(next_data, "feed_items")

    for i, query in enumerate(dehydrated.get("queries", [])):
        if not isinstance(query, dict):
            continue
        state = query.get("state", {})
        if not isinstance(state, dict):
            continue
        data = state.get("data")
        if data is None:
            continue

        if isinstance(data, dict):
            # Shape 1: data.feed.feed_items
            feed = data.get("feed", {})
            if isinstance(feed, dict):
                items = feed.get("feed_items", [])
                if items:
                    logger.debug("Yad2: feed_items at queries[%d].state.data.feed", i)
                    return items
            # Shape 2: paginated — data.pages[].feed.feed_items
            combined = []
            for page in data.get("pages", []):
                if isinstance(page, dict):
                    combined.extend(page.get("feed", {}).get("feed_items", []))
            if combined:
                logger.debug("Yad2: feed_items via paginated pages at queries[%d]", i)
                return combined

        # Shape 3: data is already the list
        if isinstance(data, list) and data and isinstance(data[0], dict) and "type" in data[0]:
            return data

    return _recursive_find_list(next_data, "feed_items")


def _recursive_find_list(obj, key: str) -> list:
    """Return the first list value for `key` found anywhere in the JSON tree."""
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], list):
            return obj[key]
        for v in obj.values():
            result = _recursive_find_list(v, key)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _recursive_find_list(item, key)
            if result:
                return result
    return []
