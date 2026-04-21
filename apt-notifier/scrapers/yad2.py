import json
import logging
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext
from .base import Scraper

logger = logging.getLogger(__name__)

# Updated endpoint with filter params so the API returns pre-filtered results
_API_URL = (
    "https://gw.yad2.co.il/feed-search-legacy/realestate/rent"
    "?city=5000&roomsMin=2&roomsMax=4&priceMin=5000&priceMax=9000"
)
_SEARCH_URL = "https://www.yad2.co.il/realestate/rent?city=5000"
_BASE_LISTING_URL = "https://www.yad2.co.il/item/"


class Yad2Scraper(Scraper):
    source = "yad2"

    async def _fetch(self) -> list[dict]:
        async with self._browser() as ctx:
            listings = await self._fetch_api(ctx)
            if not listings:
                logger.warning("Yad2 API returned nothing, falling back to HTML scrape")
                listings = await self._fetch_html(ctx)
        return listings

    # ------------------------------------------------------------------
    # Internal JSON API (preferred)
    # ------------------------------------------------------------------

    async def _fetch_api(self, ctx: BrowserContext) -> list[dict]:
        try:
            resp = await ctx.request.get(
                _API_URL,
                headers={
                    "Referer": "https://www.yad2.co.il/realestate/rent",
                    "Origin": "https://www.yad2.co.il",
                    "Accept": "application/json, text/plain, */*",
                },
            )
            if not resp.ok:
                logger.error("Yad2 API returned %d", resp.status)
                return []
            data = await resp.json()
        except Exception as exc:
            logger.error("Yad2 API request failed: %s", exc)
            return []

        items = data.get("data", {}).get("feed", {}).get("feed_items", [])
        if not items:
            # Some API responses wrap feed_items inside pages[]
            pages = data.get("data", {}).get("feed", {}).get("pages", [])
            for page in pages:
                if isinstance(page, dict):
                    items.extend(page.get("feed_items", []))

        logger.info("Yad2 API: got %d raw feed items", len(items))
        return [n for item in items if item.get("type") == "ad" and (n := self._normalize_api_item(item))]

    def _normalize_api_item(self, item: dict) -> dict | None:
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
    # HTML fallback
    # ------------------------------------------------------------------

    async def _fetch_html(self, ctx: BrowserContext) -> list[dict]:
        try:
            html = await self._get_html(ctx, _SEARCH_URL)
        except Exception as exc:
            logger.error("Yad2 HTML fallback failed: %s", exc)
            return []

        soup = BeautifulSoup(html, "lxml")
        results = []

        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not (script and script.string):
            logger.warning("Yad2: no __NEXT_DATA__ script found in page")
        else:
            try:
                next_data = json.loads(script.string)
                # Debug: log the raw structure so we can see what Yad2 actually returns
                logger.debug(
                    "Yad2 __NEXT_DATA__ (first 2000 chars): %s",
                    json.dumps(next_data, ensure_ascii=False)[:2000],
                )
                feed_items = self._extract_feed_items(next_data)
                logger.info("Yad2 HTML: extracted %d feed items from __NEXT_DATA__", len(feed_items))
                for item in feed_items:
                    if item.get("type") == "ad":
                        listing = self._normalize_api_item(item)
                        if listing:
                            results.append(listing)
                if results:
                    return results
            except Exception as exc:
                logger.warning("Yad2 __NEXT_DATA__ parse failed: %s", exc)

        # Last-resort: visible feed cards (JS-rendered, may be empty in headless)
        for card in soup.select("div[class*='feeditem'], div[class*='feed-item']"):
            try:
                link_tag = card.select_one("a[href]")
                href = link_tag["href"] if link_tag else ""
                if not href.startswith("http"):
                    href = "https://www.yad2.co.il" + href

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

    def _extract_feed_items(self, next_data: dict) -> list:
        """Try every known __NEXT_DATA__ shape Yad2 has used, then recurse."""
        dehydrated = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("dehydratedState", {})
        )
        if not isinstance(dehydrated, dict):
            logger.debug("Yad2: dehydratedState is not a dict: %s", type(dehydrated))
            return _recursive_find_list(next_data, "feed_items")

        queries = dehydrated.get("queries", [])
        logger.debug("Yad2: found %d queries in dehydratedState", len(queries))

        for i, query in enumerate(queries):
            if not isinstance(query, dict):
                logger.debug("Yad2: queries[%d] is %s, skipping", i, type(query))
                continue

            state = query.get("state", {})
            if not isinstance(state, dict):
                continue

            data = state.get("data")
            if data is None:
                continue

            # Shape 1: data.feed.feed_items (standard)
            if isinstance(data, dict):
                feed = data.get("feed", {})
                if isinstance(feed, dict):
                    items = feed.get("feed_items", [])
                    if items:
                        logger.debug("Yad2: found feed_items via queries[%d].state.data.feed", i)
                        return items

                # Shape 2: data.pages[].feed.feed_items (infinite query / pagination)
                pages = data.get("pages", [])
                if pages:
                    combined = []
                    for page in pages:
                        if isinstance(page, dict):
                            combined.extend(
                                page.get("feed", {}).get("feed_items", [])
                            )
                    if combined:
                        logger.debug("Yad2: found feed_items via queries[%d] paginated pages", i)
                        return combined

            # Shape 3: data is a list of feed items directly
            if isinstance(data, list) and data and isinstance(data[0], dict) and "type" in data[0]:
                logger.debug("Yad2: data is a direct list at queries[%d]", i)
                return data

        # Nuclear fallback: walk the whole JSON tree
        logger.debug("Yad2: falling back to recursive search for feed_items")
        return _recursive_find_list(next_data, "feed_items")


def _recursive_find_list(obj, key: str) -> list:
    """Return the first list value found for `key` anywhere in the JSON tree."""
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
