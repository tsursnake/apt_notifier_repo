import json
import logging
import re
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext
from .base import Scraper

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.homeless.co.il/rent/apartments/tel-aviv/"
_API_URL = "https://www.homeless.co.il/api/realestate/search/"


class HomelessScraper(Scraper):
    source = "homeless"

    async def _fetch(self) -> list[dict]:
        async with self._browser() as ctx:
            listings = await self._fetch_api(ctx)
            if not listings:
                logger.warning("Homeless API returned nothing, falling back to HTML")
                listings = await self._fetch_html(ctx)
        return listings

    # ------------------------------------------------------------------
    # Internal API (preferred)
    # ------------------------------------------------------------------

    async def _fetch_api(self, ctx: BrowserContext) -> list[dict]:
        payload = {
            "dealType": "rent",
            "propertyTypes": ["apartment"],
            "cities": ["תל אביב יפו"],
            "page": 1,
            "pageSize": 40,
        }
        try:
            resp = await ctx.request.post(
                _API_URL,
                data=json.dumps(payload),
                headers={
                    "Referer": _SEARCH_URL,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/plain, */*",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            if not resp.ok:
                logger.error("Homeless API returned %d", resp.status)
                return []
            data = await resp.json()
        except Exception as exc:
            logger.error("Homeless API request failed: %s", exc)
            return []

        items = data.get("results") or data.get("items") or data.get("data") or []
        return [n for item in items if (n := self._normalize(item))]

    def _normalize(self, item: dict) -> dict | None:
        url = item.get("url") or item.get("link") or ""
        if not url:
            item_id = item.get("id") or item.get("adId")
            if not item_id:
                return None
            url = f"https://www.homeless.co.il/item/{item_id}"
        if not url.startswith("http"):
            url = "https://www.homeless.co.il" + url

        price_raw = item.get("price") or item.get("rent")
        try:
            price = int(str(price_raw).replace(",", "").strip())
        except (TypeError, ValueError):
            price = None

        rooms_raw = item.get("rooms") or item.get("roomsCount")
        try:
            rooms = float(rooms_raw)
        except (TypeError, ValueError):
            rooms = None

        size_raw = item.get("squareMeter") or item.get("size") or item.get("area")
        try:
            size_m2 = int(size_raw)
        except (TypeError, ValueError):
            size_m2 = None

        neighborhood = (
            item.get("neighborhood")
            or item.get("area")
            or item.get("cityArea")
            or ""
        )

        raw_text = item.get("description") or item.get("title") or json.dumps(item)
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
            logger.error("Homeless HTML fetch failed: %s", exc)
            return []

        soup = BeautifulSoup(html, "lxml")
        results = []

        for script in soup.find_all("script"):
            text = script.string or ""
            match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\});", text, re.S)
            if match:
                try:
                    state = json.loads(match.group(1))
                    items = state.get("search", {}).get("results", {}).get("items", [])
                    for item in items:
                        norm = self._normalize(item)
                        if norm:
                            results.append(norm)
                    if results:
                        return results
                except Exception:
                    pass

        for card in soup.select("article, div[class*='listing'], li[class*='item']"):
            try:
                link = card.select_one("a[href]")
                if not link:
                    continue
                href = link["href"]
                if not href.startswith("http"):
                    href = "https://www.homeless.co.il" + href

                price = None
                price_tag = card.select_one("[class*='price']")
                if price_tag:
                    digits = "".join(filter(str.isdigit, price_tag.get_text()))
                    if digits:
                        price = int(digits)

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
