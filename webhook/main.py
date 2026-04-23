import logging
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from pydantic import BaseModel
from parser import parse_listings
from notifier import send

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()


class DistillPayload(BaseModel):
    url: str
    text: str
    selector: str = ""


def _passes_filters(listing: dict) -> bool:
    if listing.get("exclude"):
        return False
    price = listing.get("price")
    if price is not None and (price < 5000 or price > 9000):
        return False
    rooms = listing.get("rooms")
    if rooms is not None and (rooms < 2 or rooms > 4):
        return False
    return True


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(payload: DistillPayload):
    try:
        listings = await parse_listings(payload.text)
    except Exception as exc:
        logger.error("Parse failed: %s", exc)
        return {"processed": 0, "sent": 0, "error": str(exc)}

    processed = len(listings)
    sent = 0
    for listing in listings:
        if _passes_filters(listing):
            if await send(listing, payload.url):
                sent += 1

    logger.info("Webhook processed=%d sent=%d source=%s", processed, sent, payload.url)
    return {"processed": processed, "sent": sent}
