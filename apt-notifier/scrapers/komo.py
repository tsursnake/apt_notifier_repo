import json
import logging
import re
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext
from .base import Scraper

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://komo.co.il/rent/tel-aviv"
_API_URL = "https://komo.co.il/api/listings/search"


class KomoScraper(Scraper):
    source = "komo"

    async def _fetch(self) -> list[dict]:
        async with self._browser() as ctx:
            listings = await self._fetch_api(ctx)
            if not listings:
                logger.warning("Komo API returned nothing, falling back to HTML")
                listings = await self._fetch_html(ctx)
        return listings

    # ------------------------------------------------------------------
    # Internal API (preferred)
    # ------------------------------------------------------------------

    async def _fetch_api(self, ctx: BrowserContext) -> list[dict]:
        payload = {
            "dealType": "rent",
            "propertyTypes": ["apartment"],
            "city": "תל אביב יפו",
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
                },
            )
            if not resp.ok:
                logger.error("Komo API returned %d", resp.status)
                return []
            data = await resp.json()
        except Exception as exc:
            logger.error("Komo API failed: %s", exc)
            return []

        items = data.get("listings") or data.get("results") or data.get("data") or []
        return [n for item in items if (n := self._normalize(item))]

    def _normalize(self, item: dict) -> dict | None:
        url = item.get("url") or item.get("link") or ""
        if not url:
            item_id = item.get("id") or item.get("listingId")
            if not item_id:
                return None
            url = f"https://komo.co.il/listing/{item_id}"
        if not url.startswith("http"):
            url = "https://komo.co.il" + url

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
            logger.error("Komo HTML fetch failed: %s", exc)
            return []

        soup = BeautifulSoup(html, "lxml")
        results = []

        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script and script.string:
            try:
                nd = json.loads(script.string)
                items = nd.get("props", {}).get("pageProps", {}).get("listings", [])
                for item in items:
                    norm = self._normalize(item)
                    if norm:
                        results.append(norm)
                if results:
                    return results
            except Exception:
                pass

        for script in soup.find_all("script"):
            text = script.string or ""
            match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\});", text, re.S)
            if not match:
                match = re.search(r"window\.__APP_STATE__\s*=\s*(\{.+?\});", text, re.S)
            if match:
                try:
                    state = json.loads(match.group(1))
                    for item in (state.get("listings") or []):
                        norm = self._normalize(item)
                        if norm:
                            results.append(norm)
                    if results:
                        return results
                except Exception:
                    pass

        for card in soup.select("div[class*='listing'], article[class*='listing']"):
            try:
                link = card.select_one("a[href]")
                if not link:
                    continue
                href = link["href"]
                if not href.startswith("http"):
                    href = "https://komo.co.il" + href

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
