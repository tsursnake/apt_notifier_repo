import json
import logging
import re
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext
from .base import Scraper

logger = logging.getLogger(__name__)

# winwin.co.il replaced the dead windo.co.il domain
_SEARCH_URL = "https://www.winwin.co.il/RealEstate/ForRent?cityId=5000"
_API_URL     = "https://www.winwin.co.il/api/RealEstate/Search"


class WinwinScraper(Scraper):
    source = "winwin"

    async def _fetch(self) -> list[dict]:
        async with self._browser() as ctx:
            listings = await self._fetch_api(ctx)
            if not listings:
                logger.warning("Winwin API returned nothing, falling back to HTML")
                listings = await self._fetch_html(ctx)
        return listings

    # ------------------------------------------------------------------
    # Internal API (preferred)
    # ------------------------------------------------------------------

    async def _fetch_api(self, ctx: BrowserContext) -> list[dict]:
        payload = {
            "dealType": "ForRent",
            "cityId": 5000,
            "propertyTypes": ["Apartment"],
            "pageNumber": 1,
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
                },
            )
            if not resp.ok:
                logger.warning("Winwin API: %d", resp.status)
                return []
            data = await resp.json()
        except Exception as exc:
            logger.warning("Winwin API failed: %s", exc)
            return []

        items = (
            data.get("items")
            or data.get("results")
            or data.get("listings")
            or data.get("data")
            or []
        )
        return [n for item in items if (n := self._normalize(item))]

    def _normalize(self, item: dict) -> dict | None:
        url = item.get("url") or item.get("link") or item.get("detailUrl") or ""
        if not url:
            item_id = item.get("id") or item.get("listingId")
            if not item_id:
                return None
            url = f"https://www.winwin.co.il/RealEstate/Details/{item_id}"
        if not url.startswith("http"):
            url = "https://www.winwin.co.il" + url

        price_raw = item.get("price") or item.get("rent") or item.get("monthlyRent")
        try:
            price = int(str(price_raw).replace(",", "").strip())
        except (TypeError, ValueError):
            price = None

        rooms_raw = item.get("rooms") or item.get("roomsCount") or item.get("numRooms")
        try:
            rooms = float(rooms_raw)
        except (TypeError, ValueError):
            rooms = None

        size_raw = (
            item.get("squareMeters")
            or item.get("size")
            or item.get("area")
            or item.get("sqm")
        )
        try:
            size_m2 = int(size_raw)
        except (TypeError, ValueError):
            size_m2 = None

        neighborhood = (
            item.get("neighborhood")
            or item.get("neighborhoodName")
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
            logger.error("Winwin HTML fetch failed: %s", exc)
            return []

        soup = BeautifulSoup(html, "lxml")
        results = []

        # ASP.NET / Angular apps often embed data in a window variable or JSON script
        for script in soup.find_all("script"):
            text = script.string or ""
            for pattern in [
                r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\});",
                r"window\.appData\s*=\s*(\{.+?\});",
                r"var\s+searchResults\s*=\s*(\[.+?\]);",
            ]:
                match = re.search(pattern, text, re.S)
                if match:
                    try:
                        blob = json.loads(match.group(1))
                        items = (
                            blob if isinstance(blob, list)
                            else blob.get("listings") or blob.get("results") or []
                        )
                        for item in items:
                            norm = self._normalize(item)
                            if norm:
                                results.append(norm)
                        if results:
                            return results
                    except Exception:
                        pass

        # Generic card scrape
        for card in soup.select(
            "div[class*='listing'], article[class*='property'], li[class*='item']"
        ):
            try:
                link = card.select_one("a[href]")
                if not link:
                    continue
                href = link["href"]
                if not href.startswith("http"):
                    href = "https://www.winwin.co.il" + href

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
