import logging
import os
from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


def _format(listing: dict, source_url: str) -> str:
    neighborhood = listing.get("neighborhood") or "לא צוין"
    rooms = listing.get("rooms")
    price = listing.get("price")
    url = listing.get("url") or ""
    rooms_str = str(rooms) if rooms is not None else "?"
    price_str = f"{price:,}" if price is not None else "?"
    lines = [f"🏠 {neighborhood} – {rooms_str} חד׳ – {price_str}₪"]
    if url:
        lines.append(url)
    lines.append(f"📍 {source_url}")
    return "\n".join(lines)


async def send(listing: dict, source_url: str) -> bool:
    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    try:
        await bot.send_message(
            chat_id=os.environ["TELEGRAM_CHAT_ID"],
            text=_format(listing, source_url),
        )
        return True
    except TelegramError as exc:
        logger.error("Telegram send failed: %s", exc)
        return False
