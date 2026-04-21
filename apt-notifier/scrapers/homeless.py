import json
import logging
import re
import requests
from bs4 import BeautifulSoup
from .base import Scraper

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.homeless.co.il/rent/apartments/tel-aviv/"
_API_URL = "https://www.homeless.co.il/api/realestate/search/"


class HomelessScraper(Scraper):
    source = "homeless"

    def fetch(self) -> list[dict]:
        listings = self._fetch_api()
        if not listings:
            logger.warning("Homeless API returned nothing, falling back to HTML")
            listings = self._fetch_html()
        return listings

    # ------------------------------------------------------------------
    # Internal API (preferred)
    # ------------------------------------------------------------------

    def _fetch_api(self) -> list[dict]:
        headers = self.random_headers()
        headers.update(
            {
                "Referer": _SEARCH_URL,
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        payload = {
            "dealType": "rent",
            "propertyTypes": ["apartment"],
            "cities": ["תל אביב יפו"],
            "page": 1,
            "pageSize": 40,
        }
        try:
            resp = requests.post(_API_URL, json=payload, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("Homeless API request failed: %s", exc)
            return []

        items = data.get("results") or data.get("items") or data.get("data") or []
        return [self._normalize(item) for item in items if self._normalize(item)]

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

    def _fetch_html(self) -> list[dict]:
        try:
            resp = requests.get(
                _SEARCH_URL, headers=self.random_headers(), timeout=20
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Homeless HTML fetch failed: %s", exc)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        # Try embedded JSON blob
        for script in soup.find_all("script"):
            text = script.string or ""
            match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\});", text, re.S)
            if match:
                try:
                    state = json.loads(match.group(1))
                    items = (
                        state.get("search", {})
                        .get("results", {})
                        .get("items", [])
                    )
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

                results.append(
                    {
                        "url": href,
                        "price": price,
                        "rooms": None,
                        "size_m2": None,
                        "neighborhood": "",
                        "raw_text": card.get_text(" ", strip=True),
                        "source": self.source,
                    }
                )
            except Exception:
                continue

        return results
