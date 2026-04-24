import logging
from dotenv import load_dotenv

load_dotenv()

from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from parser import parse_listings
from notifier import send

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()

_CONTENT_FIELDS = ["diff", "text", "message", "body", "current_snapshot"]


def _strip_html(raw: str) -> str:
    return BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)


def _passes_filters(listing: dict) -> bool:
    url = listing.get("url") or listing.get("raw", "")[:60]
    if listing.get("exclude"):
        logger.info("Filtered [roommate/sublet]: %s", url)
        return False
    price = listing.get("price")
    if price is not None and (price < 5000 or price > 9000):
        logger.info("Filtered [price=%s out of 5000-9000]: %s", price, url)
        return False
    rooms = listing.get("rooms")
    if rooms is not None and (rooms < 2 or rooms > 4):
        logger.info("Filtered [rooms=%s out of 2-4]: %s", rooms, url)
        return False
    return True


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    logger.info("Webhook received keys: %s", list(body.keys()))

    source_url = body.get("url") or body.get("watch_url") or ""
    title = body.get("title") or ""

    content = ""
    for field in _CONTENT_FIELDS:
        value = body.get(field, "")
        if value and value.strip():
            content = _strip_html(value)
            logger.info("Using field %r for content (%d chars)", field, len(content))
            break

    logger.info("Webhook: source=%s title=%r content_len=%d", source_url, title, len(content))
    if not content:
        logger.info("Webhook rejected: no content in payload")
        return {"processed": 0, "sent": 0, "error": "no content in payload"}

    try:
        listings = await parse_listings(content)
    except Exception as exc:
        logger.error("Parse failed: %s", exc)
        return {"processed": 0, "sent": 0, "error": str(exc)}

    processed = len(listings)
    sent = 0
    for listing in listings:
        if _passes_filters(listing):
            if await send(listing, source_url):
                sent += 1

    logger.info("Webhook processed=%d sent=%d source=%s", processed, sent, source_url)
    return {"processed": processed, "sent": sent}
