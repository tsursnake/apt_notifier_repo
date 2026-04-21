import json
import logging
import re
import requests
from bs4 import BeautifulSoup
from .base import Scraper

logger = logging.getLogger(__name__)

# Madlan (Compass Israel) uses a GraphQL endpoint
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

    def fetch(self) -> list[dict]:
        listings = self._fetch_graphql()
        if not listings:
            logger.warning("Madlan GraphQL returned nothing, falling back to HTML")
            listings = self._fetch_html()
        return listings

    # ------------------------------------------------------------------
    # GraphQL API (preferred)
    # ------------------------------------------------------------------

    def _fetch_graphql(self) -> list[dict]:
        headers = self.random_headers()
        headers.update(
            {
                "Referer": _SEARCH_URL,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        variables = {
            "filters": {
                "dealType": "RENT",
                "propertyTypes": ["APARTMENT"],
                "cityIds": ["5000"],
            },
            "pagination": {"page": 1, "pageSize": 40},
        }
        try:
            resp = requests.post(
                _GRAPHQL_URL,
                json={"query": _QUERY, "variables": variables},
                headers=headers,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
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

    def _fetch_html(self) -> list[dict]:
        try:
            resp = requests.get(
                _SEARCH_URL, headers=self.random_headers(), timeout=20
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Madlan HTML fetch failed: %s", exc)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
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
                items = data.get("listings") or []
                for item in items:
                    norm = self._normalize(item)
                    if norm:
                        results.append(norm)
            except Exception:
                pass

        return results
