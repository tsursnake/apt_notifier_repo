import json
import logging
import re
import requests
from bs4 import BeautifulSoup
from .base import Scraper

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://komo.co.il/rent/tel-aviv"
_API_URL = "https://komo.co.il/api/listings/search"


class KomoScraper(Scraper):
    source = "komo"

    def fetch(self) -> list[dict]:
        listings = self._fetch_api()
        if not listings:
            logger.warning("Komo API returned nothing, falling back to HTML")
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
            }
        )
        payload = {
            "dealType": "rent",
            "propertyTypes": ["apartment"],
            "city": "תל אביב יפו",
            "page": 1,
            "pageSize": 40,
        }
        try:
            resp = requests.post(
                _API_URL, json=payload, headers=headers, timeout=20
            )
            resp.raise_for_status()
            data = resp.json()
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

    def _fetch_html(self) -> list[dict]:
        try:
            resp = requests.get(
                _SEARCH_URL, headers=self.random_headers(), timeout=20
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Komo HTML fetch failed: %s", exc)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script and script.string:
            try:
                nd = json.loads(script.string)
                items = (
                    nd.get("props", {})
                    .get("pageProps", {})
                    .get("listings", [])
                )
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
                    items = state.get("listings") or []
                    for item in items:
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
