import json
import logging
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext
from .base import Scraper

logger = logging.getLogger(__name__)

_GRAPHQL_URL = "https://www.madlan.co.il/api/graphql"
_SEARCH_URL = "https://www.madlan.co.il/for-rent/apartments/תל-אביב-יפו"

_QUERY = """
query SearchListings($filters: ListingSearchFilters!, $pagination: PaginationInput) {
  searchListings(filters: $filters, pagination: $pagination) {
    listings {
      id
      price
      rooms
      floor
      squareMeters
      neighborhood { name }
      address { street houseNumber }
      description
      url
    }
    totalCount
  }
}
"""


class MadlanScraper(Scraper):
    source = "madlan"

    async def _fetch(self) -> list[dict]:
        async with self._browser() as ctx:
            listings = await self._fetch_graphql(ctx)
            if not listings:
                logger.warning("Madlan GraphQL returned nothing, falling back to HTML")
                listings = await self._fetch_html(ctx)
        return listings

    # ------------------------------------------------------------------
    # GraphQL API (preferred)
    # ------------------------------------------------------------------

    async def _fetch_graphql(self, ctx: BrowserContext) -> list[dict]:
        variables = {
            "filters": {
                "dealType": "RENT",
                "propertyTypes": ["APARTMENT"],
                "cityIds": ["5000"],
            },
            "pagination": {"page": 1, "pageSize": 40},
        }
        body = json.dumps({"query": _QUERY, "variables": variables})
        try:
            resp = await ctx.request.post(
                _GRAPHQL_URL,
                data=body,
                headers={
                    "Referer": _SEARCH_URL,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            if not resp.ok:
                logger.error("Madlan GraphQL returned %d", resp.status)
                return []
            data = await resp.json()
        except Exception as exc:
            logger.error("Madlan GraphQL failed: %s", exc)
            return []

        items = (
            data.get("data", {})
            .get("searchListings", {})
            .get("listings", [])
        )
        return [n for item in items if (n := self._normalize(item))]

    def _normalize(self, item: dict) -> dict | None:
        url = item.get("url") or ""
        if not url:
            item_id = item.get("id")
            if not item_id:
                return None
            url = f"https://www.madlan.co.il/listing/{item_id}"
        if not url.startswith("http"):
            url = "https://www.madlan.co.il" + url

        price_raw = item.get("price")
        try:
            price = int(str(price_raw).replace(",", "").strip())
        except (TypeError, ValueError):
            price = None

        rooms_raw = item.get("rooms")
        try:
            rooms = float(rooms_raw)
        except (TypeError, ValueError):
            rooms = None

        size_raw = item.get("squareMeters") or item.get("size_m2")
        try:
            size_m2 = int(size_raw)
        except (TypeError, ValueError):
            size_m2 = None

        neighborhood = ""
        nbhood = item.get("neighborhood")
        if isinstance(nbhood, dict):
            neighborhood = nbhood.get("name", "")
        elif isinstance(nbhood, str):
            neighborhood = nbhood

        raw_text = item.get("description") or json.dumps(item, ensure_ascii=False)
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
            logger.error("Madlan HTML fetch failed: %s", exc)
            return []

        soup = BeautifulSoup(html, "lxml")
        results = []

        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script and script.string:
            try:
                next_data = json.loads(script.string)
                listings_raw = (
                    next_data.get("props", {})
                    .get("pageProps", {})
                    .get("initialData", {})
                    .get("searchListings", {})
                    .get("listings", [])
                )
                for item in listings_raw:
                    norm = self._normalize(item)
                    if norm:
                        results.append(norm)
                if results:
                    return results
            except Exception as exc:
                logger.warning("Madlan __NEXT_DATA__ parse failed: %s", exc)

        for script in soup.find_all("script", type="application/json"):
            text = script.string or ""
            if "listings" not in text:
                continue
            try:
                data = json.loads(text)
                for item in (data.get("listings") or []):
                    norm = self._normalize(item)
                    if norm:
                        results.append(norm)
            except Exception:
                pass

        return results
