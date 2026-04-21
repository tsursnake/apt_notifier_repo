import logging
import requests
from bs4 import BeautifulSoup
from .base import Scraper

logger = logging.getLogger(__name__)

# Yad2 internal feed API used by the SPA frontend
_API_URL = (
    "https://gw.yad2.co.il/feed-search-legacy/realestate/rent"
    "?city=5000"          # Tel Aviv
    "&propertyGroup=apartments"
    "&page=1"
    "&rows=40"
)

_BASE_LISTING_URL = "https://www.yad2.co.il/item/"


class Yad2Scraper(Scraper):
    source = "yad2"

    def fetch(self) -> list[dict]:
        listings = self._fetch_api()
        if not listings:
            logger.warning("Yad2 API returned nothing, falling back to HTML scrape")
            listings = self._fetch_html()
        return listings

    # ------------------------------------------------------------------
    # Internal JSON API (preferred)
    # ------------------------------------------------------------------

    def _fetch_api(self) -> list[dict]:
        headers = self.random_headers()
        headers.update(
            {
                "Referer": "https://www.yad2.co.il/realestate/rent",
                "Origin": "https://www.yad2.co.il",
                "Accept": "application/json, text/plain, */*",
            }
        )
        try:
            resp = requests.get(_API_URL, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("Yad2 API request failed: %s", exc)
            return []

        items = data.get("data", {}).get("feed", {}).get("feed_items", [])
        results = []
        for item in items:
            if item.get("type") == "ad":
                listing = self._normalize_api_item(item)
                if listing:
                    results.append(listing)
        return results

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

    def _fetch_html(self) -> list[dict]:
        url = "https://www.yad2.co.il/realestate/rent?city=5000"
        try:
            resp = requests.get(url, headers=self.random_headers(), timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Yad2 HTML fallback failed: %s", exc)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        # Yad2 embeds __NEXT_DATA__ with full listings JSON
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script and script.string:
            import json
            try:
                next_data = json.loads(script.string)
                feed_items = (
                    next_data.get("props", {})
                    .get("pageProps", {})
                    .get("dehydratedState", {})
                    .get("queries", [{}])[0]
                    .get("state", {})
                    .get("data", {})
                    .get("feed", {})
                    .get("feed_items", [])
                )
                for item in feed_items:
                    if item.get("type") == "ad":
                        listing = self._normalize_api_item(item)
                        if listing:
                            results.append(listing)
                if results:
                    return results
            except Exception as exc:
                logger.warning("Yad2 __NEXT_DATA__ parse failed: %s", exc)

        # Last-resort: parse visible cards
        for card in soup.select("div[class*='feeditem']"):
            try:
                link_tag = card.select_one("a[href]")
                href = link_tag["href"] if link_tag else ""
                if not href.startswith("http"):
                    href = "https://www.yad2.co.il" + href

                price_tag = card.select_one("[class*='price']")
                price = None
                if price_tag:
                    try:
                        price = int(
                            "".join(filter(str.isdigit, price_tag.get_text()))
                        )
                    except ValueError:
                        pass

                raw_text = card.get_text(" ", strip=True)
                results.append(
                    {
                        "url": href,
                        "price": price,
                        "rooms": None,
                        "size_m2": None,
                        "neighborhood": "",
                        "raw_text": raw_text,
                        "source": self.source,
                    }
                )
            except Exception:
                continue

        return results
